"""Кэшированный индекс заметок из репозитория.

Нужен, чтобы бот мог искать по базе, собирать сводки и предлагать связи,
не выкачивая всё заново на каждый запрос.
"""

from __future__ import annotations

import asyncio
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

DEFAULT_TTL = 600
MAX_FILES = 500
FETCH_CONCURRENCY = 6
SKIP_NAMES = {"Dashboard.md", "README.md"}


@dataclass(slots=True)
class NoteInfo:
    path: str
    title: str
    tags: tuple[str, ...]
    category: str
    created: datetime | None
    text: str
    tasks: tuple[str, ...]

    @property
    def stem(self) -> str:
        return PurePosixPath(self.path).stem

    @property
    def folder(self) -> str:
        return str(PurePosixPath(self.path).parent)


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
    )


class NotesIndex:
    def __init__(self, github: GitHubService, ttl: int = DEFAULT_TTL) -> None:
        self._github = github
        self._ttl = ttl
        self._notes: list[NoteInfo] = []
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

            paths = [
                path
                for path in await self._github.list_markdown_paths()
                if PurePosixPath(path).name not in SKIP_NAMES
                and not path.startswith(".")
            ]
            if len(paths) > MAX_FILES:
                logger.warning("Заметок %s, индексирую первые %s", len(paths), MAX_FILES)
                paths = paths[:MAX_FILES]

            semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

            async def load_one(path: str) -> NoteInfo | None:
                async with semaphore:
                    try:
                        raw = await self._github.get_text(path)
                    except GitHubError as exc:
                        logger.warning("Не прочитал %s: %s", path, exc)
                        return None
                return parse_note(path, raw) if raw else None

            loaded = await asyncio.gather(*(load_one(path) for path in paths))
            self._notes = [note for note in loaded if note is not None]
            self._loaded_at = loop.time()
            logger.info("Индекс заметок: %s файлов", len(self._notes))
            return self._notes

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    # ── Запросы ──────────────────────────────────────────────

    async def search(self, query: str, limit: int = 5) -> list[NoteInfo]:
        needle = query.strip().casefold()
        if not needle:
            return []

        scored: list[tuple[int, NoteInfo]] = []
        for note in await self.notes():
            score = 0
            if needle in note.title.casefold():
                score += 3
            if any(needle in tag.casefold() for tag in note.tags):
                score += 2
            if needle in note.text.casefold():
                score += 1
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
