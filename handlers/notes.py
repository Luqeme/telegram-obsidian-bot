"""Обработка заметок: текст (этап 1), голос (этап 2)."""

from __future__ import annotations

import csv
import html
import io
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
SUMMARY_LIMIT = 600
TASK_LIMIT = 200
MAX_CARD_TASKS = 15

MONEY_PATH = "30_Money/transactions.csv"
MONEY_HEADER = "date,kind,amount,category,note"


def _csv_row(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue().rstrip("\r\n")


def _clean_cell(value: str, limit: int = 120) -> str:
    return " ".join(value.replace("\n", " ").split())[:limit]


def _format_amount(amount: float) -> str:
    return f"{amount:.0f}" if amount == int(amount) else f"{amount:.2f}"


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

    if draft.money_kind != "none" and draft.money_amount > 0:
        await _save_money(message, services, draft, original, created)
        return

    content = build_markdown(draft, original, source, created)  # type: ignore[arg-type]
    filename = make_filename(
        draft.title,
        created,
        transliterate=services.settings.filename_transliterate,
    )
    commit_message = f"Add note from Telegram: {draft.title}"

    try:
        path, _ = await services.github.save_note(filename, content, commit_message)
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
        _render_card(path, draft),
        parse_mode="HTML",
    )


async def _save_money(
    message: Message,
    services: Services,
    draft: NoteDraft,
    original: str,
    created: datetime,
) -> None:
    category = _clean_cell(draft.money_category, limit=30) or "Прочее"
    amount = _format_amount(round(float(draft.money_amount), 2))
    row = _csv_row(
        [
            created.strftime("%Y-%m-%d"),
            draft.money_kind,
            amount,
            category,
            _clean_cell(original),
        ]
    )

    try:
        await services.github.append_line(
            MONEY_PATH,
            row,
            f"Money: {draft.money_kind} {amount}",
            header=MONEY_HEADER,
        )
    except GitHubError as exc:
        logger.error("append money: %s", exc)
        await message.answer(
            f"{exc.user_message}\n\nЗапись не потеряна:\n{original[:3000]}"
        )
        return

    kind = "Расход" if draft.money_kind == "expense" else "Доход"
    sign = "−" if draft.money_kind == "expense" else "+"
    logger.info("money_saved kind=%s amount=%s category=%s", draft.money_kind, amount, category)
    await message.answer(
        f"💰 <b>{kind} записан</b>\n\n"
        f"{sign}{amount} ₽ · {html.escape(category)}",
        parse_mode="HTML",
    )


def _render_card(path: str, draft: NoteDraft) -> str:
    lines = [
        "✅ <b>Заметка сохранена в Obsidian</b>",
        "",
        f"📁 <code>{html.escape(path)}</code>",
    ]

    tags = normalize_tags(draft.tags)
    if tags:
        lines.extend(
            ["", "🏷 " + " ".join(f"<code>#{html.escape(tag)}</code>" for tag in tags)]
        )

    if draft.summary:
        lines.extend(["", "💡 <b>Суть</b>", html.escape(_shorten(draft.summary))])

    if draft.tasks:
        lines.extend(["", "📋 <b>Задачи</b>"])
        for task in draft.tasks[:MAX_CARD_TASKS]:
            lines.append(f"• {html.escape(_shorten(task, TASK_LIMIT))}")
        hidden = len(draft.tasks) - MAX_CARD_TASKS
        if hidden > 0:
            lines.append(f"…и ещё {hidden}")

    # Режем по границе строки: каждая строка уже ограничена по длине,
    # поэтому HTML-теги внутри неё не разрываются.
    text = "\n".join(lines)
    if len(text) > CARD_LIMIT:
        text = text[:CARD_LIMIT].rsplit("\n", 1)[0] + "\n…"
    return text


def _shorten(text: str, limit: int = SUMMARY_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for separator in (". ", "! ", "? "):
        index = cut.rfind(separator)
        if index > limit // 2:
            return cut[: index + 1].strip()
    return cut.rstrip() + "…"
