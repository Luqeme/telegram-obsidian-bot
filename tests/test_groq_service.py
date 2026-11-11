"""Тесты GroqService без сети: ретраи, fallback схемы, разбор ответов."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from services.groq_service import (
    GroqError,
    GroqHTTPError,
    GroqService,
    _mime_type,
)

DRAFT = {
    "is_meaningful": True,
    "title": "Тестовая заметка",
    "category": "Мысль",
    "tags": ["тест"],
    "summary": "Кратко.",
    "tasks": [],
    "money_kind": "none",
    "money_amount": 0,
    "money_category": "",
    "project": "",
    "completed_task": "",
}


def make_service(handler) -> tuple[GroqService, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = GroqService(
        client,
        api_key="test-key",
        stt_model="whisper-large-v3",
        llm_model="openai/gpt-oss-120b",
    )
    return service, client


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}
    )


def test_structure_note_parses_draft() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response(json.dumps(DRAFT))

    service, client = make_service(handler)

    async def run():
        try:
            return await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    draft = asyncio.run(run())
    assert draft.title == "Тестовая заметка"


def test_falls_back_to_json_object_on_400() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "json_schema unsupported"})
        return chat_response(json.dumps(DRAFT))

    service, client = make_service(handler)

    async def run():
        try:
            return await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    asyncio.run(run())

    assert len(payloads) == 2
    assert payloads[1]["response_format"] == {"type": "json_object"}


def test_invalid_json_from_model_is_groq_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response("не json")

    service, client = make_service(handler)

    async def run():
        try:
            await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    with pytest.raises(GroqError):
        asyncio.run(run())


def test_retries_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("services.groq_service.asyncio.sleep", fake_sleep)

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)
        return chat_response(json.dumps(DRAFT))

    service, client = make_service(handler)

    async def run():
        try:
            return await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    draft = asyncio.run(run())

    assert draft.title == "Тестовая заметка"
    assert len(calls) == 2
    assert delays == [1]


def test_retry_after_header_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("services.groq_service.asyncio.sleep", fake_sleep)

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0.5"})
        return chat_response(json.dumps(DRAFT))

    service, client = make_service(handler)

    async def run():
        try:
            return await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    asyncio.run(run())

    assert delays == [0.5]


def test_401_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    service, client = make_service(handler)

    async def run():
        try:
            await service.structure_note("текст", "text")
        finally:
            await client.aclose()

    with pytest.raises(GroqHTTPError) as error:
        asyncio.run(run())

    assert error.value.status == 401
    assert len(calls) == 1


def test_network_error_becomes_groq_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    service, client = make_service(handler)

    async def run():
        try:
            await service.answer_question("вопрос", "контекст")
        finally:
            await client.aclose()

    with pytest.raises(GroqError):
        asyncio.run(run())


def test_transcribe_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        return httpx.Response(200, json={"text": "  привет  "})

    service, client = make_service(handler)

    async def run():
        try:
            return await service.transcribe_audio(b"audio", filename="voice.ogg")
        finally:
            await client.aclose()

    assert asyncio.run(run()) == "привет"


def test_transcribe_non_json_is_groq_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    service, client = make_service(handler)

    async def run():
        try:
            await service.transcribe_audio(b"audio")
        finally:
            await client.aclose()

    with pytest.raises(GroqError):
        asyncio.run(run())


def test_answer_question_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response("Ответ по базе.")

    service, client = make_service(handler)

    async def run():
        try:
            return await service.answer_question("вопрос", "контекст")
        finally:
            await client.aclose()

    assert asyncio.run(run()) == "Ответ по базе."


def test_mime_type_by_extension() -> None:
    assert _mime_type("voice.ogg") == "audio/ogg"
    assert _mime_type("track.MP3") == "audio/mpeg"
    assert _mime_type("note.mp4") == "video/mp4"
    assert _mime_type("unknown.bin") == "audio/ogg"
