"""Проверка белого списка Telegram user_id."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

logger = logging.getLogger(__name__)


class AllowedUsersMiddleware(BaseMiddleware):
    """Пускает дальше только доверенные user_id.

    Единственная точка авторизации: проверка навешивается на все message-события,
    а не размазывается по хендлерам.
    """

    def __init__(self, allowed: frozenset[int]) -> None:
        self._allowed = allowed
        self._warned: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is not None and user.id in self._allowed:
            return await handler(event, data)

        if user is not None:
            logger.warning("Доступ запрещён: user_id=%s", user.id)
            if user.id not in self._warned:
                self._warned.add(user.id)
                try:
                    await event.answer("⛔ Доступ ограничен.")
                except TelegramAPIError:
                    logger.debug("Не удалось отправить отказ user_id=%s", user.id)

        return None
