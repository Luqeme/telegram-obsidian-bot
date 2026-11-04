"""Служебные команды: /start, /help, /id, /find, /ask, /money."""

from __future__ import annotations

import csv
import html
import io
import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from services import GitHubError, GroqError, Services

router = Router(name="base")
logger = logging.getLogger(__name__)

MONEY_PATH = "30_Money/transactions.csv"
SEARCH_LIMIT = 5
SNIPPET_PAD = 60
ASK_CONTEXT_NOTES = 5
ASK_CONTEXT_CHARS = 700


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет!\n\n"
        "Кидай сюда мысль текстом или голосовым — я разберу её на тезисы, "
        "теги и задачи и сохраню заметку в Obsidian.\n\n"
        "Команды:\n"
        "/find — поиск по базе\n"
        "/ask — вопрос к базе\n"
        "/today — сводка на сегодня\n"
        "/money — деньги за месяц\n"
        "/id — твой Telegram ID\n"
        "/help — как это работает"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📥 <b>Как пользоваться</b>\n\n"
        "Отправь текст или голосовое — получишь готовую заметку в базе знаний.\n\n"
        "Что я делаю:\n"
        "• расшифровываю голос;\n"
        "• выделяю заголовок, суть и задачи;\n"
        "• ставлю сроки и приоритеты в формате Tasks;\n"
        "• подбираю теги и связанные заметки;\n"
        "• сохраняю .md в репозиторий Obsidian.\n\n"
        "<b>Команды</b>\n"
        "/find <i>запрос</i> — поиск по заметкам\n"
        "/ask <i>вопрос</i> — ответ по содержимому базы\n"
        "/today — что сегодня, с кнопками закрытия задач\n"
        "/money — доход и расход за месяц\n\n"
        "Деньги: «потратил 540 на обед», «заработал 5000» — запишу в отдельный файл.\n\n"
        "Если что-то сломалось — пришлю текст обратно, ничего не потеряется.",
        parse_mode="HTML",
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя.")
        return
    await message.answer(
        f"🆔 Твой user_id: <code>{user.id}</code>\n"
        f"Внеси его в <code>ALLOWED_TELEGRAM_USERS</code> в .env",
        parse_mode="HTML",
    )


@router.message(Command("find"))
async def cmd_find(message: Message, services: Services) -> None:
    query = _argument(message)
    if len(query) < 2:
        await message.answer("🔎 Что искать? Например: <code>/find JWT</code>", parse_mode="HTML")
        return

    try:
        found = await services.index.search(query, limit=SEARCH_LIMIT)
    except GitHubError as exc:
        logger.error("find: %s", exc)
        await message.answer(exc.user_message)
        return

    if not found:
        await message.answer(f"🔎 По запросу «{html.escape(query)}» ничего не нашлось.")
        return

    lines = [f"🔎 <b>Найдено: {len(found)}</b>", ""]
    for note in found:
        lines.append(f"• <b>{html.escape(note.title)}</b>")
        if note.tags:
            tags = " ".join(f"#{html.escape(tag)}" for tag in note.tags[:4])
            lines.append(f"  <code>{tags}</code>")
        snippet = _snippet(note.text, query)
        if snippet:
            lines.append(f"  <i>{html.escape(snippet)}</i>")
        lines.append("")

    await message.answer(
        "\n".join(lines).strip(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("ask"))
async def cmd_ask(message: Message, services: Services) -> None:
    question = _argument(message)
    if len(question) < 3:
        await message.answer(
            "💬 О чём спросить? Например: <code>/ask что я писал про дашборд</code>",
            parse_mode="HTML",
        )
        return

    try:
        found = await services.index.search(question, limit=ASK_CONTEXT_NOTES)
    except GitHubError as exc:
        logger.error("ask: %s", exc)
        await message.answer(exc.user_message)
        return

    if not found:
        await message.answer(
            f"💬 В базе нет заметок по запросу «{html.escape(question)}»."
        )
        return

    context = "\n\n".join(
        f"### {note.title}\n{note.text[:ASK_CONTEXT_CHARS]}" for note in found
    )

    try:
        answer = await services.groq.answer_question(question, context)
    except GroqError as exc:
        logger.error("ask: %s", exc)
        await message.answer(exc.user_message)
        return

    sources = "\n".join(f"• {html.escape(note.title)}" for note in found[:3])
    await message.answer(
        f"{html.escape(answer)}\n\n<blockquote>Источники:\n{sources}</blockquote>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("money"))
async def cmd_money(message: Message, services: Services) -> None:
    try:
        rows = await _read_money(services)
    except GitHubError as exc:
        logger.error("money: %s", exc)
        await message.answer(exc.user_message)
        return

    now = datetime.now(services.settings.tz)
    month = now.strftime("%Y-%m")
    month_rows = [row for row in rows if str(row.get("date", "")).startswith(month)]

    if not month_rows:
        await message.answer(f"💰 За {now:%m.%Y} записей нет.")
        return

    spent = sum(float(row["amount"]) for row in month_rows if row.get("kind") == "expense")
    earned = sum(float(row["amount"]) for row in month_rows if row.get("kind") == "income")

    by_category: dict[str, float] = {}
    for row in month_rows:
        if row.get("kind") != "expense":
            continue
        category = (row.get("category") or "Прочее").strip()
        by_category[category] = by_category.get(category, 0.0) + float(row["amount"])

    top = sorted(by_category.items(), key=lambda item: -item[1])[:3]

    lines = [
        f"💰 <b>За {now:%m.%Y}</b>",
        "",
        f"Доход: <b>{_money(earned)} ₽</b>",
        f"Расход: <b>{_money(spent)} ₽</b>",
        f"Итого: <b>{_money(earned - spent)} ₽</b>",
    ]
    if top:
        lines.extend(["", "<b>Куда ушло</b>"])
        for category, amount in top:
            lines.append(f"• {html.escape(category)} — {_money(amount)} ₽")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── Вспомогательное ──────────────────────────────────────────


def _argument(message: Message) -> str:
    return (message.text or "").partition(" ")[2].strip()


async def _read_money(services: Services) -> list[dict]:
    raw = await services.github.get_text(MONEY_PATH)
    if not raw.strip():
        return []
    return [row for row in csv.DictReader(io.StringIO(raw)) if row.get("date")]


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _snippet(text: str, query: str) -> str:
    lowered = text.casefold()
    index = lowered.find(query.casefold())
    if index == -1:
        return ""
    start = max(0, index - SNIPPET_PAD)
    end = min(len(text), index + len(query) + SNIPPET_PAD)
    fragment = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + fragment + ("…" if end < len(text) else "")
