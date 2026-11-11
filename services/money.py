"""Подсчёт денег по месяцам: чистые функции, без сети и Telegram."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

MONEY_PATH = "30_Money/transactions.csv"

MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


@dataclass(slots=True)
class MonthSummary:
    month: str
    income: float = 0.0
    expense: float = 0.0
    count: int = 0
    expense_categories: list[tuple[str, float]] = field(default_factory=list)
    income_categories: list[tuple[str, float]] = field(default_factory=list)
    top_expenses: list[dict] = field(default_factory=list)

    @property
    def balance(self) -> float:
        return self.income - self.expense


def parse_rows(raw: str) -> list[dict]:
    if not raw.strip():
        return []
    return [row for row in csv.DictReader(io.StringIO(raw)) if row.get("date")]


def rows_for_month(rows: list[dict], month: str) -> list[dict]:
    return [row for row in rows if str(row.get("date", "")).startswith(month)]


def to_amount(value: object) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return 0.0


def format_rub(value: float) -> str:
    """Сумма с пробелами между разрядами: 1234.0 -> '1 234'."""
    return f"{value:,.0f}".replace(",", " ")


def month_label(month: str) -> str:
    """'2026-10' -> 'октябрь 2026'."""
    year, number = (int(part) for part in month.split("-"))
    return f"{MONTHS[number - 1]} {year}"


def previous_month(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    if number == 1:
        return f"{year - 1}-12"
    return f"{year}-{number - 1:02d}"


def summarize(rows: list[dict], month: str) -> MonthSummary:
    month_rows = rows_for_month(rows, month)
    summary = MonthSummary(month=month, count=len(month_rows))

    expenses: dict[str, float] = {}
    incomes: dict[str, float] = {}

    for row in month_rows:
        amount = to_amount(row.get("amount"))
        kind = str(row.get("kind", "")).strip()
        category = str(row.get("category") or "Прочее").strip() or "Прочее"

        if kind == "expense":
            summary.expense += amount
            expenses[category] = expenses.get(category, 0.0) + amount
            summary.top_expenses.append(
                {
                    "amount": amount,
                    "category": category,
                    "note": str(row.get("note") or "").strip(),
                    "date": str(row.get("date") or ""),
                }
            )
        elif kind == "income":
            summary.income += amount
            incomes[category] = incomes.get(category, 0.0) + amount

    summary.expense_categories = sorted(expenses.items(), key=lambda item: -item[1])
    summary.income_categories = sorted(incomes.items(), key=lambda item: -item[1])
    summary.top_expenses.sort(key=lambda item: -item["amount"])
    summary.top_expenses = summary.top_expenses[:5]
    return summary
