"""Тесты главного меню."""

from __future__ import annotations

from handlers.menu_ui import main_menu
from handlers.menu import _show_home, _show_projects
from handlers.report import months_menu, report_menu


class FakeMessage:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.calls.append({"text": text, **kwargs})


class FakeIndex:
    def __init__(self, tasks=None, notes=None, hubs=None) -> None:
        self._tasks = tasks or []
        self._notes = notes or []
        self._hubs = hubs or []

    async def open_tasks(self):
        return self._tasks

    async def notes(self):
        return self._notes

    async def projects(self):
        return self._hubs


def test_menu_has_all_actions() -> None:
    keyboard = main_menu()
    data = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert data == [
        "menu:find",
        "menu:ask",
        "menu:today",
        "menu:report",
        "menu:home",
        "menu:inbox",
        "menu:projects",
        "menu:undo",
        "menu:help",
    ]
    assert all(1 <= len(row) <= 2 for row in keyboard.inline_keyboard)


def test_report_menu_has_four_periods() -> None:
    keyboard = report_menu()
    data = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert data == ["rep:now", "rep:prev", "rep:months", "rep:year", "rep:main"]


def test_months_menu_lists_months_with_data() -> None:
    keyboard = months_menu(
        [
            {"date": "2026-11-01"},
            {"date": "2026-10-01"},
            {"date": "2026-10-02"},
        ]
    )
    data = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert data == ["rep:m:2026-11", "rep:m:2026-10", "rep:back"]


def test_home_shows_open_household_tasks() -> None:
    import asyncio
    from types import SimpleNamespace

    task = SimpleNamespace(
        note=SimpleNamespace(folder="30_Дом"),
        text="Купить молоко",
        id="abc",
        due="",
    )
    services = SimpleNamespace(index=FakeIndex(tasks=[task]))
    message = FakeMessage()

    asyncio.run(_show_home(message, services))

    assert "Бытовые дела" in message.calls[0]["text"]
    assert message.calls[0]["reply_markup"] is not None


def test_projects_counts_notes_and_tasks() -> None:
    import asyncio
    from types import SimpleNamespace

    hub = SimpleNamespace(title="Бот", aliases=())
    note = SimpleNamespace(up="Бот")
    task = SimpleNamespace(note=SimpleNamespace(up="Бот"))
    services = SimpleNamespace(
        index=FakeIndex(tasks=[task], notes=[note], hubs=[hub])
    )
    message = FakeMessage()

    asyncio.run(_show_projects(message, services))

    text = message.calls[0]["text"]
    assert "Бот" in text
    assert "заметок 1" in text
    assert "задач 1" in text
