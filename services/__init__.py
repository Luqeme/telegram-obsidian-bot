"""Сервисный слой: LLM, GitHub и сборка заметки."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings

from .github_service import GitHubError, GitHubService
from .groq_service import GroqError, GroqService
from .note_builder import (
    NoteDraft,
    build_markdown,
    make_filename,
    normalize_tags,
    sanitize_tag,
    slugify,
)

__all__ = [
    "GitHubError",
    "GitHubService",
    "GroqError",
    "GroqService",
    "NoteDraft",
    "Services",
    "build_markdown",
    "make_filename",
    "normalize_tags",
    "sanitize_tag",
    "slugify",
]


@dataclass(slots=True)
class Services:
    """То, что прокидывается в хендлеры через Dispatcher.workflow_data."""

    settings: Settings
    groq: GroqService
    github: GitHubService
