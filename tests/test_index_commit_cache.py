"""Если ветка не менялась, архив не скачивается повторно."""

from __future__ import annotations

import asyncio

from services.notes_index import NotesIndex

NOTE = """---
created: 2026-11-04T10:00:00
title: "Заметка"
type: inbox-text
---

# Заметка
"""


class HeadAwareGitHub:
    def __init__(self, files: dict[str, str], sha: str = "sha1"):
        self.files = files
        self.sha = sha
        self.head_calls = 0
        self.snapshot_calls = 0

    async def branch_head(self) -> str:
        self.head_calls += 1
        return self.sha

    async def download_snapshot(self):
        self.snapshot_calls += 1
        return self.sha, dict(self.files)


def test_unchanged_branch_skips_archive_download() -> None:
    github = HeadAwareGitHub({"00_Inbox/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        first = await index.notes()
        second = await index.notes(force=True)
        return first, second

    first, second = asyncio.run(go())

    assert github.head_calls == 2
    assert github.snapshot_calls == 1
    assert [note.title for note in first] == [note.title for note in second]


def test_changed_branch_downloads_again() -> None:
    github = HeadAwareGitHub({"00_Inbox/a.md": NOTE})

    async def go():
        index = NotesIndex(github)
        await index.notes()
        github.sha = "sha2"
        github.files["00_Inbox/b.md"] = NOTE.replace('"Заметка"', '"Вторая"')
        notes = await index.notes(force=True)
        return notes

    notes = asyncio.run(go())

    assert github.snapshot_calls == 2
    assert len(notes) == 2
