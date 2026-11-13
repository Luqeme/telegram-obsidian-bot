"""Подсчёт денег по месяцам: чистые функции, без сети и Telegram."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
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
    limit: float = 0.0,
    spent: float = 0.0,
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
        "lim": round(limit) if limit else 0,
        "sp": round(spent) if limit else 0,
    }


def dumps_spend_state(state: dict) -> str:
    state = dict(state)
    state["k"] = list(state.get("k", []))
    payload = json.dumps(state, ensure_ascii=False)
    while state["k"] and len(payload.encode("utf-8")) > SPEND_STATE_LIMIT:
        state["k"].pop()
        payload = json.dumps(state, ensure_ascii=False)
    return payload


LIMIT_PREFIX_RE = re.compile(r"^\s*(?:лимит|бюджет)\b(.*)$", re.IGNORECASE)
LIMIT_AMOUNT_RE = re.compile(
    r"(?<![\d.,])(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(к|тыс\.?|тысяч[а-яё]*)?",
    re.IGNORECASE,
)
LIMIT_CLEAR_RE = re.compile(
    r"\b(убер\w*|удал\w*|сним\w*|убра\w*|без)\b", re.IGNORECASE
)
LIMIT_STOPWORDS = frozenset(
    {
        "на",
        "для",
        "по",
        "про",
        "в",
        "во",
        "с",
        "со",
        "и",
        "месяц",
        "месяца",
        "руб",
        "рубль",
        "рублей",
        "р",
        "поставь",
        "поставить",
        "установи",
        "установить",
        "задай",
        "задать",
        "лимит",
        "бюджет",
        "убери",
        "убрать",
        "удали",
        "удалить",
        "сними",
        "снять",
        "без",
    }
)
WORD_ENDINGS = (
    "его",
    "ого",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ями",
    "ами",
    "ей",
    "ой",
    "ый",
    "ий",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ам",
    "ям",
    "ах",
    "ях",
    "ом",
    "ем",
    "ов",
    "ев",
    "ь",
    "а",
    "я",
    "у",
    "ю",
    "ы",
    "и",
    "е",
    "о",
)


@dataclass(slots=True)
class LimitCommand:
    kind: str  # set | clear | list | missing
    category: str = ""
    amount: float = 0.0


def _word_stem(word: str) -> str:
    word = word.casefold()
    for ending in WORD_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 2:
            return word[: -len(ending)]
    return word


def match_category(candidate: str, categories: list[str]) -> str | None:
    """'еду' -> 'Еда', 'сигарет' -> 'Сигареты'."""
    candidate = candidate.strip()
    if not candidate or not categories:
        return None
    lowered = candidate.casefold()
    for category in categories:
        if category.casefold() == lowered:
            return category

    stem = _word_stem(candidate.split()[-1])
    hits = [
        category
        for category in categories
        if _word_stem(category.split()[-1]) == stem
    ]
    if len(hits) == 1:
        return hits[0]
    if not hits and len(stem) >= 3:
        hits = [
            category
            for category in categories
            if _word_stem(category.split()[-1]).startswith(stem)
        ]
    return hits[0] if len(hits) == 1 else None


def _parse_limit_amount(match: re.Match[str]) -> float:
    raw = match.group(1).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    multiplier = (match.group(2) or "").casefold()
    if multiplier.startswith(("к", "тыс")):
        value *= 1000
    return value


def parse_limit_phrase(text: str) -> LimitCommand | None:
    """Разбирает «лимит еда 8000». None — это не про лимиты."""
    match = LIMIT_PREFIX_RE.match(text or "")
    if match is None:
        return None

    rest = match.group(1).strip()
    if not rest:
        return LimitCommand("list")

    clearing = bool(LIMIT_CLEAR_RE.search(rest))
    amount_match = LIMIT_AMOUNT_RE.search(rest)
    amount = _parse_limit_amount(amount_match) if amount_match else 0.0

    candidate = rest
    if amount_match is not None:
        candidate = candidate.replace(amount_match.group(0), " ")
    candidate = re.sub(r"[^\w\s-]", " ", candidate, flags=re.UNICODE)
    words = [
        word
        for word in candidate.split()
        if word.casefold() not in LIMIT_STOPWORDS
    ]
    category = " ".join(words)

    if amount_match is not None:
        if clearing or amount <= 0:
            return LimitCommand("clear", category)
        return LimitCommand("set", category, amount)
    if clearing:
        return LimitCommand("clear", category)
    return LimitCommand("missing", category)


def category_spent(rows: list[dict], month: str, category: str) -> float:
    key = category.casefold()
    return sum(
        to_amount(row.get("amount"))
        for row in rows
        if str(row.get("date", "")).startswith(month)
        and row.get("kind") == "expense"
        and str(row.get("category", "")).casefold() == key
    )


def budget_status(spent: float, limit: float) -> dict:
    """Проценты, остаток и флаг перерасхода для лимита категории."""
    if not limit:
        return {}
    left = limit - spent
    return {
        "pct": round(spent / limit * 100),
        "left": round(left),
        "over": spent > limit,
    }
