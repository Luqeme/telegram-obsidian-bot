"""Шим widget_query: разбор Update и маршрутизация в handler."""

from __future__ import annotations

import asyncio
import json

import httpx
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from services.widget_shim import (
    WidgetQuery,
    answer_widget_query,
    install_widget_shim,
)

UPDATE = {
    "update_id": 1,
    "widget_query": {
        "id": "q1",
        "from": {"id": 2, "is_bot": False, "first_name": "A"},
        "data": "done:abc",
        "chat": {"id": 2, "type": "private"},
        "message_id": 10,
        "widget_id": "w1",
    },
}


def test_update_is_parsed_as_widget_query() -> None:
    update = Update.model_validate(UPDATE)

    assert update.event_type == "widget_query"
    assert isinstance(update.event, WidgetQuery)
    assert update.event.id == "q1"
    assert update.event.data == "done:abc"
    assert update.event.from_user.id == 2


def test_widget_query_is_routed_with_services() -> None:
    async def run() -> tuple[list[tuple[str, str, object]], list[str]]:
        dispatcher = Dispatcher()
        seen: list[tuple[str, str, object]] = []

        async def handler(query: WidgetQuery, services: object) -> None:
            seen.append((query.id, query.data, services))

        observer = install_widget_shim(dispatcher)
        observer.register(handler)
        dispatcher.workflow_data["services"] = "services-stub"

        bot = Bot("123:ABC")
        try:
            await dispatcher.feed_update(bot, Update.model_validate(UPDATE))
        finally:
            await bot.session.close()

        return seen, dispatcher.resolve_used_update_types()

    seen, used = asyncio.run(run())

    assert seen == [("q1", "done:abc", "services-stub")]
    assert "widget_query" in used


def test_answer_widget_query_payload() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> bool:
        try:
            return await answer_widget_query(
                "token", "q1", "ok", client=client
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) is True
    assert requests[0].url.path.endswith("/answerWidgetQuery")
    payload = json.loads(requests[0].content)
    assert payload == {"widget_query_id": "q1", "data": "ok"}
