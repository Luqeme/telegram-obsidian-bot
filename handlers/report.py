"""Отчёт по деньгам: команда /report и автоматическая отправка 1-го числа."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from services import GitHubError, Services
from services.money import (
    MONEY_PATH,
    MonthSummary,
    month_label,
    parse_rows,
    previous_month,
    summarize,
)

router = Router(name="report")
logger = logging.getLogger(__name__)


@router.message(Command("report"))
async def cmd_report(message: Message, services: Services) -> None:
    month = datetime.now(services.settings.tz).strftime("%Y-%m")
    argument = (message.text or "").partition(" ")[2].strip()
    if argument:
        month = _parse_month(argument)
        if month is None:
            await message.answer(
                "Формат: <code>/report 2026-10</code> — год и месяц через дефис.",
                parse_mode="HTML",
            )
            return

    try:
        rows = await _read_money(services)
    except GitHubError as exc:
        logger.error("report: %s", exc)
        await message.answer(exc.user_message)
        return

    await message.answer(render_report(rows, month), parse_mode="HTML")


async def report_loop(bot: Bot, services: Services) -> None:
    """1-го числа в MONTHLY_REPORT_TIME присылает отчёт за прошлый месяц."""
    while True:
        delay = _seconds_until_month_start(
            services.settings.monthly_report_time, services.settings.tz
        )
        await asyncio.sleep(delay)

        try:
            now = datetime.now(services.settings.tz)
            month = previous_month(now.strftime("%Y-%m"))
            rows = await _read_money(services)
            if summarize(rows, month).count:
                await _broadcast(bot, services, render_report(rows, month))
        except Exception:  # noqa: BLE001 - фоновая задача не должна падать
            logger.exception("Месячный отчёт не отправился")

        await asyncio.sleep(61)


def render_report(rows: list[dict], month: str) -> str:
    summary = summarize(rows, month)
    label = month_label(month)

    if summary.count == 0:
        return f"📊 <b>Отчёт за {label}</b>\n\nЗаписей нет."

    lines = [
        f"📊 <b>Отчёт за {label}</b>",
        "",
        f"Доход: <b>{_money(summary.income)} ₽</b>",
        f"Расход: <b>{_money(summary.expense)} ₽</b>",
        f"Остаток: <b>{_money(summary.balance)} ₽</b>",
        f"Операций: {summary.count}",
    ]

    lines.extend(_category_lines(summary))

    if summary.income_categories:
        lines.extend(["", "<b>Доходы</b>"])
        for category, amount in summary.income_categories[:5]:
            lines.append(f"• {html.escape(category)} — {_money(amount)} ₽")

    if summary.top_expenses:
        lines.extend(["", "<b>Крупные траты</b>"])
        for item in summary.top_expenses:
            note = item["note"]
            suffix = f" · {html.escape(note[:60])}" if note else ""
            lines.append(
                f"• {_money(item['amount'])} ₽ · "
                f"{html.escape(item['category'])}{suffix}"
            )

    previous = summarize(rows, previous_month(month))
    if previous.expense > 0:
        delta = (summary.expense - previous.expense) / previous.expense * 100
        sign = "−" if delta < 0 else "+"
        lines.extend(
            [
                "",
                f"<i>Прошлый месяц ({month_label(previous.month)}): "
                f"{_money(previous.expense)} ₽ · {sign}{abs(delta):.0f}%</i>",
            ]
        )

    return "\n".join(lines)


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _category_lines(summary: MonthSummary) -> list[str]:
    if not summary.expense_categories:
        return []
    lines = ["", "<b>Расходы по категориям</b>"]
    total = summary.expense or 1.0
    for category, amount in summary.expense_categories[:10]:
        share = amount / total * 100
        lines.append(
            f"• {html.escape(category)} — {_money(amount)} ₽ ({share:.0f}%)"
        )
    hidden = len(summary.expense_categories) - 10
    if hidden > 0:
        lines.append(f"…и ещё {hidden}")
    return lines


async def _read_money(services: Services) -> list[dict]:
    raw = await services.github.get_text(MONEY_PATH)
    return parse_rows(raw)


async def _broadcast(bot: Bot, services: Services, text: str) -> None:
    for user_id in services.settings.allowed_user_ids:
        try:
            await bot.send_message(
                user_id, text, parse_mode="HTML", disable_web_page_preview=True
            )
        except TelegramAPIError as exc:
            logger.warning("Отчёт не ушёл %s: %s", user_id, exc)


def _parse_month(value: str) -> str | None:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        return None
    if parsed.year < 2000 or parsed.year > 2100:
        return None
    return parsed.strftime("%Y-%m")


def _seconds_until_month_start(hhmm: str, tz: timezone) -> float:
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now(tz)
    target = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return max(1.0, (target - now).total_seconds())
