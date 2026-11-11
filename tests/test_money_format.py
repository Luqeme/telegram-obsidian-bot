"""Одна и та же сумма должна выглядеть одинаково в /money и /report."""

from __future__ import annotations

from handlers.base import render_money
from handlers.report import render_report
from services.money import format_rub

ROWS = [
    {
        "date": "2026-11-01",
        "kind": "expense",
        "amount": "1234",
        "category": "Еда",
        "note": "обед",
    },
    {
        "date": "2026-11-02",
        "kind": "income",
        "amount": "5000",
        "category": "Зарплата",
        "note": "",
    },
]


def test_format_rub() -> None:
    assert format_rub(1234) == "1 234"
    assert format_rub(0) == "0"
    assert format_rub(1234567.8) == "1 234 568"


def test_money_and_report_share_formatting() -> None:
    short = render_money(ROWS, "2026-11")
    full = render_report(ROWS, "2026-11")

    assert "1 234" in short
    assert "1 234" in full
    assert "5 000" in short
    assert "5 000" in full
