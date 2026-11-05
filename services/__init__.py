"""Сервисный слой: LLM, GitHub, индекс заметок и сборка заметки."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings

from .github_service import GitHubError, GitHubService
from .groq_service import GroqError, GroqService
from .note_builder import (
    NoteDraft,
    TaskItem,
    build_markdown,
    format_task,
    make_filename,
    normalize_tags,
    sanitize_tag,
    slugify,
    wiki_link,
    with_up_link,
)
from .notes_index import NoteInfo, NotesIndex

__all__ = [
    "GitHubError",
    "GitHubService",
    "GroqError",
    "GroqService",
    "NoteDraft",
    "NoteInfo",
    "NotesIndex",
    "Services",
    "TaskItem",
    "build_markdown",
    "format_task",
    "make_filename",
    "normalize_tags",
    "sanitize_tag",
    "slugify",
    "wiki_link",
    "with_up_link",
]


@dataclass(slots=True)
class Services:
    """То, что прокидывается в хендлеры через Dispatcher.workflow_data."""

    settings: Settings
    groq: GroqService
    github: GitHubService
    index: NotesIndex
