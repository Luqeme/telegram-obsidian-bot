"""Проверка доступов и еженедельный пинг инбокса."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from services import Services

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 24 * 3600
SUNDAY = 6


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
    """Воскресный пинг: сколько лежит в инбоксе."""
    while True:
        delay = _seconds_until_weekday(
            services.settings.weekly_ping_time, SUNDAY, services.settings.tz
        )
        await asyncio.sleep(delay)

        try:
            text = await build_weekly(services)
            if text:
                await _broadcast(bot, services, text)
        except Exception:  # noqa: BLE001
            logger.exception("Недельный пинг не отправился")

        await asyncio.sleep(61)


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
