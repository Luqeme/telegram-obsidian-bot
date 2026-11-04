"""Служебные команды: /start, /help, /id, /find, /today, /money."""

from __future__ import annotations

import csv
import html
import io
import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from services import GitHubError, Services

router = Router(name="base")
logger = logging.getLogger(__name__)

MONEY_PATH = "30_Money/transactions.csv"
SEARCH_LIMIT = 5
TASK_LIMIT = 5
SNIPPET_PAD = 60


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет!\n\n"
        "Кидай сюда мысль текстом или голосовым — я разберу её на тезисы, "
        "теги и задачи и сохраню заметку в Obsidian.\n\n"
        "Команды:\n"
        "/find — поиск по базе\n"
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
        "• подбираю теги и связанные заметки;\n"
        "• сохраняю .md в репозиторий Obsidian.\n\n"
        "<b>Команды</b>\n"
        "/find <i>запрос</i> — поиск по заметкам\n"
        "/today — что сегодня: заметки, задачи, траты\n"
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
    query = (message.text or "").partition(" ")[2].strip()
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


@router.message(Command("today"))
async def cmd_today(message: Message, services: Services) -> None:
    try:
        notes = await services.index.notes()
        money_rows = await _read_money(services)
    except GitHubError as exc:
        logger.error("today: %s", exc)
        await message.answer(exc.user_message)
        return

    tz = services.settings.tz
    now = datetime.now(tz)
    today = now.date()

    today_notes = [
        note
        for note in notes
        if note.created is not None and note.created.astimezone(tz).date() == today
    ]
    open_tasks = [(note.title, task) for note in notes for task in note.tasks]
    today_money = [row for row in money_rows if row.get("date") == today.isoformat()]

    spent = sum(float(row["amount"]) for row in today_money if row.get("kind") == "expense")
    earned = sum(float(row["amount"]) for row in today_money if row.get("kind") == "income")

    lines = [
        f"📅 <b>Сегодня, {now:%d.%m}</b>",
        "",
        f"Заметок: <b>{len(today_notes)}</b>",
        f"Открытых задач: <b>{len(open_tasks)}</b>",
    ]
    if spent or earned:
        lines.append(f"Потрачено: <b>{_money(spent)} ₽</b> · Получено: <b>{_money(earned)} ₽</b>")

    if today_notes:
        lines.extend(["", "<b>Новое</b>"])
        for note in today_notes[:5]:
            lines.append(f"• {html.escape(note.title)}")

    if open_tasks:
        lines.extend(["", "<b>Задачи</b>"])
        for _, task in open_tasks[:TASK_LIMIT]:
            lines.append(f"☐ {html.escape(task)}")
        if len(open_tasks) > TASK_LIMIT:
            lines.append(f"…и ещё {len(open_tasks) - TASK_LIMIT}")

    await message.answer("\n".join(lines), parse_mode="HTML")


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
