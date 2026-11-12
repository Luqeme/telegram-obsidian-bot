"""Сводка дня и закрытие задач из чата."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services import GitHubError, Services
from services.money import MONEY_PATH, format_rub, parse_rows, to_amount
from services.notes_index import TaskRef
from services.widgets import build_today_widget, send_widget

logger = logging.getLogger(__name__)

router = Router(name="digest")

MAX_BUTTONS = 6
BUTTON_LABEL = 40


@router.message(Command("today"))
async def cmd_today(message: Message, services: Services) -> None:
    try:
        tasks = await services.index.open_tasks()
        notes = await services.index.notes()
    except GitHubError as exc:
        logger.error("today: %s", exc)
        await message.answer(exc.user_message)
        return

    tz = services.settings.tz
    now = datetime.now(tz)
    today = now.date()

    today_notes = [
        note
        for note in notes
        if note.created is not None and note.created.astimezone(tz).date() == today
    ]
    due_today = [task for task in tasks if task.due and _due_date(task) == today]
    overdue = [task for task in tasks if task.due and _due_date(task) < today]

    overdue_ids = {task.id for task in overdue}
    due_ids = {task.id for task in due_today}
    ordered = overdue + due_today + [
        task for task in tasks if task.id not in overdue_ids | due_ids
    ]

    inbox_dir = services.settings.obsidian_inbox_dir.strip("/")
    inbox_prefix = f"{inbox_dir}/" if inbox_dir else ""
    inbox = [note for note in notes if inbox_prefix and note.path.startswith(inbox_prefix)]

    expense = 0.0
    income = 0.0
    try:
        for row in parse_rows(await services.github.get_text(MONEY_PATH)):
            if str(row.get("date", "")) != today.isoformat():
                continue
            amount = to_amount(row.get("amount"))
            if row.get("kind") == "expense":
                expense += amount
            elif row.get("kind") == "income":
                income += amount
    except GitHubError as exc:
        logger.warning("today money: %s", exc)

    widget_tasks = [
        {
            "text": task.text,
            "due": task.due,
            "icon": "⏳" if task.id in overdue_ids else "📅" if task.id in due_ids else "•",
        }
        for task in ordered[:MAX_BUTTONS]
    ]

    lines = [
        f"📅 <b>Сегодня, {now:%d.%m}</b>",
        "",
        f"Заметок: <b>{len(today_notes)}</b>",
        f"Открытых задач: <b>{len(tasks)}</b>",
        f"В инбоксе: <b>{len(inbox)}</b>",
    ]

    if overdue:
        lines.append(f"Просрочено: <b>{len(overdue)}</b>")
    if due_today:
        lines.append(f"На сегодня: <b>{len(due_today)}</b>")
    if expense or income:
        lines.append(
            f"Сегодня: <b>−{html.escape(format_rub(expense))} ₽</b>"
            + (f" · +{html.escape(format_rub(income))} ₽" if income else "")
        )
    if services.index.truncated:
        indexed, total = services.index.truncated
        lines.append(f"⚠️ В индексе <b>{indexed}</b> из {total} заметок")

    if today_notes:
        lines.extend(["", "<b>Новое</b>"])
        for note in today_notes[:5]:
            lines.append(f"• {html.escape(note.title)}")

    if ordered:
        lines.extend(["", "<b>Задачи</b>"])
        for task in ordered[: MAX_BUTTONS]:
            lines.append(_task_line(task))
        if len(ordered) > MAX_BUTTONS:
            lines.append(f"…и ещё {len(ordered) - MAX_BUTTONS}")

    markup = build_today_widget(
        notes_today=len(today_notes),
        inbox=len(inbox),
        open_tasks=len(tasks),
        overdue=len(overdue),
        due_today=len(due_today),
        tasks=widget_tasks,
        expense=expense,
        income=income,
    )
    keyboard = _keyboard(ordered)

    if markup:
        ok, reason = await send_widget(
            services.settings.telegram_bot_token,
            message.chat.id,
            markup,
            f"📅 Сегодня, {now:%d.%m}",
            reply_markup=keyboard.model_dump(exclude_none=True) if keyboard else None,
        )
        if ok:
            return
        logger.warning("today_widget: %s", reason)

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("t:"))
async def on_task_done(callback: CallbackQuery, services: Services) -> None:
    identifier = (callback.data or "")[2:]

    try:
        task = await services.index.find_task(identifier)
    except GitHubError as exc:
        logger.error("find_task: %s", exc)
        await callback.answer("Не удалось прочитать базу", show_alert=True)
        return

    if task is None:
        await callback.answer("Задача уже изменена или удалена", show_alert=True)
        return

    done = datetime.now(services.settings.tz).strftime("%Y-%m-%d")
    old_line = f"- [ ] {task.raw}"
    new_line = f"- [x] {task.raw} ✅ {done}"

    try:
        updated = await services.github.replace_line(
            task.note.path, old_line, new_line, f"Task done: {task.text}"
        )
    except GitHubError as exc:
        logger.error("replace_line: %s", exc)
        await callback.answer(exc.user_message[:180], show_alert=True)
        return

    if not updated:
        await callback.answer("Задача уже изменилась", show_alert=True)
        return

    services.index.invalidate()
    logger.info("task_done path=%s", task.note.path)
    await callback.answer("Готово ✅")
    await _drop_button(callback)


async def send_digest(bot: Bot, services: Services) -> bool:
    text, markup = await build_digest(services)
    if not text:
        return False

    for user_id in services.settings.allowed_user_ids:
        try:
            await bot.send_message(
                user_id, text, parse_mode="HTML", reply_markup=markup
            )
        except TelegramAPIError as exc:
            logger.warning("Дайджест не ушёл пользователю %s: %s", user_id, exc)

    return True


async def build_digest(services: Services) -> tuple[str, InlineKeyboardMarkup | None]:
    """Только задачи с дедлайном на сегодня и просроченные."""
    try:
        tasks = await services.index.open_tasks()
    except GitHubError as exc:
        logger.error("digest: %s", exc)
        return "", None

    tz = services.settings.tz
    today = datetime.now(tz).date()

    overdue = [task for task in tasks if task.due and _due_date(task) < today]
    due_today = [task for task in tasks if task.due and _due_date(task) == today]

    if not overdue and not due_today:
        return "", None

    lines = ["☀️ <b>Доброе утро</b>", ""]
    if overdue:
        lines.append(f"Просрочено: <b>{len(overdue)}</b>")
    if due_today:
        lines.append(f"На сегодня: <b>{len(due_today)}</b>")

    lines.append("")
    for task in (overdue + due_today)[:MAX_BUTTONS]:
        lines.append(_task_line(task))

    return "\n".join(lines), _keyboard(overdue + due_today)


async def digest_loop(bot: Bot, services: Services) -> None:
    """Фоновая отправка дайджеста. Живёт вместе с ботом."""
    while True:
        delay = _seconds_until(services.settings.digest_time, services.settings.tz)
        await asyncio.sleep(delay)

        try:
            await send_digest(bot, services)
        except Exception:  # noqa: BLE001 - фоновая задача не должна падать
            logger.exception("Ошибка при отправке дайджеста")

        # чтобы не отправить дважды в одну и ту же минуту
        await asyncio.sleep(61)


# ── Вспомогательное ──────────────────────────────────────────


def _due_date(task: TaskRef):
    return datetime.strptime(task.due, "%Y-%m-%d").date()


def _task_line(task: TaskRef) -> str:
    line = f"☐ {html.escape(task.text)}"
    if task.due:
        line += f" · до {task.due[8:10]}.{task.due[5:7]}"
    return line


def _keyboard(tasks: list[TaskRef]) -> InlineKeyboardMarkup | None:
    rows = []
    for task in tasks[:MAX_BUTTONS]:
        label = task.text if len(task.text) <= BUTTON_LABEL else task.text[: BUTTON_LABEL - 1] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✅ {label}", callback_data=f"t:{task.id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _drop_button(callback: CallbackQuery) -> None:
    message = callback.message
    markup = getattr(message, "reply_markup", None)
    if markup is None:
        return

    rows = [
        [button for button in row if button.callback_data != callback.data]
        for row in markup.inline_keyboard
    ]
    rows = [row for row in rows if row]
    try:
        await message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        )
    except TelegramAPIError:
        logger.debug("Не удалось обновить клавиатуру")


def _seconds_until(hhmm: str, tz: timezone) -> float:
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())
