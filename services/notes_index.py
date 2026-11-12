"""Кэшированный индекс заметок из репозитория.

Нужен, чтобы бот мог искать по базе, собирать сводки и предлагать связи,
не выкачивая всё заново на каждый запрос.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

import yaml

from .github_service import GitHubError, GitHubService

logger = logging.getLogger(__name__)

TASK_RE = re.compile(r"^[ \t]*- \[ \] (.+)$", re.MULTILINE)
HEADING_RE = re.compile(r"^# (.+)$", re.MULTILINE)
DUE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
DONE_RE = re.compile(r"✅\s*\d{4}-\d{2}-\d{2}")
PRIORITY_MARKS = ("⏫", "🔼", "🔽")

DEFAULT_TTL = 600
MAX_FILES = 2000
FETCH_CONCURRENCY = 6
SKIP_NAMES = {"Карта.md", "README.md"}
SKIP_ROOT_NAMES = {"Dashboard.md"}
SKIP_TYPES = {"project", "project-template", "money-categories"}

STOPWORDS = frozenset(
    {
        "что", "про", "как", "где", "когда", "почему", "зачем", "кто", "это",
        "я", "мы", "мне", "меня", "мой", "мои", "моя", "был", "была", "были",
        "было", "будет", "есть", "и", "или", "а", "но", "в", "во", "на", "по",
        "с", "со", "у", "к", "от", "до", "за", "из", "о", "об", "для", "не",
        "ни", "же", "ли", "то", "всё", "все", "писал", "писала", "говорил",
        "сказал", "записал", "надиктовывал", "помню", "знаю", "там", "тут",
        "этот", "эта", "эти", "ещё", "уже", "можно", "надо",
    }
)

WORD_RE = re.compile(r"[0-9a-zа-яё]+")


@dataclass(slots=True)
class NoteInfo:
    path: str
    title: str
    tags: tuple[str, ...]
    category: str
    created: datetime | None
    text: str
    tasks: tuple[str, ...]
    note_type: str = ""
    aliases: tuple[str, ...] = ()
    description: str = ""
    up: str = ""

    @property
    def stem(self) -> str:
        return PurePosixPath(self.path).stem

    @property
    def folder(self) -> str:
        return str(PurePosixPath(self.path).parent)


def task_text(raw: str) -> str:
    """Убирает служебные метки Tasks: срок, приоритет, отметку выполнения."""
    text = DUE_RE.sub("", raw)
    text = DONE_RE.sub("", text)
    for mark in PRIORITY_MARKS:
        text = text.replace(mark, "")
    return " ".join(text.split())


def task_due(raw: str) -> str:
    match = DUE_RE.search(raw)
    return match.group(1) if match else ""


def task_id(path: str, raw: str) -> str:
    return hashlib.sha1(f"{path}\n{raw}".encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class TaskRef:
    note: NoteInfo
    raw: str
    id: str

    @property
    def text(self) -> str:
        return task_text(self.raw)

    @property
    def due(self) -> str:
        return task_due(self.raw)


def parse_note(path: str, raw: str) -> NoteInfo:
    meta: dict = {}
    body = raw

    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            header = raw[3:end]
            body = raw[end + 4 :]
            try:
                parsed = yaml.safe_load(header)
                if isinstance(parsed, dict):
                    meta = parsed
            except yaml.YAMLError:
                logger.warning("Битый frontmatter в %s", path)

    heading = HEADING_RE.search(body)
    title = meta.get("title") or (heading.group(1).strip() if heading else "")
    if not title:
        title = PurePosixPath(path).stem

    tags_raw = meta.get("tags") or []
    if isinstance(tags_raw, str):
        tags_raw = [tags_raw]
    tags = tuple(
        str(tag).lstrip("#") for tag in tags_raw if str(tag).strip()
    )

    created_raw = meta.get("created")
    created: datetime | None = None
    if isinstance(created_raw, datetime):
        created = created_raw
    elif isinstance(created_raw, str):
        try:
            created = datetime.fromisoformat(created_raw)
        except ValueError:
            created = None
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    tasks = tuple(match.strip() for match in TASK_RE.findall(body))

    aliases_raw = meta.get("aliases") or []
    if isinstance(aliases_raw, str):
        aliases_raw = [aliases_raw]
    aliases = tuple(str(item).strip() for item in aliases_raw if str(item).strip())

    up_raw = meta.get("up") or ""
    if isinstance(up_raw, list):
        up_raw = up_raw[0] if up_raw else ""
    up = str(up_raw).strip()
    if up.startswith("[[") and up.endswith("]]"):
        up = up[2:-2]
    up = up.split("|")[0].strip()

    return NoteInfo(
        path=path,
        title=str(title),
        tags=tags,
        category=str(meta.get("category") or ""),
        created=created,
        text=body,
        tasks=tasks,
        note_type=str(meta.get("type") or ""),
        aliases=aliases,
        description=str(meta.get("description") or "").strip(),
        up=up,
    )


def parse_money_categories(text: str) -> list[str]:
    """Список категорий из файла: по одной на строку, можно с дефисом."""
    result: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ">", "```", "|")):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if not line or len(line) > 40:
            continue
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            result.append(line)
    return result[:40]


class NotesIndex:
    def __init__(self, github: GitHubService, ttl: int = DEFAULT_TTL) -> None:
        self._github = github
        self._ttl = ttl
        self._notes: list[NoteInfo] = []
        self._projects: list[NoteInfo] = []
        self._money_categories: list[str] = []
        self._snapshot_sha: str | None = None
        self._truncated: tuple[int, int] | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def truncated(self) -> tuple[int, int] | None:
        """(проиндексировано, всего), если заметок больше MAX_FILES."""
        return self._truncated

    # ── Загрузка ─────────────────────────────────────────────

    async def notes(self, force: bool = False) -> list[NoteInfo]:
        loop = asyncio.get_running_loop()
        fresh = loop.time() - self._loaded_at < self._ttl
        if not force and self._notes and fresh:
            return self._notes

        async with self._lock:
            if not force and self._notes and loop.time() - self._loaded_at < self._ttl:
                return self._notes

            documents, commit = await self._fetch_documents()

            # Ветка не менялась — пересобирать индекс незачем.
            if documents is None:
                self._loaded_at = loop.time()
                return self._notes

            known: dict[str, NoteInfo] = {}
            projects: dict[str, NoteInfo] = {}
            money_categories: list[str] = []
            for path, raw in documents.items():
                note = parse_note(path, raw) if raw else None
                if note is None:
                    continue
                if note.note_type == "project":
                    projects[path] = note
                elif note.note_type == "money-categories":
                    money_categories = parse_money_categories(note.text)
                elif note.note_type not in SKIP_TYPES:
                    known[path] = note

            self._notes = [known[path] for path in documents if path in known]
            self._projects = [projects[path] for path in documents if path in projects]
            self._money_categories = money_categories
            self._snapshot_sha = commit
            self._loaded_at = loop.time()
            logger.info("Индекс заметок: %s файлов", len(documents))
            return self._notes

    async def _fetch_documents(self) -> tuple[dict[str, str] | None, str | None]:
        """(путь -> текст, sha коммита). None вместо словаря — ветка не менялась."""
        head_reader = getattr(self._github, "branch_head", None)
        if head_reader is not None:
            try:
                head = await head_reader()
            except GitHubError as exc:
                logger.warning("Не удалось узнать состояние ветки: %s", exc)
                head = ""
            if head and head == self._snapshot_sha and self._notes:
                return None, head

        loader = getattr(self._github, "download_snapshot", None)
        if loader is not None:
            try:
                commit, files = await loader()
            except GitHubError as exc:
                logger.warning("Архив ветки недоступен, читаю по файлам: %s", exc)
            else:
                filtered = {
                    path: raw for path, raw in files.items() if not self._skip(path)
                }
                return self._limit(filtered), commit

        blobs = [
            (path, sha)
            for path, sha in await self._github.list_markdown_blobs()
            if not self._skip(path)
        ]
        blobs = self._limit(blobs)
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def load_one(path: str) -> tuple[str, str]:
            async with semaphore:
                try:
                    return path, await self._github.get_text(path)
                except GitHubError as exc:
                    logger.warning("Не прочитал %s: %s", path, exc)
                    return path, ""

        loaded = await asyncio.gather(*(load_one(path) for path, _ in blobs))
        return {path: raw for path, raw in loaded if raw}, None

    @staticmethod
    def _skip(path: str) -> bool:
        pure = PurePosixPath(path)
        if len(pure.parts) == 1 and pure.name in SKIP_ROOT_NAMES:
            return True
        if pure.name in SKIP_NAMES:
            return True
        return any(part.startswith(".") for part in pure.parts)

    def _limit(self, items):
        """Обрезает список/словарь до MAX_FILES и запоминает факт обрезки."""
        total = len(items)
        if total <= MAX_FILES:
            self._truncated = None
            return items

        self._truncated = (MAX_FILES, total)
        logger.warning(
            "Заметок %s, индексирую первые %s — остальные не попадут в поиск",
            total,
            MAX_FILES,
        )
        if isinstance(items, dict):
            return dict(list(items.items())[:MAX_FILES])
        return items[:MAX_FILES]

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    # ── Запросы ──────────────────────────────────────────────

    async def search(self, query: str, limit: int = 5) -> list[NoteInfo]:
        """Пословный поиск: «что я писал про дашборд» тоже находит заметки."""
        phrase = query.strip().casefold()
        tokens = [
            token
            for token in WORD_RE.findall(phrase)
            if len(token) >= 3 and token not in STOPWORDS
        ]
        if not tokens and not phrase:
            return []

        scored: list[tuple[int, NoteInfo]] = []
        for note in await self.notes():
            title = note.title.casefold()
            text = note.text.casefold()
            tags = [tag.casefold() for tag in note.tags]

            score = 0
            for token in tokens:
                if token in title:
                    score += 3
                if any(token in tag for tag in tags):
                    score += 2
                if token in text:
                    score += 1

            if phrase and (phrase in title or phrase in text):
                score += 5

            if score:
                scored.append((score, note))

        scored.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
        return [note for _, note in scored[:limit]]

    async def similar(self, tags: list[str], limit: int = 2) -> list[NoteInfo]:
        wanted = {tag.casefold() for tag in tags if tag}
        if not wanted:
            return []

        matches: list[tuple[int, NoteInfo]] = []
        for note in await self.notes():
            overlap = len(wanted & {tag.casefold() for tag in note.tags})
            if overlap:
                matches.append((overlap, note))

        matches.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
        return [note for _, note in matches[:limit]]

    async def projects(self) -> list[NoteInfo]:
        """Хабы проектов (type: project) — для кнопок выбора проекта."""
        await self.notes()
        return self._projects

    async def areas(self) -> list[NoteInfo]:
        """Бытовые области (type: area) — сюда бот дописывает задачи."""
        return [note for note in await self.notes() if note.note_type == "area"]

    async def money_categories(self) -> list[str]:
        """Категории денег из файла в хранилище (пусто, если файла нет)."""
        await self.notes()
        return self._money_categories

    async def top_tags(self, limit: int = 30) -> list[str]:
        """Самые частые теги базы — чтобы модель не плодила синонимы."""
        counts: dict[str, int] = {}
        for note in await self.notes():
            for tag in note.tags:
                key = tag.casefold()
                counts[key] = counts.get(key, 0) + 1
        return sorted(counts, key=lambda tag: (-counts[tag], tag))[:limit]

    async def open_tasks(self) -> list[TaskRef]:
        refs: list[TaskRef] = []
        for note in await self.notes():
            for raw in note.tasks:
                refs.append(TaskRef(note=note, raw=raw, id=task_id(note.path, raw)))
        return refs

    async def find_task(self, identifier: str) -> TaskRef | None:
        for note in await self.notes():
            for raw in note.tasks:
                if task_id(note.path, raw) == identifier:
                    return TaskRef(note=note, raw=raw, id=identifier)
        return None
