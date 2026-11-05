"""Обработка заметок: текст (этап 1), голос (этап 2)."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services import (
    GitHubError,
    GroqError,
    NoteDraft,
    Services,
    TaskItem,
    build_markdown,
    format_task,
    make_filename,
    normalize_tags,
    wiki_link,
    with_up_link,
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
PROJECT_PAGE_SIZE = 6

# callback_data ограничена 64 байтами, а путь с кириллицей в неё не влезает,
# поэтому в кнопке лежит короткий хеш, а путь — в памяти процесса.
_PROJECT_NOTES: dict[str, str] = {}
_PROJECT_HUBS: dict[str, str] = {}


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


AUDIO_EXTENSIONS = (
    ".ogg",
    ".oga",
    ".mp3",
    ".m4a",
    ".wav",
    ".flac",
    ".webm",
    ".mp4",
)


def _media_info(message: Message) -> tuple[str, int, int, str] | None:
    """file_id, размер, длительность, имя файла — для любого аудио-вложения."""
    if message.voice is not None:
        voice = message.voice
        return voice.file_id, voice.file_size or 0, voice.duration or 0, "voice.ogg"

    if message.video_note is not None:
        note = message.video_note
        return note.file_id, note.file_size or 0, note.duration or 0, "note.mp4"

    if message.audio is not None:
        audio = message.audio
        name = audio.file_name or "audio.mp3"
        return audio.file_id, audio.file_size or 0, audio.duration or 0, name

    if message.document is not None:
        document = message.document
        name = document.file_name or "audio.bin"
        mime = document.mime_type or ""
        if mime.startswith("audio/") or name.lower().endswith(AUDIO_EXTENSIONS):
            return document.file_id, document.file_size or 0, 0, name

    return None


@router.message(F.voice | F.video_note | F.audio | F.document)
async def handle_voice(message: Message, bot: Bot, services: Services) -> None:
    info = _media_info(message)
    if info is None:
        return  # обычный документ — не наше дело

    file_id, size, duration, filename = info
    logger.info(
        "media_received user_id=%s file=%s duration=%s size=%s",
        message.from_user.id if message.from_user else 0,
        filename,
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
        buffer = await bot.download(file_id)
    except TelegramAPIError as exc:
        logger.error("download media: %s", exc)
        await message.answer("❌ Не удалось скачать аудио. Попробуй ещё раз.")
        return

    if buffer is None:
        await message.answer("❌ Не удалось скачать аудио. Попробуй ещё раз.")
        return

    try:
        hint, _ = await _index_context(services)
        text = await services.groq.transcribe_audio(
            buffer.read(), filename=filename, hint=hint
        )
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


async def _index_context(services: Services) -> tuple[str, str]:
    """(словарь для Whisper, описание проектов для LLM)."""
    try:
        hubs = await services.index.projects()
        areas = await services.index.areas()
        tags = await services.index.top_tags(limit=20)
    except GitHubError as exc:
        logger.warning("Не удалось получить контекст базы: %s", exc)
        return "", ""

    targets = [*hubs, *areas]
    seen: set[str] = set()
    words: list[str] = []
    for word in [word for hub in targets for word in (hub.title, *hub.aliases)] + tags:
        key = word.casefold()
        if word and key not in seen:
            seen.add(key)
            words.append(word)
    hint = ", ".join(words)[:400]

    parts: list[str] = []
    for hub in hubs:
        line = hub.title
        if hub.aliases:
            line += f" ({', '.join(hub.aliases)})"
        if hub.description:
            line += f" — {hub.description}"
        parts.append(line)

    context = ""
    if parts:
        context = (
            "Проекты базы: "
            + "; ".join(parts)
            + ". Если текст явно про один из них, используй его точное название "
            "в title и summary."
        )

    if areas:
        area_parts: list[str] = []
        for area in areas:
            line = area.title
            if area.aliases:
                line += f" ({', '.join(area.aliases)})"
            if area.description:
                line += f" — {area.description}"
            area_parts.append(line)
        context += (
            "\nБытовые области: "
            + "; ".join(area_parts)
            + ". Если текст — бытовое дело (купить продукты, заехать в аптеку, "
            "забрать посылку), укажи точное название области в поле project."
        )
    return hint, context


async def _process(
    bot: Bot,
    message: Message,
    services: Services,
    *,
    text: str,
    original: str,
    source: str,
) -> None:
    now = datetime.now(services.settings.tz)

    known_tags: list[str] = []
    project_context = ""
    try:
        known_tags = await services.index.top_tags(limit=30)
    except GitHubError as exc:
        logger.warning("Не удалось получить словарь тегов: %s", exc)

    try:
        _, project_context = await _index_context(services)
    except GitHubError as exc:
        logger.warning("Не удалось получить проекты: %s", exc)
    try:
        draft = await services.groq.structure_note(
            text,  # type: ignore[arg-type]
            source,  # type: ignore[arg-type]
            today=now.date(),
            known_tags=known_tags,
            known_projects=project_context,
        )
    except GroqError as exc:
        logger.error("structure_note: %s", exc)
        await message.answer(exc.user_message)
        return

    if not draft.is_meaningful:
        await message.answer("🤔 В сообщении нет содержания для заметки.")
        return

    created = now

    if draft.money_kind != "none" and draft.money_amount > 0:
        await _save_money(message, services, draft, original, created)
        return

    target = None
    if draft.project:
        try:
            targets = [*await services.index.projects(), *await services.index.areas()]
        except GitHubError as exc:
            logger.warning("Не удалось проверить проект: %s", exc)
            targets = []
        target = _match_target(draft.project, targets)
        if target is not None and target.note_type == "area":
            await _save_area_tasks(message, services, draft, target, original)
            return

    related: list[tuple[str, str]] = []
    linked_summary = draft.summary
    try:
        all_notes = await services.index.notes()
        for note in await services.index.similar(draft.tags, limit=2):
            related.append((note.stem, note.title))
        linked_summary = wiki_link(
            draft.summary, [(note.stem, note.title) for note in all_notes]
        )
    except GitHubError as exc:
        logger.warning("Не удалось найти связанные заметки: %s", exc)

    content = build_markdown(
        draft.model_copy(update={"summary": linked_summary}),
        original,
        source,  # type: ignore[arg-type]
        created,
        related=related,
    )
    if target is not None:
        content = with_up_link(content, target.title)
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
    services.index.invalidate()

    markup = await _project_keyboard(services, path)
    card = _render_card(path, draft, target.title if target is not None else "")
    if markup is not None:
        card += "\n\n🚀 <b>Проект?</b> Выбери или поменяй кнопкой ниже."
    await message.answer(card, parse_mode="HTML", reply_markup=markup)


def _remember(mapping: dict[str, str], key: str, value: str, limit: int = 1000) -> None:
    mapping[key] = value
    while len(mapping) > limit:
        mapping.pop(next(iter(mapping)))


def _normalize_project(value: str) -> str:
    return " ".join(value.strip().casefold().replace("-", " ").split())


def _match_target(value: str, targets: list):
    """Возвращает хаб проекта или области, если LLM назвала его/алиас."""
    wanted = _normalize_project(value)
    if not wanted:
        return None
    for target in targets:
        for name in (target.title, *target.aliases):
            if _normalize_project(name) == wanted:
                return target
    return None


async def _project_keyboard(
    services: Services, path: str, page: int = 0
) -> InlineKeyboardMarkup | None:
    """Кнопки проектов с постраничной навигацией. None, если хабов нет."""
    try:
        hubs = await services.index.projects()
    except GitHubError as exc:
        logger.warning("Не удалось получить проекты: %s", exc)
        return None

    if not hubs:
        return None

    token = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    _remember(_PROJECT_NOTES, token, path)

    pages = (len(hubs) + PROJECT_PAGE_SIZE - 1) // PROJECT_PAGE_SIZE
    page = max(0, min(page, pages - 1))
    chunk = hubs[page * PROJECT_PAGE_SIZE : (page + 1) * PROJECT_PAGE_SIZE]

    buttons: list[InlineKeyboardButton] = []
    for hub in chunk:
        key = hashlib.sha1(hub.path.encode("utf-8")).hexdigest()[:8]
        _remember(_PROJECT_HUBS, key, hub.title)
        buttons.append(
            InlineKeyboardButton(
                text=hub.title[:32],
                callback_data=f"proj:{token}:{key}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text="Без проекта", callback_data=f"proj:{token}:none"
        )
    )
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]

    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀", callback_data=f"proj:{token}:page{page - 1}"
                )
            )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text="Ещё ▶", callback_data=f"proj:{token}:page{page + 1}"
                )
            )
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("proj:"))
async def on_project_choice(callback: CallbackQuery, services: Services) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return

    _, token, choice = parts
    path = _PROJECT_NOTES.get(token)
    if path is None:
        await callback.answer(
            "Кнопка устарела — пришли заметку ещё раз.", show_alert=True
        )
        return

    message = callback.message

    if choice.startswith("page"):
        try:
            page = int(choice[4:])
        except ValueError:
            page = 0
        markup = await _project_keyboard(services, path, page)
        if isinstance(message, Message) and markup is not None:
            try:
                await message.edit_reply_markup(reply_markup=markup)
            except TelegramAPIError:
                pass
        await callback.answer()
        return

    _PROJECT_NOTES.pop(token, None)

    if choice == "none":
        await callback.answer("Без проекта")
        if isinstance(message, Message):
            try:
                await message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
        return

    project = _PROJECT_HUBS.get(choice)
    if project is None:
        await callback.answer(
            "Проект не найден — пришли заметку ещё раз.", show_alert=True
        )
        return

    try:
        updated = await services.github.set_up_link(
            path, project, f"Set project: {project}"
        )
    except GitHubError as exc:
        logger.error("set_up_link: %s", exc)
        await callback.answer(exc.user_message, show_alert=True)
        return

    if not updated:
        await callback.answer("Не нашёл заметку в GitHub.", show_alert=True)
        return

    services.index.invalidate()
    logger.info("project_linked path=%s project=%s", path, project)
    await callback.answer("Готово")

    if isinstance(message, Message):
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await message.answer(
            f"🚀 Заметка добавлена в проект <b>{html.escape(project)}</b>",
            parse_mode="HTML",
        )


async def _save_area_tasks(
    message: Message,
    services: Services,
    draft: NoteDraft,
    area,
    original: str,
) -> None:
    """Бытовое дело: дописывает задачи в чек-лист области, а не создаёт заметку."""
    tasks = draft.tasks or [TaskItem(text=draft.title)]
    lines = [format_task(task) for task in tasks]

    try:
        await services.github.append_lines(
            area.path, lines, f"Home: {draft.title}"
        )
    except GitHubError as exc:
        logger.error("append area: %s", exc)
        await message.answer(
            f"{exc.user_message}\n\nЗадача не потеряна:\n{original[:3000]}"
        )
        return

    services.index.invalidate()
    logger.info("area_saved path=%s tasks=%s", area.path, len(lines))

    bullets = []
    for task in tasks[:10]:
        line = f"• {html.escape(task.text)}"
        if task.due:
            line += f" · до {task.due[8:10]}.{task.due[5:7]}"
        bullets.append(line)

    await message.answer(
        f"🏠 <b>{html.escape(area.title)}</b>\n\n" + "\n".join(bullets),
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


def _render_card(path: str, draft: NoteDraft, project: str = "") -> str:
    lines = [
        "✅ <b>Заметка сохранена в Obsidian</b>",
        "",
        f"📁 <code>{html.escape(path)}</code>",
    ]

    if project:
        lines.extend(["", f"🚀 Проект: <b>{html.escape(project)}</b>"])

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
            line = html.escape(_shorten(task.text, TASK_LIMIT))
            if task.due:
                line += f" · до {task.due[8:10]}.{task.due[5:7]}"
            lines.append(f"• {line}")
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
