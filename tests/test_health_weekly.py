"""Тесты недельного пинга инбокса."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from handlers.health import build_weekly


class FakeIndex:
    def __init__(self, notes: list[Any]) -> None:
        self._notes = notes

    async def notes(self) -> list[Any]:
        return self._notes


def _services(inbox: str, notes: list[Any]) -> Any:
    return SimpleNamespace(
        index=FakeIndex(notes),
        settings=SimpleNamespace(obsidian_inbox_dir=inbox, tz=timezone.utc),
    )


def _note(path: str, created: datetime | None = None) -> Any:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    return SimpleNamespace(path=path, folder=folder, created=created)


def test_weekly_uses_configured_inbox() -> None:
    notes = [_note("10_Inbox/a.md"), _note("20_Notes/b.md")]

    text = asyncio.run(build_weekly(_services("10_Inbox", notes)))

    assert "Ждёт разбора: <b>1</b>" in text


def test_weekly_ignores_other_folders() -> None:
    notes = [_note("00_Inbox/a.md")]

    assert asyncio.run(build_weekly(_services("0_Inbox", notes))) == ""


def test_weekly_counts_stale_notes() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=10)
    fresh = datetime.now(timezone.utc) - timedelta(days=1)
    notes = [_note("00_Inbox/old.md", old), _note("00_Inbox/fresh.md", fresh)]

    text = asyncio.run(build_weekly(_services("00_Inbox", notes)))

    assert "Ждёт разбора: <b>2</b>" in text
    assert "старше недели: <b>1</b>" in text


def test_weekly_returns_empty_without_inbox() -> None:
    notes = [_note("20_Notes/b.md")]

    assert asyncio.run(build_weekly(_services("00_Inbox", notes))) == ""


def test_weekly_survives_broken_index() -> None:
    class BrokenIndex:
        async def notes(self) -> list[Any]:
            raise RuntimeError("нет доступа")

    services = SimpleNamespace(
        index=BrokenIndex(),
        settings=SimpleNamespace(obsidian_inbox_dir="00_Inbox", tz=timezone.utc),
    )

    assert asyncio.run(build_weekly(services)) == ""
