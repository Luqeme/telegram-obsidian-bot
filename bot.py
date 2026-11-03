"""Точка входа: загрузка конфига, polling, логирование."""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx
from aiogram import Bot, Dispatcher
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramUnauthorizedError,
)
from aiogram.types import BotCommand, ErrorEvent, Message
from pydantic import ValidationError

from config import get_settings
from handlers import base as base_handlers
from handlers import notes as notes_handlers
from middlewares.auth import AllowedUsersMiddleware
from services import GitHubService, GroqService, Services

logger = logging.getLogger("bot")

HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def setup_logging(level: str) -> None:
    # Логи всегда в UTF-8, иначе на Windows кириллица в файле превращается в кракозябры.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


def format_settings_error(exc: ValidationError) -> str:
    lines = ["❌ Не удалось прочитать .env:"]
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]).upper() or "КОНФИГ"
        lines.append(f"  • {field}: {error['msg']}")
    lines.append("")
    lines.append("Скопируй .env.example в .env и заполни значения.")
    return "\n".join(lines)


async def on_error(event: ErrorEvent) -> bool:
    logger.error("Необработанная ошибка: %r", event.exception, exc_info=event.exception)
    message = event.update.message
    if isinstance(message, Message):
        try:
            await message.answer("❌ Внутренняя ошибка. Попробуй ещё раз.")
        except TelegramAPIError:
            pass
    return True


async def main() -> int:
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(format_settings_error(exc), file=sys.stderr)
        return 1

    problems = settings.placeholder_problems()
    if problems:
        print("❌ В .env остались значения-заглушки:", file=sys.stderr)
        for problem in problems:
            print(f"  • {problem}", file=sys.stderr)
        return 1

    setup_logging(settings.log_level)
    logger.info(
        "Запуск: llm=%s, stt=%s, repo=%s@%s, inbox=%s, tz=%s",
        settings.groq_llm_model,
        settings.groq_stt_model,
        settings.github_repo,
        settings.github_branch,
        settings.obsidian_inbox_dir,
        settings.timezone,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        services = Services(
            settings=settings,
            groq=GroqService(
                client,
                api_key=settings.groq_api_key,
                stt_model=settings.groq_stt_model,
                llm_model=settings.groq_llm_model,
            ),
            github=GitHubService(
                client,
                token=settings.github_token,
                repo=settings.github_repo,
                branch=settings.github_branch,
                inbox_dir=settings.obsidian_inbox_dir,
            ),
        )

        bot = Bot(token=settings.telegram_bot_token)
        dispatcher = Dispatcher()
        dispatcher.workflow_data["services"] = services
        dispatcher.message.middleware(AllowedUsersMiddleware(settings.allowed_user_ids))
        dispatcher.include_router(base_handlers.router)
        dispatcher.include_router(notes_handlers.router)
        dispatcher.errors.register(on_error)

        try:
            try:
                await bot.set_my_commands(
                    [
                        BotCommand(command="start", description="Начать"),
                        BotCommand(command="help", description="Как это работает"),
                        BotCommand(command="id", description="Мой Telegram ID"),
                    ]
                )
            except TelegramUnauthorizedError:
                print(
                    "❌ Telegram отклонил токен: он недействителен или отозван.\n"
                    "   @BotFather → /mybots → твой бот → API Token → Revoke,\n"
                    "   новый токен впиши в .env → TELEGRAM_BOT_TOKEN",
                    file=sys.stderr,
                )
                return 1

            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types()
            )
        finally:
            await bot.session.close()
            logger.info("Бот остановлен")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 0
    raise SystemExit(exit_code)
