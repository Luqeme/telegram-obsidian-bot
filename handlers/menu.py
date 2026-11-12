"""Обработка кнопок главного меню."""

from __future__ import annotations

import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ForceReply, Message

from handlers.base import PENDING, cmd_help
from handlers.digest import _keyboard, cmd_today
from handlers.notes import _undo_action
from handlers.report import cmd_report
from handlers.menu_ui import main_menu
from services import GitHubError, Services

logger = logging.getLogger(__name__)
router = Router(name="menu")

HOME_DIR = "30_Дом"


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(callback: CallbackQuery, services: Services) -> None:
    action = (callback.data or "").partition(":")[2]
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return

    await callback.answer()

    if action in {"find", "ask"}:
        await _ask_for_query(callback, message, action)
        return

    if action == "today":
        await cmd_today(message, services)
    elif action == "report":
        await cmd_report(message, services)
    elif action == "money":
        await cmd_report(message, services)
    elif action == "undo":
        await _undo_action(callback.from_user.id, message, services)
    elif action == "help":
        await cmd_help(message)
    elif action == "home":
        await _show_home(message, services)
    elif action == "inbox":
        await _show_inbox(message, services)
    elif action == "projects":
        await _show_projects(message, services)
    else:
        await message.answer("Неизвестный пункт меню.")


async def _ask_for_query(callback: CallbackQuery, message: Message, kind: str) -> None:
    prompt = (
        "🔎 Что искать? Напиши ответом на это сообщение."
        if kind == "find"
        else "💬 Что спросить у базы? Напиши ответом на это сообщение."
    )
    sent = await message.answer(prompt, reply_markup=ForceReply(selective=True))
    PENDING[callback.from_user.id] = (kind, sent.message_id)


async def _show_home(message: Message, services: Services) -> None:
    try:
        tasks = await services.index.open_tasks()
    except GitHubError as exc:
        logger.error("menu home: %s", exc)
        await message.answer(exc.user_message)
        return

    home = [task for task in tasks if task.note.folder == HOME_DIR]
    if not home:
        await message.answer("🏠 Бытовых дел нет — всё сделано.")
        return

    lines = ["🏠 <b>Бытовые дела</b>", "", "Нажми на задачу, чтобы закрыть:"]
    markup = _keyboard(home)
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=markup)


async def _show_inbox(message: Message, services: Services) -> None:
    try:
        notes = await services.index.notes()
    except GitHubError as exc:
        logger.error("menu inbox: %s", exc)
        await message.answer(exc.user_message)
        return

    inbox_dir = services.settings.obsidian_inbox_dir.strip("/")
    prefix = f"{inbox_dir}/" if inbox_dir else ""
    inbox = [note for note in notes if prefix and note.path.startswith(prefix)]

    if not inbox:
        await message.answer("📥 Инбокс пуст.")
        return

    now = datetime.now(services.settings.tz)
    lines = [f"📥 <b>В инбоксе: {len(inbox)}</b>", ""]
    for note in inbox[:12]:
        days = ""
        if note.created is not None:
            delta = (now - note.created.astimezone(services.settings.tz)).days
            days = f" · {delta} дн."
        lines.append(f"• {html.escape(note.title)}{days}")
    if len(inbox) > 12:
        lines.append(f"…и ещё {len(inbox) - 12}")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def _show_projects(message: Message, services: Services) -> None:
    try:
        hubs = await services.index.projects()
        notes = await services.index.notes()
        tasks = await services.index.open_tasks()
    except GitHubError as exc:
        logger.error("menu projects: %s", exc)
        await message.answer(exc.user_message)
        return

    if not hubs:
        await message.answer("🚀 Проектов пока нет.")
        return

    lines = ["🚀 <b>Проекты</b>", ""]
    for hub in hubs:
        names = {hub.title.casefold(), *(alias.casefold() for alias in hub.aliases)}
        related = [note for note in notes if note.up.casefold() in names]
        open_tasks = [
            task for task in tasks if task.note.up.casefold() in names
        ]
        lines.append(
            f"• <b>{html.escape(hub.title)}</b> — заметок {len(related)}, "
            f"задач {len(open_tasks)}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")
