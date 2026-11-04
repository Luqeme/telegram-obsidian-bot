"""Groq Cloud: распознавание речи и структурирование заметки."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Sequence

import httpx
from pydantic import ValidationError

from prompts import NOTE_DRAFT_SCHEMA, SYSTEM_PROMPT

from .note_builder import NoteDraft, NoteSource

logger = logging.getLogger(__name__)

API_URL = "https://api.groq.com/openai/v1"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

ANSWER_PROMPT = """Ты — помощник по личной базе заметок пользователя.
Отвечай ТОЛЬКО по предоставленным заметкам. Если в них нет ответа — честно скажи,
что в базе этого не нашлось, и не додумывай.

Правила:
- 2–5 предложений, по-русски, без вступлений вроде «Конечно» или «Вот что я нашёл».
- Не выдумывай факты, даты, имена и суммы.
- Если заметки противоречат друг другу — отметь это.
- Если уместно, назови заголовок заметки, из которой взят ответ.
"""

STT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
LLM_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class GroqError(RuntimeError):
    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


class GroqHTTPError(GroqError):
    def __init__(self, status: int, message: str, user_message: str) -> None:
        super().__init__(message, user_message)
        self.status = status


class GroqService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        stt_model: str,
        llm_model: str,
    ) -> None:
        self._client = client
        self._stt_model = stt_model
        self._llm_model = llm_model
        self._headers = {"Authorization": f"Bearer {api_key}"}

    # ── Распознавание речи ───────────────────────────────────

    async def transcribe_audio(
        self, audio: bytes, filename: str = "voice.ogg"
    ) -> str:
        """Отправляет аудио в Whisper. Возвращает расшифровку (может быть пустой)."""
        files = {"file": (filename, audio, "audio/ogg")}
        data = {
            "model": self._stt_model,
            "language": "ru",
            "response_format": "json",
            "temperature": "0",
        }
        response = await self._post_with_retry(
            f"{API_URL}/audio/transcriptions",
            what="Whisper",
            user_message="❌ Не удалось расшифровать аудио. Попробуй ещё раз или отправь текстом.",
            timeout=STT_TIMEOUT,
            files=files,
            data=data,
        )

        try:
            text = response.json().get("text", "")
        except ValueError as exc:
            raise GroqError(
                f"Whisper вернул не JSON: {response.text[:200]}",
                "❌ Не удалось расшифровать аудио.",
            ) from exc

        return text.strip()

    # ── Структурирование ─────────────────────────────────────

    async def structure_note(
        self,
        text: str,
        source: NoteSource,
        *,
        today: date | None = None,
        known_tags: Sequence[str] = (),
    ) -> NoteDraft:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        context: list[str] = []
        if today is not None:
            context.append(f"Сегодня {today:%Y-%m-%d}, {WEEKDAYS[today.weekday()]}.")
        if known_tags:
            context.append(
                "Существующие теги базы (используй, если подходят): "
                + ", ".join(known_tags)
                + "."
            )
        if context:
            messages.append({"role": "system", "content": "\n".join(context)})

        messages.append({"role": "user", "content": text})

        payload: dict[str, Any] = {
            "model": self._llm_model,
            "messages": messages,
            "temperature": 0.3,
            "max_completion_tokens": 1200,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "note_draft",
                    "strict": True,
                    "schema": NOTE_DRAFT_SCHEMA,
                },
            },
        }

        try:
            response = await self._post_with_retry(
                f"{API_URL}/chat/completions",
                what="LLM",
                user_message="❌ Не удалось структурировать заметку. Попробуй переформулировать.",
                timeout=LLM_TIMEOUT,
                json=payload,
            )
        except GroqHTTPError as exc:
            if exc.status != 400:
                raise
            # Часть моделей не поддерживает json_schema — пробуем json_object.
            logger.warning("Модель отклонила json_schema, повторяю с json_object")
            payload["response_format"] = {"type": "json_object"}
            response = await self._post_with_retry(
                f"{API_URL}/chat/completions",
                what="LLM",
                user_message="❌ Не удалось структурировать заметку. Попробуй переформулировать.",
                timeout=LLM_TIMEOUT,
                json=payload,
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GroqError(
                f"Неожиданный ответ LLM: {response.text[:300]}",
                "❌ Не удалось структурировать заметку.",
            ) from exc

        try:
            draft = NoteDraft.model_validate_json(content)
        except ValidationError as exc:
            raise GroqError(
                f"LLM вернула невалидный JSON: {exc}",
                "❌ Не удалось структурировать заметку. Попробуй переформулировать.",
            ) from exc

        logger.debug("LLM: source=%s title=%r", source, draft.title)
        return draft

    # ── Ответ по заметкам ────────────────────────────────────

    async def answer_question(self, question: str, context: str) -> str:
        payload = {
            "model": self._llm_model,
            "messages": [
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "system", "content": f"Заметки:\n{context}"},
                {"role": "user", "content": question},
            ],
            "temperature": 0.2,
            "max_completion_tokens": 600,
        }

        response = await self._post_with_retry(
            f"{API_URL}/chat/completions",
            what="LLM",
            user_message="❌ Не удалось ответить по базе. Попробуй переформулировать.",
            timeout=LLM_TIMEOUT,
            json=payload,
        )

        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GroqError(
                f"Неожиданный ответ LLM: {response.text[:300]}",
                "❌ Не удалось ответить по базе.",
            ) from exc

    # ── Общий транспорт ──────────────────────────────────────

    async def _post_with_retry(
        self,
        url: str,
        *,
        what: str,
        user_message: str,
        timeout: httpx.Timeout,
        **kwargs: Any,
    ) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = await self._client.post(
                    url, headers=self._headers, timeout=timeout, **kwargs
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("%s: сеть, попытка %s: %r", what, attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GroqError(f"{what}: сеть недоступна: {exc!r}", user_message) from exc

            status = response.status_code

            if status in RETRY_STATUSES:
                logger.warning("%s: HTTP %s, попытка %s", what, status, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(_retry_after(response, attempt))
                    continue
                raise GroqHTTPError(status, f"{what}: HTTP {status} после 3 попыток", user_message)

            if status >= 400:
                logger.error("%s: HTTP %s: %s", what, status, response.text[:300])
                raise GroqHTTPError(
                    status,
                    f"{what}: HTTP {status}: {response.text[:300]}",
                    user_message,
                )

            return response

        raise GroqError(  # pragma: no cover - недостижимо
            f"{what}: исчерпаны попытки ({last_error!r})", user_message
        )


def _retry_after(response: httpx.Response, attempt: int) -> float:
    raw = response.headers.get("retry-after", "")
    try:
        return min(float(raw), 10.0)
    except (TypeError, ValueError):
        return float(2**attempt)
