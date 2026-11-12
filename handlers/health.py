"""Проверка доступов и еженедельный пинг инбокса."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from services import GitHubError, Services
from services.money import MONEY_PATH, parse_rows, to_amount
from services.widgets import (
    WeeklyReview,
    build_weekly_widget,
    send_widget,
    weekly_caption,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 24 * 3600
SUNDAY = 6
DONE_TASK_RE = re.compile(
    r"^- \[[xX]\] .+?✅\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE
)


async def health_loop(bot: Bot, services: Services) -> None:
    """Раз в сутки проверяет, что GitHub и Groq отвечают."""
    await asyncio.sleep(10)

    while True:
        try:
            await check_and_report(bot, services)
        except Exception:  # noqa: BLE001 - фоновая задача не должна падать
            logger.exception("Проверка доступов не удалась")

        await asyncio.sleep(CHECK_INTERVAL)


async def check_and_report(bot: Bot, services: Services) -> list[str]:
    problems: list[str] = []

    github_ok, github_reason = await services.github.check_access()
    if not github_ok:
        problems.append(f"GitHub: {github_reason}")

    groq_ok, groq_reason = await services.groq.check_access()
    if not groq_ok:
        problems.append(f"Groq: {groq_reason}")

    if not problems:
        return []

    logger.error("Проблемы с доступом: %s", problems)
    text = (
        "⚠️ <b>Проблема с доступом</b>\n\n"
        + "\n".join(f"• {html.escape(problem)}" for problem in problems)
        + "\n\nПроверь токены в .env на сервере."
    )
    await _broadcast(bot, services, text)
    return problems


async def weekly_loop(bot: Bot, services: Services) -> None:
    """Воскресный обзор недели виджетом."""
    while True:
        delay = _seconds_until_weekday(
            services.settings.weekly_ping_time, SUNDAY, services.settings.tz
        )
        await asyncio.sleep(delay)

        try:
            await send_weekly(bot, services)
        except Exception:  # noqa: BLE001
            logger.exception("Недельный обзор не отправился")

        await asyncio.sleep(61)


async def collect_weekly(services: Services) -> WeeklyReview:
    notes = await services.index.notes()
    tasks = await services.index.open_tasks()
    projects = await services.index.projects()

    tz = services.settings.tz
    now = datetime.now(tz)
    end = now.date()
    start = end - timedelta(days=6)

    notes_week = [
        note
        for note in notes
        if note.created is not None
        and start <= note.created.astimezone(tz).date() <= end
    ]

    tasks_done = 0
    for note in notes:
        for raw_date in DONE_TASK_RE.findall(note.text):
            try:
                done = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if start <= done <= end:
                tasks_done += 1

    overdue = sum(
        1
        for task in tasks
        if task.due and _safe_date(task.due) < end  # type: ignore[operator]
    )

    inbox_dir = services.settings.obsidian_inbox_dir.strip("/")
    prefix = f"{inbox_dir}/" if inbox_dir else ""
    inbox = [note for note in notes if prefix and note.path.startswith(prefix)]
    stale = [
        note
        for note in inbox
        if note.created is not None
        and note.created.astimezone(tz).date() < start
    ]

    expense, income = 0.0, 0.0
    prev_expense, prev_income = 0.0, 0.0
    try:
        rows = parse_rows(await services.github.get_text(MONEY_PATH))
        expense, income = _money_range(rows, start, end)
        prev_expense, prev_income = _money_range(
            rows, start - timedelta(days=7), start - timedelta(days=1)
        )
    except GitHubError as exc:
        logger.warning("weekly money: %s", exc)

    idle: list[str] = []
    for hub in projects:
        names = {hub.title.casefold(), *(alias.casefold() for alias in hub.aliases)}
        moved = any(note.up.casefold() in names for note in notes_week)
        if not moved:
            idle.append(hub.title)

    return WeeklyReview(
        period=f"{start:%d.%m}–{end:%d.%m}",
        notes_week=len(notes_week),
        tasks_done=tasks_done,
        tasks_open=len(tasks),
        overdue=overdue,
        inbox=len(inbox),
        inbox_stale=len(stale),
        expense=expense,
        income=income,
        prev_expense=prev_expense,
        prev_income=prev_income,
        projects_idle=idle,
    )


async def send_weekly(bot: Bot, services: Services) -> bool:
    try:
        review = await collect_weekly(services)
    except Exception as exc:  # noqa: BLE001
        logger.error("weekly: %s", exc)
        return False

    if not review.has_data:
        return False

    markup = build_weekly_widget(review)
    text = render_weekly(review)

    for user_id in services.settings.allowed_user_ids:
        sent = False
        if markup:
            ok, reason = await send_widget(
                services.settings.telegram_bot_token,
                user_id,
                markup,
                weekly_caption(review),
            )
            if ok:
                sent = True
            else:
                logger.warning("weekly_widget: %s", reason)

        if not sent:
            try:
                await bot.send_message(user_id, text, parse_mode="HTML")
            except TelegramAPIError as exc:
                logger.warning("Недельный обзор не ушёл %s: %s", user_id, exc)

    return True


def render_weekly(review: WeeklyReview) -> str:
    lines = [
        f"🗓 <b>Итоги недели · {review.period}</b>",
        "",
        f"Заметок: <b>{review.notes_week}</b>",
        f"Задач закрыто: <b>{review.tasks_done}</b>",
        f"Открыто: <b>{review.tasks_open}</b>",
    ]
    if review.overdue:
        lines.append(f"Просрочено: <b>{review.overdue}</b>")
    lines.append(f"В инбоксе: <b>{review.inbox}</b>")
    if review.inbox_stale:
        lines.append(f"Из них старше недели: <b>{review.inbox_stale}</b>")

    lines.extend(["", f"<b>Деньги</b>"])
    lines.append(
        f"Расход: <b>{html.escape(_money(review.expense))} ₽</b> · "
        f"Доход: <b>{html.escape(_money(review.income))} ₽</b>"
    )
    if review.prev_expense > 0:
        delta = (review.expense - review.prev_expense) / review.prev_expense * 100
        sign = "−" if delta < 0 else "+"
        lines.append(f"<i>Расход к прошлой неделе: {sign}{abs(delta):.0f}%</i>")

    if review.projects_idle:
        lines.extend(
            [
                "",
                "<b>Без движения</b>",
                "• " + ", ".join(html.escape(name) for name in review.projects_idle),
            ]
        )

    return "\n".join(lines)


def _money_range(rows: list[dict], start: date, end: date) -> tuple[float, float]:
    expense = 0.0
    income = 0.0
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date", ""))[:10])
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        amount = to_amount(row.get("amount"))
        if row.get("kind") == "expense":
            expense += amount
        elif row.get("kind") == "income":
            income += amount
    return expense, income


def _safe_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.max


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


async def build_weekly(services: Services) -> str:
    try:
        notes = await services.index.notes()
    except Exception as exc:  # noqa: BLE001
        logger.error("weekly: %s", exc)
        return ""

    now = datetime.now(services.settings.tz)
    inbox_dir = services.settings.obsidian_inbox_dir.strip("/")
    prefix = f"{inbox_dir}/" if inbox_dir else ""
    inbox = [note for note in notes if prefix and note.path.startswith(prefix)]
    if not inbox:
        return ""

    week_ago = now - timedelta(days=7)
    stale = [
        note
        for note in inbox
        if note.created is not None and note.created.astimezone(services.settings.tz) < week_ago
    ]

    lines = [
        "🗂 <b>Инбокс за неделю</b>",
        "",
        f"Ждёт разбора: <b>{len(inbox)}</b>",
    ]
    if stale:
        lines.append(f"Из них старше недели: <b>{len(stale)}</b>")

    return "\n".join(lines)


async def _broadcast(bot: Bot, services: Services, text: str) -> None:
    for user_id in services.settings.allowed_user_ids:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except TelegramAPIError as exc:
            logger.warning("Сообщение не ушло %s: %s", user_id, exc)


def _seconds_until_weekday(hhmm: str, weekday: int, tz: timezone) -> float:
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    days = (weekday - now.weekday()) % 7
    if days == 0 and target <= now:
        days = 7

    target += timedelta(days=days)
    return max(1.0, (target - now).total_seconds())
