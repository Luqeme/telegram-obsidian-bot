"""Подсчёт денег по месяцам: чистые функции, без сети и Telegram."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field

MONEY_PATH = "30_Money/transactions.csv"
SPEND_CHIPS = 8
SPEND_STATE_LIMIT = 1024
REQUEST_LIMIT = 64

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


def note_hash(note: str) -> str:
    """Короткий отпечаток заметки: по нему виджет находит свою строку в CSV."""
    return hashlib.sha1(note.encode("utf-8")).hexdigest()[:6]


def csv_row(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue().rstrip("\r\n")


def locate_row(raw: str, amount: object, digest: str) -> tuple[int, list[str]] | None:
    """Последняя строка CSV с такой суммой и отпечатком заметки."""
    target = to_amount(amount)
    lines = raw.splitlines()
    for index in range(len(lines) - 1, 0, -1):
        line = lines[index]
        if not line.strip():
            continue
        try:
            values = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        if len(values) != 5:
            continue
        if to_amount(values[2]) != target:
            continue
        if note_hash(values[4]) != digest:
            continue
        return index, values
    return None


def replace_row_category(
    raw: str, amount: object, digest: str, category: str
) -> tuple[str, str, list[str]] | None:
    """(старая строка, новая строка, поля) или None, если строку не нашли."""
    found = locate_row(raw, amount, digest)
    if found is None:
        return None
    index, values = found
    old_line = raw.splitlines()[index]
    values[3] = category
    return old_line, csv_row(values), values


def find_row_line(raw: str, amount: object, digest: str) -> tuple[str, list[str]] | None:
    found = locate_row(raw, amount, digest)
    if found is None:
        return None
    index, values = found
    return raw.splitlines()[index], values


def day_expense(rows: list[dict], date: str) -> float:
    return sum(
        to_amount(row.get("amount"))
        for row in rows
        if str(row.get("date", "")) == date and row.get("kind") == "expense"
    )


def spend_state(
    *,
    amount: float,
    kind: str,
    category: str,
    note: str,
    categories: list[str],
    today_total: float,
    status: str = "ok",
) -> dict:
    """Состояние виджета траты: сумма, заметка, категории, статус."""
    value: float | int = (
        int(amount) if float(amount).is_integer() else round(float(amount), 2)
    )
    digest = note_hash(note)
    chips = [
        name
        for name in categories
        if len(f"cat:{value}:{digest}:{name}".encode("utf-8")) <= REQUEST_LIMIT
    ][:SPEND_CHIPS]
    if (
        category
        and category not in chips
        and len(f"cat:{value}:{digest}:{category}".encode("utf-8")) <= REQUEST_LIMIT
    ):
        chips.insert(0, category)
    return {
        "a": value,
        "g": 1 if kind == "income" else 0,
        "c": category,
        "n": note[:40],
        "h": digest,
        "k": chips,
        "t": round(today_total),
        "s": status,
    }


def dumps_spend_state(state: dict) -> str:
    state = dict(state)
    state["k"] = list(state.get("k", []))
    payload = json.dumps(state, ensure_ascii=False)
    while state["k"] and len(payload.encode("utf-8")) > SPEND_STATE_LIMIT:
        state["k"].pop()
        payload = json.dumps(state, ensure_ascii=False)
    return payload
