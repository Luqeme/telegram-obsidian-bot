"""Тесты ограничений на голосовые сообщения."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import Message

from handlers.notes import (
    MAX_AUDIO_SECONDS,
    _fallback_title,
    _find_open_task,
    _match_target,
    check_voice_limits,
)
from handlers import menu as menu_handlers

LIMIT_MB = 20


def test_normal_voice_is_allowed() -> None:
    assert check_voice_limits(size=1_000_000, duration=30, limit_mb=LIMIT_MB) is None


def test_exact_limits_are_allowed() -> None:
    assert (
        check_voice_limits(
            size=LIMIT_MB * 1024 * 1024,
            duration=MAX_AUDIO_SECONDS,
            limit_mb=LIMIT_MB,
        )
        is None
    )


def test_too_large_is_rejected() -> None:
    reason = check_voice_limits(
        size=LIMIT_MB * 1024 * 1024 + 1, duration=30, limit_mb=LIMIT_MB
    )
    assert reason is not None
    assert "МБ" in reason


def test_too_long_is_rejected() -> None:
    reason = check_voice_limits(
        size=1000, duration=MAX_AUDIO_SECONDS + 1, limit_mb=LIMIT_MB
    )
    assert reason is not None
    assert "мин" in reason


def test_project_matches_title_or_alias() -> None:
    hubs = [
        SimpleNamespace(
            title="Peptrack",
            aliases=("Peptrack", "пептрек", "Shot Bot", "шот бот", "дневник уколов"),
        ),
        SimpleNamespace(title="Obsidian", aliases=("Бот", "Обсидиан")),
    ]

    assert _match_target("Peptrack", hubs).title == "Peptrack"
    assert _match_target("shot-bot", hubs).title == "Peptrack"
    assert _match_target("дневник уколов", hubs).title == "Peptrack"
    assert _match_target("бот", hubs).title == "Obsidian"
    assert _match_target("обсидиан", hubs).title == "Obsidian"
    assert _match_target("несуществующий", hubs) is None
    assert _match_target("", hubs) is None


def test_fix_reply_filter_matches_prompt() -> None:
    import asyncio
    from types import SimpleNamespace

    from handlers.notes import FIX_PENDING, IsFixReply

    FIX_PENDING[5] = ("token", 42)
    try:
        match = SimpleNamespace(
            from_user=SimpleNamespace(id=5),
            reply_to_message=SimpleNamespace(message_id=42),
        )
        other = SimpleNamespace(
            from_user=SimpleNamespace(id=5),
            reply_to_message=SimpleNamespace(message_id=43),
        )
        assert asyncio.run(IsFixReply()(match)) is True
        assert asyncio.run(IsFixReply()(other)) is False
    finally:
        FIX_PENDING.pop(5, None)


def test_fallback_title_uses_first_words() -> None:
    assert _fallback_title("Купить молоко завтра утром, а ещё позвонить в сервис.") == (
        "Купить молоко завтра утром, а ещё позвонить"
    )
    assert _fallback_title("   ") == "Заметка"


def test_find_open_task_by_past_tense() -> None:
    tasks = [
        SimpleNamespace(text="Купить молоко"),
        SimpleNamespace(text="Оплатить интернет"),
    ]

    assert _find_open_task("купил молоко", tasks).text == "Купить молоко"
    assert _find_open_task("оплатил интернет", tasks).text == "Оплатить интернет"
    assert _find_open_task("сделал отчёт", tasks) is None


def test_card_has_no_github_link() -> None:
    from services.note_builder import NoteDraft

    from handlers.notes import _render_card

    draft = NoteDraft(
        is_meaningful=True,
        title="Тест",
        category="Мысль",
        tags=["тест"],
        summary="Проверка карточки.",
    )
    card = _render_card("00_Inbox/2026-11-04_00-00-00_test.md", draft)
    assert "github.com" not in card
    assert "00_Inbox/2026-11-04_00-00-00_test.md" in card


def _draft_with_tasks(tasks):
    from services.note_builder import NoteDraft

    return NoteDraft(
        is_meaningful=True,
        title="Тест",
        category="Задача",
        tags=["тест"],
        summary="Кратко о сути.",
        tasks=tasks,
    )


def test_card_lists_tasks() -> None:
    from handlers.notes import _render_card

    card = _render_card(
        "00_Inbox/x.md", _draft_with_tasks(["Оплатить интернет", "Купить хлеб"])
    )
    assert "📋 <b>Задачи</b>" in card
    assert "• Оплатить интернет" in card
    assert "• Купить хлеб" in card
    assert "Задач: 2" not in card


def test_card_limits_task_list() -> None:
    from handlers.notes import MAX_CARD_TASKS, _render_card

    tasks = [f"Задача номер {i}" for i in range(MAX_CARD_TASKS + 5)]
    card = _render_card("00_Inbox/x.md", _draft_with_tasks(tasks))

    assert card.count("•") == MAX_CARD_TASKS
    assert "…и ещё 5" in card


def test_card_escapes_tasks() -> None:
    from handlers.notes import _render_card

    card = _render_card("00_Inbox/x.md", _draft_with_tasks(["<b>не жирный</b>"]))
    assert "&lt;b&gt;" in card
    assert "<b>не жирный</b>" not in card


def test_card_without_tasks_has_no_section() -> None:
    from handlers.notes import _render_card

    card = _render_card("00_Inbox/x.md", _draft_with_tasks([]))
    assert "📋" not in card


def test_csv_row_quotes_commas() -> None:
    from handlers.notes import _csv_row

    assert (
        _csv_row(["2026-11-04", "expense", "540", "Еда", "обед, кофе"])
        == '2026-11-04,expense,540,Еда,"обед, кофе"'
    )


def test_format_amount() -> None:
    from handlers.notes import _format_amount

    assert _format_amount(540) == "540"
    assert _format_amount(540.5) == "540.50"


def test_money_fields_default_to_none() -> None:
    from services.note_builder import NoteDraft

    draft = NoteDraft(is_meaningful=True, title="Тест", category="Мысль")
    assert draft.money_kind == "none"
    assert draft.money_amount == 0
    assert draft.money_category == ""


def _menu_callback(data: str, message=None, user_id: int = 2):
    async def answer(*args, **kwargs) -> bool:
        return True

    return SimpleNamespace(
        data=data,
        message=message,
        from_user=SimpleNamespace(id=user_id),
        bot="bot-stub",
        answer=answer,
    )


def test_menu_report_opens_widget_directly() -> None:
    calls: list[tuple] = []
    original = menu_handlers.send_report

    async def fake_report(bot, chat_id, services, view="current", **kwargs) -> None:
        calls.append((bot, chat_id, services, view))

    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 2, "type": "private"},
        }
    )
    callback = _menu_callback("menu:report", message)

    menu_handlers.send_report = fake_report
    try:
        asyncio.run(menu_handlers.on_menu(callback, "services"))
    finally:
        menu_handlers.send_report = original

    assert calls == [("bot-stub", 2, "services", "current")]


def test_menu_report_works_for_inaccessible_message() -> None:
    """Старое меню приходит как InaccessibleMessage — отчёт всё равно уходит."""
    from aiogram.types import InaccessibleMessage

    calls: list[tuple] = []
    original = menu_handlers.send_report

    async def fake_report(bot, chat_id, services, view="current", **kwargs) -> None:
        calls.append((bot, chat_id, view))

    message = InaccessibleMessage.model_validate(
        {"message_id": 1, "date": 0, "chat": {"id": 2, "type": "private"}}
    )
    callback = _menu_callback("menu:report", message)

    menu_handlers.send_report = fake_report
    try:
        asyncio.run(menu_handlers.on_menu(callback, "services"))
    finally:
        menu_handlers.send_report = original

    assert calls == [("bot-stub", 2, "current")]


def test_menu_today_works_for_inaccessible_message() -> None:
    from aiogram.types import InaccessibleMessage

    calls: list[tuple] = []
    original = menu_handlers.send_today

    async def fake_today(bot, chat_id, services, **kwargs) -> None:
        calls.append((bot, chat_id))

    message = InaccessibleMessage.model_validate(
        {"message_id": 1, "date": 0, "chat": {"id": 2, "type": "private"}}
    )
    callback = _menu_callback("menu:today", message)

    menu_handlers.send_today = fake_today
    try:
        asyncio.run(menu_handlers.on_menu(callback, "services"))
    finally:
        menu_handlers.send_today = original

    assert calls == [("bot-stub", 2)]


def test_menu_report_reaches_report_state() -> None:
    from datetime import datetime, timezone

    from handlers import report as report_handlers

    calls: list[tuple] = []

    async def fake_read(_services) -> list[dict]:
        return []

    async def fake_send(bot, chat_id, services, rows, view) -> None:
        calls.append((chat_id, view, rows))

    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 2, "type": "private"},
        }
    )
    callback = _menu_callback("menu:report", message)
    services = SimpleNamespace(
        settings=SimpleNamespace(
            tz=timezone.utc,
            telegram_bot_token="token",
        ),
        github=SimpleNamespace(),
    )

    originals = (report_handlers.read_money, report_handlers._send_report_state)
    report_handlers.read_money = fake_read
    report_handlers._send_report_state = fake_send
    try:
        asyncio.run(menu_handlers.on_menu(callback, services))
    finally:
        report_handlers.read_money, report_handlers._send_report_state = originals

    assert calls and calls[0][0] == 2
    assert calls[0][1] == "current"
    assert isinstance(datetime.now(timezone.utc), datetime)
