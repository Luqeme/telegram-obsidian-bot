"""Виджет траты: состояние, поиск строки в CSV и переключение категории."""

from __future__ import annotations

from datetime import datetime, timezone

from services.money import (
    MONEY_PATH,
    day_expense,
    dumps_spend_state,
    find_row_line,
    note_hash,
    parse_rows,
    replace_row_category,
    spend_state,
)
from services.widgets import build_spend_widget, compressed_size
from services.widgets import MAX_COMPRESSED

CSV = (
    "date,kind,amount,category,note\n"
    '2026-11-13,expense,540,Еда,"потратил 540 на обед"\n'
    '2026-11-13,expense,1200,Аренда,"квартира"\n'
    "2026-11-13,income,90000,Зарплата,аванс\n"
)

NOTE = "потратил 540 на обед"


def test_note_hash_is_stable_and_short() -> None:
    assert note_hash(NOTE) == note_hash(NOTE)
    assert len(note_hash(NOTE)) == 6
    assert note_hash(NOTE) != note_hash("другое")


def test_find_row_line_matches_amount_and_note() -> None:
    found = find_row_line(CSV, "540", note_hash(NOTE))

    assert found is not None
    line, values = found
    assert values[3] == "Еда"
    assert values[4] == NOTE
    assert line in CSV


def test_find_row_line_returns_none_for_unknown() -> None:
    assert find_row_line(CSV, "540", note_hash("нет такой")) is None
    assert find_row_line(CSV, "999", note_hash(NOTE)) is None


def test_replace_row_category_keeps_other_fields() -> None:
    change = replace_row_category(CSV, "540", note_hash(NOTE), "Автомобиль")

    assert change is not None
    old_line, new_line, values = change
    assert "Еда" in old_line
    assert "Автомобиль" in new_line
    assert values[3] == "Автомобиль"

    updated = CSV.replace(old_line, new_line)
    rows = parse_rows(updated)
    assert rows[0]["category"] == "Автомобиль"
    assert rows[0]["note"] == NOTE
    assert rows[0]["amount"] == "540"
    assert rows[0]["kind"] == "expense"


def test_replace_row_category_quotes_note_with_comma() -> None:
    raw = (
        "date,kind,amount,category,note\n"
        '2026-11-13,expense,300,Прочее,"обед, кофе"\n'
    )
    change = replace_row_category(raw, "300", note_hash("обед, кофе"), "Еда")

    assert change is not None
    _, new_line, _ = change
    assert '"обед, кофе"' in new_line
    assert parse_rows("date,kind,amount,category,note\n" + new_line)[0][
        "category"
    ] == "Еда"


def test_day_expense_sums_only_expenses() -> None:
    rows = parse_rows(CSV)

    assert day_expense(rows, "2026-11-13") == 1740
    assert day_expense(rows, "2026-11-14") == 0


def test_spend_state_fields() -> None:
    state = spend_state(
        amount=540,
        kind="expense",
        category="Еда",
        note=NOTE,
        categories=["Еда", "Аренда", "Прочее"],
        today_total=1740,
    )

    assert state["a"] == 540
    assert state["g"] == 0
    assert state["c"] == "Еда"
    assert state["n"] == NOTE
    assert state["h"] == note_hash(NOTE)
    assert state["k"] == ["Еда", "Аренда", "Прочее"]
    assert state["t"] == 1740
    assert state["s"] == "ok"


def test_spend_state_income_flag() -> None:
    state = spend_state(
        amount=90000,
        kind="income",
        category="Зарплата",
        note="аванс",
        categories=["Зарплата"],
        today_total=0,
    )

    assert state["g"] == 1


def test_spend_state_includes_budget() -> None:
    state = spend_state(
        amount=540,
        kind="expense",
        category="Еда",
        note=NOTE,
        categories=["Еда"],
        today_total=0,
        limit=8000,
        spent=2738,
    )

    assert state["lim"] == 8000
    assert state["sp"] == 2738


def test_spend_state_without_budget_has_zeroes() -> None:
    state = spend_state(
        amount=540,
        kind="expense",
        category="Еда",
        note=NOTE,
        categories=["Еда"],
        today_total=0,
    )

    assert state["lim"] == 0
    assert state["sp"] == 0


def test_spend_state_drops_chips_that_do_not_fit_request() -> None:
    long_name = "Очень длинная категория денег"
    state = spend_state(
        amount=540,
        kind="expense",
        category="Еда",
        note=NOTE,
        categories=["Еда", long_name],
        today_total=0,
    )

    assert "Еда" in state["k"]
    assert long_name not in state["k"]


def test_spend_state_fits_chat_data() -> None:
    state = spend_state(
        amount=12345,
        kind="expense",
        category="Еда",
        note="очень длинная заметка " * 20,
        categories=[f"Категория {index}" for index in range(8)],
        today_total=99999,
    )

    payload = dumps_spend_state(state)
    assert len(payload.encode("utf-8")) <= 1024
    assert len(state["n"]) <= 40


def test_spend_widget_shell() -> None:
    import re

    markup = build_spend_widget()

    assert markup
    assert "TelegramWidget.chatData" in markup
    assert "chatDataChanged" in markup
    assert "'cat:' + s.a" in markup
    assert "'undo:' + s.a" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED

    script = re.search(r"<script>(.*?)</script>", markup, re.S)
    assert script is not None
    assert not re.search(r"^\s*def\s+\w+\s*\(", script.group(1), re.M)


def test_spend_state_note_hash_matches_saved_row() -> None:
    summary_note = "потратил 540 на обед"
    state = spend_state(
        amount=540,
        kind="expense",
        category="Еда",
        note=summary_note,
        categories=[],
        today_total=0,
    )

    found = find_row_line(CSV, str(state["a"]), state["h"])
    assert found is not None


def test_money_path_constant() -> None:
    assert MONEY_PATH == "30_Money/transactions.csv"
    assert datetime.now(timezone.utc).tzinfo is not None
