"""Бюджеты: разбор лимитов, фразы и запись в файл категорий."""

from __future__ import annotations

import asyncio

from services.money import (
    budget_status,
    category_spent,
    match_category,
    parse_limit_phrase,
    parse_rows,
)
from services.notes_index import (
    parse_money_budgets,
    parse_money_categories,
    set_money_limit,
)

CATEGORIES = ["Еда", "Аренда", "Сигареты", "Аптека", "Автомобиль", "Прочее"]

FILE = """# 💰 Категории

- Еда — 8 000
- Аренда
- Сигареты
- Аптека
- Автомобиль — 7 000
- Прочее
"""


def test_parse_budgets_from_file() -> None:
    budgets = parse_money_budgets(FILE)

    assert budgets == {"еда": 8000.0, "автомобиль": 7000.0}


def test_categories_ignore_limits() -> None:
    assert parse_money_categories(FILE) == CATEGORIES


def test_categories_still_work_without_limits() -> None:
    text = "- Еда\n- Аренда\n"

    assert parse_money_categories(text) == ["Еда", "Аренда"]
    assert parse_money_budgets(text) == {}


def test_set_money_limit_sets_and_clears() -> None:
    old, new = set_money_limit(FILE, "Еда", 9000)
    assert old == "- Еда — 8 000"
    assert new == "- Еда — 9 000"

    raw = FILE.replace(old, new)
    old, new = set_money_limit(raw, "Еда", None)
    assert old == "- Еда — 9 000"
    assert new == "- Еда"


def test_set_money_limit_unknown_category() -> None:
    assert set_money_limit(FILE, "Машина", 5000) is None


def test_match_category_variants() -> None:
    assert match_category("еда", CATEGORIES) == "Еда"
    assert match_category("еду", CATEGORIES) == "Еда"
    assert match_category("сигарет", CATEGORIES) == "Сигареты"
    assert match_category("аптеку", CATEGORIES) == "Аптека"
    assert match_category("автомобиля", CATEGORIES) == "Автомобиль"
    assert match_category("машину", CATEGORIES) is None


def test_parse_limit_phrase_sets() -> None:
    command = parse_limit_phrase("лимит еда 8000")

    assert command is not None
    assert command.kind == "set"
    assert command.category == "еда"
    assert command.amount == 8000


def test_parse_limit_phrase_accepts_spaces_and_multipliers() -> None:
    assert parse_limit_phrase("лимит на еду 8 000").amount == 8000
    assert parse_limit_phrase("лимит автомобиль 8к").amount == 8000
    assert parse_limit_phrase("лимит аптека 1 тыс").amount == 1000
    assert parse_limit_phrase("лимит связь 2,5к").amount == 2500


def test_parse_limit_phrase_clear() -> None:
    command = parse_limit_phrase("лимит еда 0")

    assert command is not None
    assert command.kind == "clear"
    assert command.category == "еда"

    cleared = parse_limit_phrase("лимит убери с прочего")
    assert cleared is not None
    assert cleared.kind == "clear"
    assert cleared.category == "прочего"


def test_parse_limit_phrase_list_and_missing() -> None:
    listed = parse_limit_phrase("лимит")
    assert listed is not None and listed.kind == "list"

    missing = parse_limit_phrase("лимит еда")
    assert missing is not None and missing.kind == "missing"


def test_parse_limit_phrase_ignores_regular_text() -> None:
    assert parse_limit_phrase("потратил 100 на еду") is None
    assert parse_limit_phrase("купил лимит 5000") is None


def test_category_spent_only_this_month_and_category() -> None:
    rows = parse_rows(
        "date,kind,amount,category,note\n"
        "2026-11-01,expense,1000,Еда,\n"
        "2026-11-02,expense,500,Еда,\n"
        "2026-11-03,expense,700,Аренда,\n"
        "2026-10-03,expense,900,Еда,\n"
        "2026-11-04,income,5000,Зарплата,\n"
    )

    assert category_spent(rows, "2026-11", "Еда") == 1500
    assert category_spent(rows, "2026-11", "Аренда") == 700
    assert category_spent(rows, "2026-10", "Еда") == 900


def test_budget_status() -> None:
    status = budget_status(2738, 8000)
    assert status == {"pct": 34, "left": 5262, "over": False}

    over = budget_status(8400, 7000)
    assert over["over"] is True
    assert over["left"] == -1400
    assert over["pct"] == 120

    assert budget_status(100, 0) == {}


def _budget_services(raw: str, budgets: dict[str, float] | None = None):
    import zoneinfo

    calls: dict[str, object] = {}

    class FakeGithub:
        async def get_text(self, path: str) -> str:
            return str(calls.get("raw", raw))

        async def replace_line(self, path, old_line, new_line, message) -> bool:
            calls["replace"] = (old_line, new_line)
            calls["raw"] = str(calls.get("raw", raw)).replace(old_line, new_line)
            return True

    class FakeIndex:
        invalidated = False

        async def money_categories(self) -> list[str]:
            return CATEGORIES

        async def money_budgets(self) -> dict[str, float]:
            return budgets or {}

        async def money_categories_path(self) -> str:
            return "30_Money/Категории.md"

        def invalidate(self) -> None:
            self.invalidated = True

    settings = type(
        "Settings",
        (),
        {
            "tz": zoneinfo.ZoneInfo("UTC"),
            "money_widget": "always",
            "telegram_bot_token": "token",
        },
    )()
    services = type(
        "S", (), {"settings": settings, "github": FakeGithub(), "index": FakeIndex()}
    )()
    return services, calls


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


def test_handler_sets_limit_from_phrase() -> None:
    from handlers.notes import _handle_limit_phrase

    services, calls = _budget_services(FILE)
    message = FakeMessage()

    handled = asyncio.run(
        _handle_limit_phrase(message, services, "лимит еда 9000")
    )

    assert handled is True
    assert calls["replace"] == ("- Еда — 8 000", "- Еда — 9 000")
    assert services.index.invalidated is True
    assert "9 000" in message.answers[0]


def test_handler_clears_limit() -> None:
    from handlers.notes import _handle_limit_phrase

    services, calls = _budget_services(FILE)
    message = FakeMessage()

    asyncio.run(_handle_limit_phrase(message, services, "лимит еда 0"))

    assert calls["replace"] == ("- Еда — 8 000", "- Еда")
    assert "снят" in message.answers[0]


def test_handler_unknown_category() -> None:
    from handlers.notes import _handle_limit_phrase

    services, calls = _budget_services(FILE)
    message = FakeMessage()

    asyncio.run(_handle_limit_phrase(message, services, "лимит машина 5000"))

    assert "replace" not in calls
    assert "Не понял категорию" in message.answers[0]


def test_handler_lists_limits() -> None:
    from handlers.notes import _handle_limit_phrase

    services, _ = _budget_services(
        "date,kind,amount,category,note\n"
        "2026-11-01,expense,2738,Еда,\n",
        budgets={"еда": 8000.0},
    )
    message = FakeMessage()

    asyncio.run(_handle_limit_phrase(message, services, "лимит"))

    assert "Лимиты" in message.answers[0]
    assert "2 738 / 8 000" in message.answers[0]


def test_handler_ignores_regular_text() -> None:
    from handlers.notes import _handle_limit_phrase

    services, calls = _budget_services(FILE)
    message = FakeMessage()

    handled = asyncio.run(
        _handle_limit_phrase(message, services, "потратил 100 на еду")
    )

    assert handled is False
    assert not message.answers
