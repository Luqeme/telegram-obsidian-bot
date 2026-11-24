"""Кнопки категорий и отмены под подтверждением траты."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import Message

from handlers.notes import on_money_cancel, on_money_category
from services.money import note_hash

RAW = (
    "date,kind,amount,category,note\n"
    '2026-11-13,expense,540,Еда,"потратил 540 на обед"\n'
)
NOTE = "потратил 540 на обед"


class FakeGithub:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.replace: tuple[str, str] | None = None
        self.removed: list[str] | None = None

    async def get_text(self, path: str) -> str:
        return self.raw

    async def replace_line(self, path, old_line, new_line, message) -> bool:
        self.replace = (old_line, new_line)
        self.raw = self.raw.replace(old_line, new_line)
        return True

    async def remove_lines(self, path, lines, message) -> int:
        self.removed = list(lines)
        self.raw = "\n".join(
            line for line in self.raw.splitlines() if line not in lines
        )
        return len(lines)


class FakeIndex:
    async def money_budgets(self) -> dict[str, float]:
        return {"еда": 8000.0}

    async def money_categories(self) -> list[str]:
        return ["Еда", "Автомобиль", "Аренда"]


def _services(raw: str):
    import zoneinfo

    settings = SimpleNamespace(tz=zoneinfo.ZoneInfo("UTC"))
    return SimpleNamespace(
        settings=settings,
        github=FakeGithub(raw),
        index=FakeIndex(),
    )


def _message() -> Message:
    return Message.model_validate(
        {"message_id": 1, "date": 0, "chat": {"id": 2, "type": "private"}}
    )


def _callback(data: str, message: Message, answers: list[str]):
    async def answer(text: str = "", **kwargs) -> bool:
        answers.append(text)
        return True

    return SimpleNamespace(data=data, message=message, answer=answer)


def _run(handler, callback, services) -> None:
    asyncio.run(handler(callback, services))


def test_category_callback_rewrites_row() -> None:
    services = _services(RAW)
    message = _message()
    texts: list[str] = []
    answers: list[str] = []

    original = Message.edit_text

    async def fake_edit(self, text, **kwargs):
        texts.append(text)

    Message.edit_text = fake_edit
    try:
        _run(
            on_money_category,
            _callback(f"mc:540:{note_hash(NOTE)}:Автомобиль", message, answers),
            services,
        )
    finally:
        Message.edit_text = original

    assert services.github.replace is not None
    assert "Автомобиль" in services.github.replace[1]
    assert "Еда" in services.github.replace[0]
    assert answers and "Автомобиль" in answers[0]
    assert texts and "Автомобиль" in texts[0]


def test_category_callback_unknown_row() -> None:
    services = _services(RAW)
    message = _message()
    answers: list[str] = []

    _run(
        on_money_category,
        _callback("mc:540:zzzzzz:Аренда", message, answers),
        services,
    )

    assert services.github.replace is None
    assert answers and "изменилась" in answers[0]


def test_cancel_callback_removes_row() -> None:
    services = _services(RAW)
    message = _message()
    texts: list[str] = []
    answers: list[str] = []

    original = Message.edit_text

    async def fake_edit(self, text, **kwargs):
        texts.append(text)

    Message.edit_text = fake_edit
    try:
        _run(
            on_money_cancel,
            _callback(f"mx:540:{note_hash(NOTE)}", message, answers),
            services,
        )
    finally:
        Message.edit_text = original

    assert services.github.removed == [
        '2026-11-13,expense,540,Еда,"потратил 540 на обед"'
    ]
    assert answers and "Отменено" in answers[0]
    assert texts and "отменена" in texts[0]


def test_cancel_callback_unknown_row() -> None:
    services = _services(RAW)
    message = _message()
    answers: list[str] = []

    _run(
        on_money_cancel,
        _callback("mx:540:zzzzzz", message, answers),
        services,
    )

    assert services.github.removed is None
    assert answers and "изменилась" in answers[0]


def test_money_keyboard_fits_callback_limit() -> None:
    from handlers.notes import _money_keyboard

    keyboard = _money_keyboard("540", NOTE, ["Еда", "Очень длинная категория " * 3])

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert buttons[-1].text == "❌ Отменить"
    for button in buttons:
        assert len((button.callback_data or "").encode("utf-8")) <= 64
    assert any(button.text == "Еда" for button in buttons)
    assert all("Очень длинная" not in button.text for button in buttons)
