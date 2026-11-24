"""Строки CSV для кнопок категорий: поиск, замена, отмена."""

from __future__ import annotations

from services.money import (
    budget_line,
    find_row_line,
    locate_row,
    note_hash,
    parse_rows,
    replace_row_category,
)

CSV = (
    "date,kind,amount,category,note\n"
    '2026-11-13,expense,540,Еда,"потратил 540 на обед"\n'
    '2026-11-13,expense,1200,Аренда,"квартира"\n'
)

NOTE = "потратил 540 на обед"


def test_note_hash_is_short_and_stable() -> None:
    assert len(note_hash(NOTE)) == 6
    assert note_hash(NOTE) == note_hash(NOTE)
    assert note_hash(NOTE) != note_hash("обед")


def test_locate_row_finds_last_match() -> None:
    found = locate_row(CSV, "1200", note_hash("квартира"))

    assert found is not None
    index, values = found
    assert values[3] == "Аренда"
    assert CSV.splitlines()[index] in CSV


def test_locate_row_missing() -> None:
    assert locate_row(CSV, "999", note_hash(NOTE)) is None
    assert locate_row(CSV, "540", note_hash("нет")) is None


def test_replace_row_category_keeps_note_and_amount() -> None:
    change = replace_row_category(CSV, "540", note_hash(NOTE), "Автомобиль")

    assert change is not None
    old_line, new_line, values = change
    assert "Еда" in old_line
    assert values[3] == "Автомобиль"

    updated = CSV.replace(old_line, new_line)
    rows = parse_rows(updated)
    assert rows[0]["category"] == "Автомобиль"
    assert rows[0]["note"] == NOTE
    assert rows[0]["amount"] == "540"


def test_find_row_line_returns_exact_line() -> None:
    found = find_row_line(CSV, "540", note_hash(NOTE))

    assert found is not None
    line, values = found
    assert values[4] == NOTE
    assert line.startswith("2026-11-13,expense,540,Еда")


def test_budget_line_without_limit() -> None:
    assert budget_line("Еда", 100, 0) is None


def test_budget_line_normal() -> None:
    line = budget_line("Еда", 2738, 8000)

    assert line == "Еда: 2 738 из 8 000 ₽ · осталось 5 262 ₽ (34%)"


def test_budget_line_warns_at_80() -> None:
    line = budget_line("Еда", 6800, 8000)

    assert line is not None
    assert line.startswith("⚠️")
    assert "(85%)" in line


def test_budget_line_over() -> None:
    line = budget_line("Автомобиль", 8400, 7000)

    assert line is not None
    assert "перерасход 1 400 ₽" in line
    assert "120%" in line
