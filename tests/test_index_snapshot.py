"""Тесты загрузки индекса архивом ветки и обработки лимита файлов."""

from __future__ import annotations

import asyncio

import pytest

from services.github_service import GitHubError
from services.notes_index import NotesIndex, parse_note

NOTE = """---
created: 2026-11-04T10:00:00
title: "Заметка"
tags:
  - тест
type: inbox-text
---

# Заметка

- [ ] Сделать дело
"""


def run(coro):
    return asyncio.run(coro)


class SnapshotGitHub:
    def __init__(self, files: dict[str, str], sha: str = "sha1", fail: bool = False):
        self.files = files
        self.sha = sha
        self.fail = fail
        self.snapshot_calls = 0

    async def download_snapshot(self):
        self.snapshot_calls += 1
        if self.fail:
            raise GitHubError("архив недоступен", "нет архива")
        return self.sha, dict(self.files)

    async def list_markdown_blobs(self):  # pragma: no cover - не должен вызываться
        raise AssertionError("при рабочем архиве пофайловое чтение не нужно")

    async def get_text(self, path: str):  # pragma: no cover
        raise AssertionError("не должен вызываться")


class FallbackGitHub:
    def __init__(self, files: dict[str, str]):
        self.files = files

    async def download_snapshot(self):
        raise GitHubError("архив сломан", "нет архива")

    async def list_markdown_blobs(self):
        return [(path, "sha") for path in self.files]

    async def get_text(self, path: str):
        return self.files[path]


def test_snapshot_is_used_for_index() -> None:
    github = SnapshotGitHub(
        {
            "00_Inbox/a.md": NOTE,
            "10_Notes/Карта.md": "# Карта",
            "10_Notes/.hidden.md": "# Скрытая",
        }
    )

    async def go():
        index = NotesIndex(github)
        notes = await index.notes()
        return index, notes

    index, notes = run(go())

    assert github.snapshot_calls == 1
    assert [note.title for note in notes] == ["Заметка"]
    assert index.truncated is None


def test_fallback_to_per_file_when_archive_fails() -> None:
    github = FallbackGitHub({"00_Inbox/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        return await index.notes()

    notes = run(go())

    assert [note.title for note in notes] == ["Заметка"]


def test_same_commit_reuses_index() -> None:
    github = SnapshotGitHub({"00_Inbox/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        first = await index.notes()
        second = await index.notes(force=True)
        return index, first, second

    index, first, second = run(go())

    assert [n.title for n in first] == [n.title for n in second]
    assert github.snapshot_calls == 2  # архив запрошен, но граф пересобран из кэша


def test_truncation_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.notes_index.MAX_FILES", 2)

    github = SnapshotGitHub(
        {
            "00_Inbox/a.md": NOTE,
            "00_Inbox/b.md": NOTE,
            "00_Inbox/c.md": NOTE,
        }
    )

    async def go():
        index = NotesIndex(github)
        notes = await index.notes()
        return index, notes

    index, notes = run(go())

    assert len(notes) == 2
    assert index.truncated == (2, 3)


def test_truncation_cleared_when_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    github = SnapshotGitHub({"00_Inbox/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        await index.notes()
        return index

    index = run(go())
    assert index.truncated is None


def test_dashboard_project_hub_is_indexed() -> None:
    hub = '---\ntype: project\ntitle: "Dashboard"\n---\n\n# Dashboard\n'
    github = SnapshotGitHub(
        {
            "Dashboard.md": "# 🧠 База знаний",
            "20_Projects/Dashboard.md": hub,
            "10_Notes/a.md": NOTE,
        }
    )

    async def go():
        index = NotesIndex(github)
        notes = await index.notes()
        return index, notes

    index, notes = run(go())

    assert [note.title for note in notes] == ["Заметка"]
    assert [project.title for project in index._projects] == ["Dashboard"]


def test_project_hub_is_not_in_search_index() -> None:
    hub = '---\ntype: project\ntitle: "Бот"\n---\n\n# Бот\n'
    github = SnapshotGitHub({"20_Projects/Бот.md": hub, "10_Notes/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        notes = await index.notes()
        return index, notes

    index, notes = run(go())

    assert [note.title for note in notes] == ["Заметка"]
    assert [hub.title for hub in index._projects] == ["Бот"]


def test_parse_note_still_works_for_snapshot_content() -> None:
    note = parse_note("00_Inbox/a.md", NOTE)

    assert note.title == "Заметка"
    assert note.tasks == ("Сделать дело",)
