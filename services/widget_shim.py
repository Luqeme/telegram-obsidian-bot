"""Мини-шим для Bot API 10.4: widget_query в aiogram 3.31.

aiogram пока не знает widget_query. Патчим только определение типа события
у Update и регистрируем отдельный observer. Когда aiogram получит официальную
поддержку, этот модуль можно удалить.
"""

from __future__ import annotations

import functools

import httpx
from aiogram import Dispatcher
from aiogram.dispatcher.event.telegram import TelegramEventObserver
from aiogram.types import Chat, Update, User
from pydantic import BaseModel, ConfigDict, Field

ANSWER_URL = "https://api.telegram.org/bot{token}/answerWidgetQuery"
WIDGET_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class WidgetQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    from_user: User = Field(alias="from")
    data: str = ""
    chat: Chat | None = None
    message_id: int | None = None
    inline_message_id: str | None = None
    chat_instance: str = ""
    chat_type: str | None = None
    widget_id: str = ""


def _has_widget(update: Update) -> bool:
    return bool(update.model_extra and "widget_query" in update.model_extra)


if not getattr(Update, "_widget_query_shim", False):
    _original_event_type = Update.event_type.fget
    _original_event = Update.event.fget

    @functools.lru_cache()
    def _event_type(self: Update) -> str:
        if _has_widget(self):
            return "widget_query"
        return _original_event_type(self)

    def _event(self: Update) -> object:
        if _has_widget(self):
            return WidgetQuery.model_validate(self.model_extra["widget_query"])
        return _original_event(self)

    Update.event_type = property(_event_type)
    Update.event = property(_event)
    Update._widget_query_shim = True  # type: ignore[attr-defined]


def install_widget_shim(dispatcher: Dispatcher) -> TelegramEventObserver:
    observer = TelegramEventObserver(router=dispatcher, event_name="widget_query")
    dispatcher.observers["widget_query"] = observer
    return observer


async def answer_widget_query(
    token: str,
    query_id: str,
    data: str = "",
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    payload = {"widget_query_id": query_id}
    if data:
        payload["data"] = data

    own = client is None
    client = client or httpx.AsyncClient(timeout=WIDGET_TIMEOUT)
    try:
        response = await client.post(
            ANSWER_URL.format(token=token), json=payload, timeout=WIDGET_TIMEOUT
        )
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("ok"))
        except ValueError:
            return False
    except httpx.HTTPError:
        return False
    finally:
        if own:
            await client.aclose()
