"""Тесты команды /money: битые суммы не должны ронять сводку."""

from __future__ import annotations

from handlers.base import render_money


def test_money_survives_empty_amount() -> None:
    rows = [
        {"date": "2026-11-01", "kind": "expense", "amount": "", "category": "Еда"},
        {"date": "2026-11-02", "kind": "expense", "amount": "540", "category": "Еда"},
        {"date": "2026-11-03", "kind": "income", "amount": "5000", "category": "Зарплата"},
    ]

    text = render_money(rows, "2026-11")

    assert "540" in text
    assert "5 000" in text
    assert "Еда" in text


def test_money_survives_garbage_amount() -> None:
    rows = [
        {"date": "2026-11-01", "kind": "expense", "amount": "не число", "category": "Еда"},
    ]

    text = render_money(rows, "2026-11")

    assert "Расход: <b>0 ₽</b>" in text


def test_money_empty_month() -> None:
    text = render_money([], "2026-11")
    assert "записей нет" in text
    assert "ноябрь 2026" in text


def test_money_ignores_other_months() -> None:
    rows = [
        {"date": "2026-10-31", "kind": "expense", "amount": "999", "category": "Еда"},
        {"date": "2026-11-01", "kind": "expense", "amount": "100", "category": "Еда"},
    ]

    text = render_money(rows, "2026-11")

    assert "999" not in text
    assert "100" in text


def test_money_shows_top_categories() -> None:
    rows = [
        {"date": "2026-11-01", "kind": "expense", "amount": "300", "category": "Еда"},
        {"date": "2026-11-02", "kind": "expense", "amount": "100", "category": "Аптека"},
        {"date": "2026-11-03", "kind": "expense", "amount": "200", "category": "Еда"},
    ]

    text = render_money(rows, "2026-11")

    assert text.index("Еда") < text.index("Аптека")
