"""Сбор данных для дашборда: только чтение, переиспользует services/."""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import date, datetime

from config import Settings
from services import GitHubError, GitHubService, NotesIndex
from services.money import (
    MONEY_PATH,
    category_spent,
    parse_rows,
    summarize,
    to_amount,
)
from services.notes_index import TaskRef

logger = logging.getLogger("dashboard")

CACHE_TTL = 30.0
TASK_LIMIT = 40

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAYS_FULL = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
MONTHS_FULL = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
MONTHS_NOM = (
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


def parse_due(task: TaskRef) -> date | None:
    if not task.due:
        return None
    try:
        return date.fromisoformat(task.due)
    except ValueError:
        return None


def task_view(task: TaskRef, today: date) -> dict:
    due = parse_due(task)
    label = ""
    state = ""
    if due is not None:
        if due < today:
            label, state = "просрочено", "overdue"
        elif due == today:
            label, state = "сегодня", "today"
        else:
            days = (due - today).days
            if days <= 7:
                label = WEEKDAYS[due.weekday()]
            else:
                label = f"{due.day:02d}.{due.month:02d}"
    return {
        "text": task.text,
        "due": due.isoformat() if due else "",
        "label": label,
        "state": state,
    }


def order_tasks(tasks: list[TaskRef], today: date) -> list[TaskRef]:
    overdue: list[TaskRef] = []
    due_today: list[TaskRef] = []
    rest: list[TaskRef] = []
    for task in tasks:
        due = parse_due(task)
        if due is not None and due < today:
            overdue.append(task)
        elif due is not None and due == today:
            due_today.append(task)
        else:
            rest.append(task)
    return overdue + due_today + rest


class Dashboard:
    """Кэширует готовый ответ, чтобы не дёргать GitHub на каждое открытие."""

    def __init__(
        self,
        settings: Settings,
        github: GitHubService,
        index: NotesIndex,
        ttl: float = CACHE_TTL,
    ) -> None:
        self.settings = settings
        self._github = github
        self._index = index
        self._ttl = ttl
        self._payload: dict | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def payload(self) -> dict:
        loop = asyncio.get_running_loop()
        if self._payload is not None and loop.time() - self._loaded_at < self._ttl:
            return self._payload

        async with self._lock:
            if self._payload is not None and loop.time() - self._loaded_at < self._ttl:
                return self._payload
            data = await self._build()
            self._payload = data
            self._loaded_at = loop.time()
            return data

    def invalidate(self) -> None:
        self._payload = None
        self._loaded_at = 0.0

    async def _build(self) -> dict:
        tz = self.settings.tz
        now = datetime.now(tz)
        today = now.date()
        month = now.strftime("%Y-%m")

        notes = await self._index.notes()
        tasks = await self._index.open_tasks()

        today_notes = [
            note
            for note in notes
            if note.created is not None and note.created.astimezone(tz).date() == today
        ]

        inbox_dir = self.settings.obsidian_inbox_dir.strip("/")
        inbox_prefix = f"{inbox_dir}/" if inbox_dir else ""
        inbox = [note for note in notes if inbox_prefix and note.path.startswith(inbox_prefix)]

        ordered = order_tasks(tasks, today)
        overdue_count = sum(1 for task in ordered if task_view(task, today)["state"] == "overdue")

        money = await self._money(month, now, today)

        return {
            "updated": int(time.time()),
            "date_label": f"{WEEKDAYS_FULL[today.weekday()]}, {today.day} {MONTHS_FULL[today.month - 1]}",
            "today_day": today.day,
            "stats": {
                "notes": len(today_notes),
                "tasks": len(tasks),
                "overdue": overdue_count,
                "inbox": len(inbox),
            },
            "money": money,
            "tasks": [task_view(task, today) for task in ordered[:TASK_LIMIT]],
        }

    async def _money(self, month: str, now: datetime, today: date) -> dict:
        try:
            raw = await self._github.get_text(MONEY_PATH)
        except GitHubError as exc:
            logger.warning("Не прочитал %s: %s", MONEY_PATH, exc)
            raw = ""

        rows = parse_rows(raw)
        summary = summarize(rows, month)
        days = calendar.monthrange(now.year, now.month)[1]
        daily = [0.0] * days

        for row in rows:
            stamp = str(row.get("date", ""))
            if not stamp.startswith(month) or str(row.get("kind", "")) != "expense":
                continue
            try:
                day = int(stamp[8:10])
            except ValueError:
                continue
            if 1 <= day <= days:
                daily[day - 1] += to_amount(row.get("amount"))

        limits = await self._index.money_budgets()
        budgets = []
        for name, limit in limits.items():
            if limit <= 0:
                continue
            spent = category_spent(rows, month, name)
            budgets.append(
                {
                    "name": name,
                    "limit": round(limit),
                    "spent": round(spent),
                    "pct": round(spent / limit * 100),
                    "left": round(limit - spent),
                    "over": spent > limit,
                }
            )
        budgets.sort(key=lambda item: (-item["pct"], item["name"]))

        return {
            "month": month,
            "month_label": MONTHS_NOM[now.month - 1],
            "income": round(summary.income),
            "expense": round(summary.expense),
            "balance": round(summary.balance),
            "daily": [round(value) for value in daily],
            "budgets": budgets,
            "today_expense": round(daily[today.day - 1]) if today.day <= days else 0,
        }
