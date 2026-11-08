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
from handlers import digest as digest_handlers
from handlers import health as health_handlers
from handlers import notes as notes_handlers
from handlers import report as report_handlers
from middlewares.auth import AllowedUsersMiddleware
from services import GitHubService, GroqService, NotesIndex, Services

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
        github = GitHubService(
            client,
            token=settings.github_token,
            repo=settings.github_repo,
            branch=settings.github_branch,
            inbox_dir=settings.obsidian_inbox_dir,
        )
        services = Services(
            settings=settings,
            groq=GroqService(
                client,
                api_key=settings.groq_api_key,
                stt_model=settings.groq_stt_model,
                llm_model=settings.groq_llm_model,
            ),
            github=github,
            index=NotesIndex(github),
        )

        bot = Bot(token=settings.telegram_bot_token)
        dispatcher = Dispatcher()
        dispatcher.workflow_data["services"] = services
        auth = AllowedUsersMiddleware(settings.allowed_user_ids)
        dispatcher.message.middleware(auth)
        dispatcher.callback_query.middleware(auth)
        dispatcher.include_router(base_handlers.router)
        dispatcher.include_router(digest_handlers.router)
        dispatcher.include_router(report_handlers.router)
        dispatcher.include_router(notes_handlers.router)
        dispatcher.errors.register(on_error)

        background: list[asyncio.Task] = []

        try:
            try:
                await bot.set_my_commands(
                    [
                        BotCommand(command="start", description="Начать"),
                        BotCommand(command="help", description="Как это работает"),
                        BotCommand(command="find", description="Поиск по заметкам"),
                        BotCommand(command="ask", description="Вопрос к базе"),
                        BotCommand(command="today", description="Сводка на сегодня"),
                        BotCommand(command="money", description="Деньги за месяц"),
                        BotCommand(command="report", description="Отчёт за месяц"),
                        BotCommand(command="undo", description="Отменить последнее"),
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

            background.append(
                asyncio.create_task(health_handlers.health_loop(bot, services))
            )
            if settings.digest_time:
                background.append(
                    asyncio.create_task(digest_handlers.digest_loop(bot, services))
                )
            if settings.weekly_ping_time:
                background.append(
                    asyncio.create_task(health_handlers.weekly_loop(bot, services))
                )
            if settings.monthly_report_time:
                background.append(
                    asyncio.create_task(report_handlers.report_loop(bot, services))
                )

            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types()
            )
        finally:
            for task in background:
                task.cancel()
            await bot.session.close()
            logger.info("Бот остановлен")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 0
    raise SystemExit(exit_code)
