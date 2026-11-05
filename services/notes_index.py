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
MAX_FILES = 500
FETCH_CONCURRENCY = 6
SKIP_NAMES = {"Dashboard.md", "Карта.md", "README.md"}

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

    return NoteInfo(
        path=path,
        title=str(title),
        tags=tags,
        category=str(meta.get("category") or ""),
        created=created,
        text=body,
        tasks=tasks,
        note_type=str(meta.get("type") or ""),
    )


class NotesIndex:
    def __init__(self, github: GitHubService, ttl: int = DEFAULT_TTL) -> None:
        self._github = github
        self._ttl = ttl
        self._notes: list[NoteInfo] = []
        self._cache: dict[str, tuple[str, NoteInfo]] = {}
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    # ── Загрузка ─────────────────────────────────────────────

    async def notes(self, force: bool = False) -> list[NoteInfo]:
        loop = asyncio.get_running_loop()
        fresh = loop.time() - self._loaded_at < self._ttl
        if not force and self._notes and fresh:
            return self._notes

        async with self._lock:
            if not force and self._notes and loop.time() - self._loaded_at < self._ttl:
                return self._notes

            blobs = [
                (path, sha)
                for path, sha in await self._github.list_markdown_blobs()
                if PurePosixPath(path).name not in SKIP_NAMES
                and not path.startswith(".")
            ]
            if len(blobs) > MAX_FILES:
                logger.warning("Заметок %s, индексирую первые %s", len(blobs), MAX_FILES)
                blobs = blobs[:MAX_FILES]

            known: dict[str, NoteInfo] = {}
            to_fetch: list[tuple[str, str]] = []
            for path, sha in blobs:
                cached = self._cache.get(path)
                if cached is not None and cached[0] == sha:
                    known[path] = cached[1]
                else:
                    to_fetch.append((path, sha))

            semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

            async def load_one(path: str, sha: str) -> tuple[str, str, NoteInfo | None]:
                async with semaphore:
                    try:
                        raw = await self._github.get_text(path)
                    except GitHubError as exc:
                        logger.warning("Не прочитал %s: %s", path, exc)
                        return path, sha, None
                return path, sha, parse_note(path, raw) if raw else None

            loaded = await asyncio.gather(
                *(load_one(path, sha) for path, sha in to_fetch)
            )
            for path, sha, note in loaded:
                if note is not None and note.note_type != "project":
                    known[path] = note
                    self._cache[path] = (sha, note)

            current = {path for path, _ in blobs}
            self._cache = {
                path: value for path, value in self._cache.items() if path in current
            }
            self._notes = [known[path] for path, _ in blobs if path in known]
            self._loaded_at = loop.time()
            logger.info(
                "Индекс заметок: %s всего, %s обновлено", len(self._notes), len(to_fetch)
            )
            return self._notes

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
