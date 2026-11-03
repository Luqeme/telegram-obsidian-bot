"""Обработка заметок: текст (этап 1), голос (этап 2)."""

from __future__ import annotations

import html
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from services import (
    GitHubError,
    GroqError,
    NoteDraft,
    Services,
    build_markdown,
    make_filename,
    normalize_tags,
)

logger = logging.getLogger(__name__)

router = Router(name="notes")

MIN_TEXT_LEN = 15
MIN_TRANSCRIPT_LEN = 10
MAX_AUDIO_SECONDS = 20 * 60
CARD_LIMIT = 4000
SUMMARY_LIMIT = 1200


def check_voice_limits(size: int, duration: int, limit_mb: int) -> str | None:
    """Возвращает текст отказа или None, если запись допустима."""
    if duration > MAX_AUDIO_SECONDS:
        return (
            f"⚠️ Слишком длинная запись (~{duration // 60} мин). "
            f"Максимум {MAX_AUDIO_SECONDS // 60} минут за раз."
        )
    if size > limit_mb * 1024 * 1024:
        return (
            f"⚠️ Запись слишком большая ({size / 1024 / 1024:.1f} МБ). "
            f"Максимум {limit_mb} МБ."
        )
    return None


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message, bot: Bot, services: Services) -> None:
    text = (message.text or "").strip()

    if len(text) < MIN_TEXT_LEN or not any(char.isalpha() for char in text):
        await message.answer(
            "🤔 Слишком коротко, чтобы сделать заметку. Напиши пару предложений."
        )
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _process(bot, message, services, text=text, original=text, source="text")


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, services: Services) -> None:
    voice = message.voice
    if voice is None:
        return

    size = voice.file_size or 0
    duration = voice.duration or 0
    logger.info(
        "voice_received user_id=%s duration=%s size=%s",
        message.from_user.id if message.from_user else 0,
        duration,
        size,
    )

    reason = check_voice_limits(size, duration, services.settings.max_audio_mb)
    if reason:
        await message.answer(reason)
        return

    await bot.send_chat_action(message.chat.id, ChatAction.RECORD_VOICE)

    # Аудио живёт только в памяти: на диск ничего не пишем и удалять нечего.
    try:
        buffer = await bot.download(voice)
    except TelegramAPIError as exc:
        logger.error("download voice: %s", exc)
        await message.answer("❌ Не удалось скачать аудио. Попробуй ещё раз.")
        return

    if buffer is None:
        await message.answer("❌ Не удалось скачать аудио. Попробуй ещё раз.")
        return

    try:
        text = await services.groq.transcribe_audio(buffer.read(), filename="voice.ogg")
    except GroqError as exc:
        logger.error("transcribe_audio: %s", exc)
        await message.answer(exc.user_message)
        return

    if len(text) < MIN_TRANSCRIPT_LEN or not any(char.isalpha() for char in text):
        await message.answer(
            "🤔 Не удалось разобрать речь. Попробуй ещё раз или отправь текстом."
        )
        return

    logger.info("voice_transcribed user_id=%s chars=%s", message.from_user.id, len(text))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await _process(bot, message, services, text=text, original=text, source="voice")


async def _process(
    bot: Bot,
    message: Message,
    services: Services,
    *,
    text: str,
    original: str,
    source: str,
) -> None:
    try:
        draft = await services.groq.structure_note(text, source)  # type: ignore[arg-type]
    except GroqError as exc:
        logger.error("structure_note: %s", exc)
        await message.answer(exc.user_message)
        return

    if not draft.is_meaningful:
        await message.answer("🤔 В сообщении нет содержания для заметки.")
        return

    created = datetime.now(services.settings.tz)
    content = build_markdown(draft, original, source, created)  # type: ignore[arg-type]
    filename = make_filename(
        draft.title,
        created,
        transliterate=services.settings.filename_transliterate,
    )
    commit_message = f"Add note from Telegram: {draft.title}"

    try:
        path, url = await services.github.save_note(filename, content, commit_message)
    except GitHubError as exc:
        logger.error("save_note: %s", exc)
        await message.answer(
            f"{exc.user_message}\n\n"
            f"Заметка не потеряна, вот текст — пришли его позже:\n\n"
            f"{original[:3000]}"
        )
        return

    logger.info(
        "note_saved user_id=%s source=%s chars=%s path=%s",
        message.from_user.id if message.from_user else 0,
        source,
        len(text),
        path,
    )
    await message.answer(
        _render_card(path, url, draft),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def _render_card(path: str, url: str, draft: NoteDraft) -> str:
    lines = [
        "✅ <b>Заметка сохранена в Obsidian</b>",
        "",
        f"📁 <code>{html.escape(path)}</code>",
    ]
    if url:
        lines.append(f'🔗 <a href="{html.escape(url, quote=True)}">Открыть в GitHub</a>')

    tags = normalize_tags(draft.tags)
    if tags:
        lines.extend(
            ["", "🏷 " + " ".join(f"<code>#{html.escape(tag)}</code>" for tag in tags)]
        )

    if draft.summary:
        lines.extend(["", "💡 <b>Суть</b>", html.escape(_shorten(draft.summary))])

    if draft.tasks:
        lines.extend(["", f"📋 Задач: {len(draft.tasks)}"])

    return "\n".join(lines)[:CARD_LIMIT]


def _shorten(text: str) -> str:
    if len(text) <= SUMMARY_LIMIT:
        return text
    cut = text[:SUMMARY_LIMIT]
    for separator in (". ", "! ", "? "):
        index = cut.rfind(separator)
        if index > SUMMARY_LIMIT // 2:
            return cut[: index + 1].strip()
    return cut.rstrip() + "…"
