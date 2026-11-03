"""Служебные команды: /start, /help, /id."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="base")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет!\n\n"
        "Кидай сюда мысль текстом или голосовым — я разберу её на тезисы, "
        "теги и задачи и сохраню заметку в Obsidian.\n\n"
        "Команды:\n"
        "/id — узнать свой Telegram ID\n"
        "/help — как это работает"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📥 <b>Как пользоваться</b>\n\n"
        "Отправь текст или голосовое — получишь готовую заметку в базе знаний.\n\n"
        "Что я делаю:\n"
        "• расшифровываю голос;\n"
        "• выделяю заголовок, суть и задачи;\n"
        "• подбираю теги;\n"
        "• сохраняю .md в репозиторий Obsidian.\n\n"
        "Если что-то сломалось — пришлю текст обратно, ничего не потеряется.",
        parse_mode="HTML",
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя.")
        return
    await message.answer(
        f"🆔 Твой user_id: <code>{user.id}</code>\n"
        f"Внеси его в <code>ALLOWED_TELEGRAM_USERS</code> в .env",
        parse_mode="HTML",
    )
