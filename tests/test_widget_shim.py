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
    edit_widget_data,
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


def test_edit_widget_data_payload() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> bool:
        try:
            return await edit_widget_data(
                "token", 2, 10, '{"o":1}', client=client
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) is True
    assert requests[0].url.path.endswith("/editMessageWidgetData")
    payload = json.loads(requests[0].content)
    assert payload == {"chat_id": 2, "message_id": 10, "chat_data": '{"o":1}'}


def test_handler_closes_task_and_updates_widget() -> None:
    import zoneinfo

    from handlers import widgets as widget_handlers

    calls: dict[str, object] = {}
    edits: list[tuple] = []

    class FakeTask:
        id = "abc"
        raw = "Купить молоко"
        text = "Купить молоко"

        class note:
            path = "Tasks.md"

    class FakeIndex:
        invalidated = False

        async def find_task(self, task_id: str):
            return FakeTask() if task_id == "abc" else None

        def invalidate(self) -> None:
            self.invalidated = True

    class FakeGithub:
        async def replace_line(self, *args, **kwargs) -> bool:
            calls["replace"] = args
            return True

    settings = type(
        "Settings",
        (),
        {
            "telegram_bot_token": "token",
            "allowed_user_ids": [2],
            "tz": zoneinfo.ZoneInfo("UTC"),
        },
    )()
    services = type(
        "S", (), {"settings": settings, "index": FakeIndex(), "github": FakeGithub()}
    )()

    async def fake_collect(_services) -> dict:
        return {"stub": True}

    def fake_state(_data) -> dict:
        return {"s": 1}

    async def fake_answer(token, query_id, data="", **kwargs) -> bool:
        calls["answer"] = (token, query_id, data)
        return True

    async def fake_edit(token, chat_id, message_id, chat_data, **kwargs) -> bool:
        edits.append((token, chat_id, message_id, chat_data))
        return True

    originals = (
        widget_handlers.collect_today,
        widget_handlers.build_today_state,
        widget_handlers.answer_widget_query,
        widget_handlers.edit_widget_data,
    )
    widget_handlers.collect_today = fake_collect
    widget_handlers.build_today_state = fake_state
    widget_handlers.answer_widget_query = fake_answer
    widget_handlers.edit_widget_data = fake_edit
    try:
        query = WidgetQuery.model_validate(
            {
                "id": "q1",
                "from": {"id": 2, "is_bot": False, "first_name": "A"},
                "data": "done:abc",
                "chat": {"id": 2, "type": "private"},
                "message_id": 10,
            }
        )

        asyncio.run(widget_handlers.on_widget_query(query, services))
    finally:
        (
            widget_handlers.collect_today,
            widget_handlers.build_today_state,
            widget_handlers.answer_widget_query,
            widget_handlers.edit_widget_data,
        ) = originals

    assert calls["answer"] == ("token", "q1", "ok")
    assert edits == [("token", 2, 10, json.dumps({"s": 1}))]
    assert services.index.invalidated is True
    assert calls["replace"][0] == "Tasks.md"


def test_handler_switches_report_period() -> None:
    import zoneinfo

    from handlers import widgets as widget_handlers

    calls: dict[str, object] = {}
    edits: list[tuple] = []

    async def fake_read(_services) -> list[dict]:
        return [{"date": "2026-10-01"}]

    def fake_state(rows, view, now) -> dict:
        calls["view"] = view
        calls["rows"] = rows
        calls["now"] = now
        return {"k": "m", "v": view}

    def fake_dump(state) -> str:
        calls["state"] = state
        return json.dumps(state)

    async def fake_answer(token, query_id, data="", **kwargs) -> bool:
        calls["answer"] = (token, query_id, data)
        return True

    async def fake_edit(token, chat_id, message_id, chat_data, **kwargs) -> bool:
        edits.append((token, chat_id, message_id, chat_data))
        return True

    originals = (
        widget_handlers.read_money,
        widget_handlers.report_state,
        widget_handlers.dumps_report_state,
        widget_handlers.answer_widget_query,
        widget_handlers.edit_widget_data,
    )
    widget_handlers.read_money = fake_read
    widget_handlers.report_state = fake_state
    widget_handlers.dumps_report_state = fake_dump
    widget_handlers.answer_widget_query = fake_answer
    widget_handlers.edit_widget_data = fake_edit
    try:
        settings = type(
            "Settings",
            (),
            {
                "telegram_bot_token": "token",
                "allowed_user_ids": [2],
                "tz": zoneinfo.ZoneInfo("UTC"),
            },
        )()
        services = type("S", (), {"settings": settings})()
        query = WidgetQuery.model_validate(
            {
                "id": "q1",
                "from": {"id": 2, "is_bot": False, "first_name": "A"},
                "data": "report:mon:2026-10",
                "chat": {"id": 2, "type": "private"},
                "message_id": 10,
            }
        )

        asyncio.run(widget_handlers.on_widget_query(query, services))
    finally:
        (
            widget_handlers.read_money,
            widget_handlers.report_state,
            widget_handlers.dumps_report_state,
            widget_handlers.answer_widget_query,
            widget_handlers.edit_widget_data,
        ) = originals

    assert calls["view"] == "mon:2026-10"
    assert calls["answer"] == ("token", "q1", "ok")
    assert edits == [("token", 2, 10, json.dumps({"k": "m", "v": "mon:2026-10"}))]

