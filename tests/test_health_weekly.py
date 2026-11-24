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


def test_money_range_sums_dates() -> None:
    from datetime import date

    from handlers.health import _money_range

    rows = [
        {"date": "2026-11-06", "kind": "expense", "amount": "100"},
        {"date": "2026-11-12", "kind": "income", "amount": "500"},
        {"date": "2026-11-05", "kind": "expense", "amount": "999"},
        {"date": "мусор", "kind": "expense", "amount": "5"},
    ]

    expense, income = _money_range(
        rows, date(2026, 11, 6), date(2026, 11, 12)
    )

    assert expense == 100
    assert income == 500


def test_weekly_survives_broken_index() -> None:
    class BrokenIndex:
        async def notes(self) -> list[Any]:
            raise RuntimeError("нет доступа")

    services = SimpleNamespace(
        index=BrokenIndex(),
        settings=SimpleNamespace(obsidian_inbox_dir="00_Inbox", tz=timezone.utc),
    )

    assert asyncio.run(build_weekly(services)) == ""


def test_budget_alerts_warn_and_over() -> None:
    from handlers.health import _budget_alerts

    class Index:
        async def money_budgets(self) -> dict[str, float]:
            return {"еда": 8000.0, "автомобиль": 7000.0}

        async def money_categories(self) -> list[str]:
            return ["Еда", "Автомобиль"]

    rows = [
        {
            "date": "2026-11-01",
            "kind": "expense",
            "amount": "6800",
            "category": "Еда",
        },
        {
            "date": "2026-11-02",
            "kind": "expense",
            "amount": "8400",
            "category": "Автомобиль",
        },
    ]
    services = SimpleNamespace(index=Index())

    alerts = asyncio.run(_budget_alerts(services, rows, "2026-11"))

    assert "Еда: 85% лимита" in alerts
    assert "Автомобиль: перерасход 1 400 ₽" in alerts


def test_weekly_render_shows_budgets() -> None:
    from handlers.health import WeeklyReview, render_weekly

    review = WeeklyReview(
        period="10.11–16.11",
        notes_week=1,
        tasks_done=1,
        tasks_open=1,
        overdue=0,
        inbox=1,
        inbox_stale=0,
        expense=100,
        income=0,
        prev_expense=0,
        prev_income=0,
        budget_alerts=["Еда: 85% лимита"],
    )

    text = render_weekly(review)

    assert "Бюджеты" in text
    assert "85%" in text
