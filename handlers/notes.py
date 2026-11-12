"""Обработка заметок: текст (этап 1), голос (этап 2)."""

from __future__ import annotations

import csv
import difflib
import hashlib
import html
import io
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from prompts import DEFAULT_MONEY_CATEGORIES
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
from services.undo import Action, UndoStore
from services.notes_index import STOPWORDS, WORD_RE, TaskRef

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

UNDO = UndoStore()

# callback_data ограничена 64 байтами, а путь с кириллицей в неё не влезает,
# поэтому в кнопке лежит короткий хеш, а путь — в памяти процесса.
_PROJECT_NOTES: dict[str, str] = {}
_PROJECT_HUBS: dict[str, str] = {}
_PROJECT_FOLDERS: dict[str, str] = {}

# путь заметки -> (исходный текст, source, user_id)
_FIX_DATA: dict[str, tuple[str, str, int]] = {}
# user_id -> (token кнопки «Исправить», id сообщения-приглашения)
FIX_PENDING: dict[int, tuple[str, int]] = {}


class IsFixReply(Filter):
    """Пользователь отвечает на приглашение исправить текст."""

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        reply = message.reply_to_message
        if user is None or reply is None:
            return False
        entry = FIX_PENDING.get(user.id)
        return bool(entry and entry[1] == reply.message_id)


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


@router.message(Command("undo"))
@router.message(Command("undo"))
async def cmd_undo(message: Message, services: Services) -> None:
    user = message.from_user
    if user is None:
        return
    await _undo_action(user.id, message, services)


async def _undo_action(user_id: int, message: Message, services: Services) -> None:
    """Откатывает последнее сохранение: заметку, транзакцию или бытовую задачу."""
    if not user_id:
        return

    action = UNDO.pop(user_id)
    if action is None:
        await message.answer("↩️ Нечего отменять.")
        return

    try:
        if action.kind == "note":
            deleted = await services.github.delete_file(
                action.path, f"Undo: delete {action.path}"
            )
            if not deleted:
                await message.answer(
                    "↩️ Не нашёл файл: возможно, его уже удалили или перенесли."
                )
                return
            services.index.invalidate()
            logger.info("undo_note path=%s", action.path)
            await message.answer(
                f"↩️ Удалена заметка:\n<code>{html.escape(action.path)}</code>",
                parse_mode="HTML",
            )
            return

        if action.kind == "replace" and len(action.lines) >= 2:
            restored = await services.github.replace_line(
                action.path,
                action.lines[0],
                action.lines[1],
                "Undo: restore line",
            )
            if not restored:
                await message.answer("↩️ Строка уже изменилась — откатывать нечего.")
                return
            services.index.invalidate()
            logger.info("undo_replace path=%s", action.path)
            await message.answer(f"↩️ Отменено: {html.escape(action.label)}.")
            return

        if action.kind == "move" and action.lines:
            original = action.lines[0]
            folder = original.rsplit("/", 1)[0] if "/" in original else ""
            if not folder:
                await message.answer("↩️ Не удалось определить исходную папку.")
                return
            moved = await services.github.move_file(
                action.path, folder, "Undo: move back"
            )
            if moved is None:
                await message.answer("↩️ Не нашёл файл для возврата.")
                return
            services.index.invalidate()
            logger.info("undo_move path=%s back=%s", action.path, moved)
            await message.answer(
                f"↩️ Возвращено:\n<code>{html.escape(moved)}</code>",
                parse_mode="HTML",
            )
            return

        removed = await services.github.remove_lines(
            action.path, action.lines, "Undo: remove last entry"
        )
        if removed == 0:
            await message.answer("↩️ Уже изменено — откатывать нечего.")
            return
        services.index.invalidate()
        logger.info("undo_lines path=%s removed=%s", action.path, removed)
        await message.answer(
            f"↩️ Отменено: {html.escape(action.label)} (строк: {removed})."
        )
    except GitHubError as exc:
        UNDO.push(user_id, action)
        logger.error("undo: %s", exc)
        await message.answer(exc.user_message)


@router.message(IsFixReply(), F.text)
async def on_fix_reply(message: Message, bot: Bot, services: Services) -> None:
    user = message.from_user
    if user is None:
        return

    entry = FIX_PENDING.pop(user.id, None)
    if entry is None:
        return
    token, _ = entry

    path = _PROJECT_NOTES.get(token)
    data = _FIX_DATA.get(path) if path else None
    if not path or data is None:
        await message.answer("✏️ Кнопка устарела — пришли заметку заново.")
        return

    corrected = (message.text or "").strip()
    if len(corrected) < MIN_TEXT_LEN or not any(char.isalpha() for char in corrected):
        await message.answer(
            "🤔 Слишком коротко. Пришли исправленный текст целиком."
        )
        return

    original, source, _owner = data
    new_path = await _process(
        bot,
        message,
        services,
        text=corrected,
        original=corrected,
        source=source,
        exclude_path=path,
    )
    if new_path is None:
        await message.answer(
            "Не удалось пересобрать заметку. Старая осталась на месте."
        )
        return

    try:
        deleted = await services.github.delete_file(
            path, f"Replace note: {path}"
        )
    except GitHubError as exc:
        logger.error("fix delete: %s", exc)
        await message.answer(
            "Новая заметка создана, но старую удалить не удалось. "
            "Удали её вручную или через /undo."
        )
        return

    services.index.invalidate()
    _FIX_DATA.pop(path, None)
    logger.info("note_replaced old=%s new=%s", path, new_path)
    if deleted:
        await message.answer("♻️ Заметка пересобрана, старая удалена.")
    else:
        await message.answer(
            "♻️ Заметка пересобрана. Старую не нашёл — возможно, её уже перенесли."
        )


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


def _push_undo(message: Message, action: Action) -> None:
    if message.from_user is not None:
        UNDO.push(message.from_user.id, action)


def _push_undo_user(user_id: int, action: Action) -> None:
    if user_id:
        UNDO.push(user_id, action)


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


def _stem_tokens(text: str) -> set[str]:
    """Первые 4 буквы слов: «купил» и «купить» дают один корень."""
    return {
        token[:4]
        for token in WORD_RE.findall(text.casefold())
        if len(token) >= 4 and token not in STOPWORDS
    }


def _find_open_task(query: str, tasks: list[TaskRef]) -> TaskRef | None:
    wanted = _stem_tokens(query)
    if not wanted:
        return None

    best: tuple[float, TaskRef] | None = None
    for task in tasks:
        have = _stem_tokens(task.text)
        if not have:
            continue
        overlap = len(wanted & have) / len(wanted)
        ratio = difflib.SequenceMatcher(
            None, " ".join(sorted(wanted)), " ".join(sorted(have))
        ).ratio()
        score = max(overlap, ratio * 0.9)
        if score < 0.5:
            continue
        if best is None or score > best[0]:
            best = (score, task)
    return best[1] if best else None


async def _complete_task(message: Message, services: Services, query: str) -> bool:
    """Закрывает подходящую открытую задачу. False, если не нашлась."""
    try:
        tasks = await services.index.open_tasks()
    except GitHubError as exc:
        logger.error("complete_task: %s", exc)
        await message.answer(exc.user_message)
        return True

    task = _find_open_task(query, tasks)
    if task is None:
        return False

    done = datetime.now(services.settings.tz).strftime("%Y-%m-%d")
    old_line = f"- [ ] {task.raw}"
    new_line = f"- [x] {task.raw} ✅ {done}"

    try:
        updated = await services.github.replace_line(
            task.note.path, old_line, new_line, f"Task done: {task.text}"
        )
    except GitHubError as exc:
        logger.error("complete_task: %s", exc)
        await message.answer(exc.user_message)
        return True

    if not updated:
        await message.answer("✅ Задача уже закрыта или изменилась.")
        return True

    services.index.invalidate()
    _push_undo(
        message,
        Action(
            kind="replace",
            path=task.note.path,
            lines=[new_line, old_line],
            label="задача",
        ),
    )
    logger.info("task_done_voice path=%s", task.note.path)
    await message.answer(
        f"✅ Задача закрыта:\n<b>{html.escape(task.text)}</b>",
        parse_mode="HTML",
    )
    return True


def _fallback_title(text: str) -> str:
    """Заголовок из первых слов, если LLM вернула пустой."""
    cleaned = " ".join(text.split()).strip(" .,:;!?—-\"'«»“”„")
    title = " ".join(cleaned.split()[:7])[:80].strip()
    return title or "Заметка"


def _remember_fix(path: str, original: str, source: str, owner: int) -> None:
    _FIX_DATA[path] = (original, source, owner)
    while len(_FIX_DATA) > 1000:
        _FIX_DATA.pop(next(iter(_FIX_DATA)))


async def _process(
    bot: Bot,
    message: Message,
    services: Services,
    *,
    text: str,
    original: str,
    source: str,
    exclude_path: str | None = None,
) -> str | None:
    now = datetime.now(services.settings.tz)

    known_tags: list[str] = []
    project_context = ""
    money_categories: list[str] = []
    try:
        known_tags = await services.index.top_tags(limit=30)
    except GitHubError as exc:
        logger.warning("Не удалось получить словарь тегов: %s", exc)

    _, project_context = await _index_context(services)

    try:
        money_categories = await services.index.money_categories()
    except GitHubError as exc:
        logger.warning("Не удалось получить категории денег: %s", exc)
    if not money_categories:
        money_categories = list(DEFAULT_MONEY_CATEGORIES)

    try:
        draft = await services.groq.structure_note(
            text,  # type: ignore[arg-type]
            source,  # type: ignore[arg-type]
            today=now.date(),
            known_tags=known_tags,
            known_projects=project_context,
            money_categories=money_categories,
        )
    except GroqError as exc:
        logger.error("structure_note: %s", exc)
        await message.answer(exc.user_message)
        return None

    if not draft.is_meaningful:
        await message.answer("🤔 В сообщении нет содержания для заметки.")
        return None

    if not draft.title:
        draft = draft.model_copy(update={"title": _fallback_title(text)})

    created = now

    if draft.money_kind != "none" and draft.money_amount > 0:
        await _save_money(message, services, draft, original, created)
        return None

    if draft.completed_task:
        if await _complete_task(message, services, draft.completed_task):
            return None
        await message.answer(
            "✅ Похоже, это выполненное дело, но открытой задачи не нашёл. "
            "Если это новая мысль — переформулируй как заметку."
        )
        return None

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
            return None

    related: list[tuple[str, str]] = []
    linked_summary = draft.summary
    try:
        all_notes = [
            note
            for note in await services.index.notes()
            if note.path != exclude_path
        ]
        for note in await services.index.similar(draft.tags, limit=4):
            if note.path == exclude_path:
                continue
            related.append((note.stem, note.title))
            if len(related) >= 2:
                break
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
    directory = target.folder if target is not None else None

    try:
        path, _ = await services.github.save_note(
            filename, content, commit_message, directory=directory
        )
    except GitHubError as exc:
        logger.error("save_note: %s", exc)
        await message.answer(
            f"{exc.user_message}\n\n"
            f"Заметка не потеряна, вот текст — пришли его позже:\n\n"
            f"{original[:3000]}"
        )
        return None

    logger.info(
        "note_saved user_id=%s source=%s chars=%s path=%s",
        message.from_user.id if message.from_user else 0,
        source,
        len(text),
        path,
    )
    services.index.invalidate()
    _push_undo(message, Action(kind="note", path=path, label="заметка"))
    _remember_fix(
        path,
        original,
        source,
        message.from_user.id if message.from_user else 0,
    )

    markup = await _project_keyboard(services, path)
    card = _render_card(path, draft, target.title if target is not None else "")
    if markup is not None:
        card += "\n\n🚀 <b>Проект?</b> Выбери или поменяй кнопкой ниже."
    await message.answer(card, parse_mode="HTML", reply_markup=markup)
    return path


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
        _remember(_PROJECT_FOLDERS, key, hub.folder)
        buttons.append(
            InlineKeyboardButton(
                text=hub.title[:32],
                callback_data=f"proj:{token}:{key}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text="Готово", callback_data=f"proj:{token}:none"
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

    rows.append(
        [
            InlineKeyboardButton(
                text="🗂 В архив", callback_data=f"triage:{token}:archive"
            ),
            InlineKeyboardButton(
                text="🗑 Удалить", callback_data=f"triage:{token}:delete"
            ),
        ]
    )

    if path in _FIX_DATA:
        rows.insert(
            -1,
            [
                InlineKeyboardButton(
                    text="✏️ Исправить", callback_data=f"fix:{token}"
                )
            ],
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _clear_markup(message: Message | None) -> None:
    if isinstance(message, Message):
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


@router.callback_query(
    F.data.startswith("proj:") | F.data.startswith("triage:")
)
async def on_project_choice(callback: CallbackQuery, services: Services) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return

    prefix, token, choice = parts
    path = _PROJECT_NOTES.get(token)
    if path is None:
        await callback.answer(
            "Кнопка устарела — пришли заметку ещё раз.", show_alert=True
        )
        return

    message = callback.message

    if prefix == "proj" and choice.startswith("page"):
        try:
            page = int(choice[4:])
        except ValueError:
            page = 0
        markup = await _project_keyboard(services, path, page)
        if markup is not None:
            try:
                if isinstance(message, Message):
                    await message.edit_reply_markup(reply_markup=markup)
            except TelegramAPIError:
                pass
        await callback.answer()
        return

    if prefix == "triage":
        if choice == "cancel":
            markup = await _project_keyboard(services, path, 0)
            if markup is not None and isinstance(message, Message):
                try:
                    await message.edit_reply_markup(reply_markup=markup)
                except TelegramAPIError:
                    pass
            await callback.answer("Отменено")
            return

        if choice == "delete":
            confirm = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да, удалить",
                            callback_data=f"triage:{token}:confirmed",
                        ),
                        InlineKeyboardButton(
                            text="Отмена",
                            callback_data=f"triage:{token}:cancel",
                        ),
                    ]
                ]
            )
            if isinstance(message, Message):
                try:
                    await message.edit_reply_markup(reply_markup=confirm)
                except TelegramAPIError:
                    pass
            await callback.answer("Удалить заметку?")
            return

        if choice == "confirmed":
            try:
                deleted = await services.github.delete_file(
                    path, f"Delete note: {path}"
                )
            except GitHubError as exc:
                logger.error("triage delete: %s", exc)
                await callback.answer(exc.user_message, show_alert=True)
                return
            if not deleted:
                await callback.answer("Заметка уже удалена.", show_alert=True)
                return
            _PROJECT_NOTES.pop(token, None)
            services.index.invalidate()
            await _clear_markup(message)
            await callback.answer("Удалено")
            logger.info("triage_deleted path=%s", path)
            return

        if choice == "archive":
            try:
                moved = await services.github.move_file(
                    path, "90_Archive", f"Archive note: {path}"
                )
            except GitHubError as exc:
                logger.error("triage archive: %s", exc)
                await callback.answer(exc.user_message, show_alert=True)
                return
            if moved is None:
                await callback.answer("Не нашёл заметку.", show_alert=True)
                return
            _PROJECT_NOTES.pop(token, None)
            services.index.invalidate()
            await _clear_markup(message)
            await callback.answer("В архиве")
            logger.info("triage_archived path=%s to=%s", path, moved)
            _push_undo_user(
                callback.from_user.id,
                Action(
                    kind="move",
                    path=moved,
                    lines=[path],
                    label="перенос в архив",
                ),
            )
            if isinstance(message, Message):
                await message.answer(
                    f"🗂 Перенесено в архив:\n<code>{html.escape(moved)}</code>",
                    parse_mode="HTML",
                )
            return

        await callback.answer()
        return

    if choice == "none":
        _PROJECT_NOTES.pop(token, None)
        await callback.answer("Готово")
        await _clear_markup(message)
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

    new_path = path
    inbox = services.settings.obsidian_inbox_dir.strip("/")
    if path.startswith(f"{inbox}/"):
        folder = _PROJECT_FOLDERS.get(choice, "20_Projects")
        try:
            moved = await services.github.move_file(
                path, folder, f"Move to project: {project}"
            )
        except GitHubError as exc:
            logger.error("move to project: %s", exc)
            await callback.answer(exc.user_message, show_alert=True)
            return
        if moved is not None:
            new_path = moved

    _PROJECT_NOTES.pop(token, None)
    services.index.invalidate()
    logger.info("project_linked path=%s project=%s", new_path, project)
    if new_path != path:
        _push_undo_user(
            callback.from_user.id,
            Action(
                kind="move",
                path=new_path,
                lines=[path],
                label="перенос в проект",
            ),
        )
    await callback.answer("Готово")
    await _clear_markup(message)

    if isinstance(message, Message):
        await message.answer(
            f"🚀 Заметка в проекте <b>{html.escape(project)}</b>\n"
            f"<code>{html.escape(new_path)}</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("fix:"))
async def on_fix_request(callback: CallbackQuery) -> None:
    token = (callback.data or "").partition(":")[2]
    path = _PROJECT_NOTES.get(token)
    data = _FIX_DATA.get(path) if path else None
    if not path or data is None:
        await callback.answer(
            "Кнопка устарела — пришли заметку заново.", show_alert=True
        )
        return

    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return

    original, _source, _owner = data
    prompt = (
        "✏️ Пришли исправленный текст ответом на это сообщение.\n\n"
        f"<b>Было:</b>\n<code>{html.escape(original[:2000])}</code>"
    )
    sent = await message.answer(
        prompt, parse_mode="HTML", reply_markup=ForceReply(selective=True)
    )
    FIX_PENDING[callback.from_user.id] = (token, sent.message_id)
    await callback.answer()


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
    _push_undo(
        message,
        Action(kind="lines", path=area.path, lines=lines, label="бытовое дело"),
    )

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
    _push_undo(
        message,
        Action(kind="lines", path=MONEY_PATH, lines=[row], label="транзакция"),
    )
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
