"""Тесты подсчёта денег и текста месячного отчёта."""

from __future__ import annotations

from handlers.report import _parse_month, render_report
from services.money import (
    month_label,
    parse_rows,
    previous_month,
    summarize,
)

ROWS = [
    {
        "date": "2026-10-01",
        "kind": "income",
        "amount": "90000",
        "category": "Зарплата",
        "note": "Октябрь",
    },
    {
        "date": "2026-10-02",
        "kind": "expense",
        "amount": "25000",
        "category": "Аренда",
        "note": "Квартира",
    },
    {
        "date": "2026-10-03",
        "kind": "expense",
        "amount": "1200",
        "category": "Еда",
        "note": "Обед",
    },
    {
        "date": "2026-10-04",
        "kind": "expense",
        "amount": "800",
        "category": "Еда",
        "note": "Продукты",
    },
    {
        "date": "2026-09-05",
        "kind": "expense",
        "amount": "10000",
        "category": "Еда",
        "note": "",
    },
]


def test_parse_rows_skips_empty() -> None:
    raw = "date,kind,amount,category,note\n2026-10-01,expense,540,Еда,Обед\n"
    assert parse_rows(raw)[0]["category"] == "Еда"
    assert parse_rows("") == []


def test_summarize_month() -> None:
    summary = summarize(ROWS, "2026-10")

    assert summary.income == 90000
    assert summary.expense == 27000
    assert summary.balance == 63000
    assert summary.count == 4
    assert summary.expense_categories == [("Аренда", 25000), ("Еда", 2000)]
    assert [item["amount"] for item in summary.top_expenses] == [25000, 1200, 800]


def test_month_helpers() -> None:
    assert month_label("2026-10") == "октябрь 2026"
    assert previous_month("2026-10") == "2026-09"
    assert previous_month("2026-01") == "2025-12"
    assert _parse_month("2026-10") == "2026-10"
    assert _parse_month("октябрь") is None


def test_report_contains_totals_and_comparison() -> None:
    text = render_report(ROWS, "2026-10")

    assert "октябрь 2026" in text
    assert "27 000" in text
    assert "Аренда" in text
    assert "Крупные траты" in text
    assert "Прошлый месяц (сентябрь 2026)" in text
    assert "+170%" in text


def test_report_for_empty_month() -> None:
    assert "Записей нет" in render_report(ROWS, "2026-08")
