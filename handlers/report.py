"""Отчёт по деньгам: команда /report, подменю и автоматическая отправка."""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from handlers.menu_ui import main_menu
from services import GitHubError, Services
from services.money import (
    MONEY_PATH,
    MonthSummary,
    format_rub,
    month_label,
    parse_rows,
    previous_month,
    summarize,
)
from services.widgets import (
    MONTH_SHORT,
    build_report_shell,
    send_widget,
)

router = Router(name="report")
logger = logging.getLogger(__name__)

MAIN_TEXT = "Главное меню:"
REPORT_TEXT = "📊 <b>Отчёт</b>\n\nВыбери период:"
MONTHS_TEXT = "📅 <b>Выбери месяц</b>"
MONTHS_LIMIT = 12
REPORT_CAPTION = "📊 Отчёт по деньгам"
REPORT_STATE_LIMIT = 1024
REPORT_ROWS = 6


@router.message(Command("report"))
async def cmd_report(message: Message, services: Services) -> None:
    now = datetime.now(services.settings.tz)
    view = "current"
    argument = (message.text or "").partition(" ")[2].strip()
    if argument:
        month = _parse_month(argument)
        if month is None:
            await message.answer(
                "Формат: <code>/report 2026-10</code> — год и месяц через дефис.",
                parse_mode="HTML",
            )
            return
        view = f"mon:{month}"
    await _send_report(message, services, view)


@router.message(Command("money"))
async def cmd_money(message: Message, services: Services) -> None:
    """Старый /money оставлен алиасом, чтобы не ломать привычку."""
    await _send_report(message, services, "current")


@router.callback_query(F.data.startswith("rep:"))
async def on_report(callback: CallbackQuery, services: Services) -> None:
    data = callback.data or ""
    action = data.partition(":")[2]
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return

    await callback.answer()

    if action == "now":
        await _send_report(message, services, "current")
        return
    if action == "prev":
        await _send_report(message, services, "prev")
        return
    if action == "year":
        await _send_report(
            message,
            services,
            f"year:{datetime.now(services.settings.tz).year}",
        )
        return
    if action == "months":
        await _send_report(
            message,
            services,
            f"months:{datetime.now(services.settings.tz).year}",
        )
        return
    if action == "back":
        await show_report_menu(message)
        return
    if action == "main":
        await _edit(message, MAIN_TEXT, main_menu())
        return
    if action.startswith("m:"):
        month = _parse_month(action[2:])
        if month is not None:
            await _send_report(message, services, f"mon:{month}")
        return

    await message.answer("Неизвестный пункт отчёта.")


async def show_report_menu(message: Message) -> None:
    await _edit(message, REPORT_TEXT, report_menu())


def report_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Текущий", callback_data="rep:now"),
                InlineKeyboardButton(text="Прошлый", callback_data="rep:prev"),
            ],
            [
                InlineKeyboardButton(text="Месяц", callback_data="rep:months"),
                InlineKeyboardButton(text="Год", callback_data="rep:year"),
            ],
            [InlineKeyboardButton(text="◀ Меню", callback_data="rep:main")],
        ]
    )


def months_menu(rows: list[dict]) -> InlineKeyboardMarkup:
    months = sorted(
        {
            str(row.get("date", ""))[:7]
            for row in rows
            if len(str(row.get("date", ""))) >= 7
        },
        reverse=True,
    )[:MONTHS_LIMIT]

    buttons = [
        InlineKeyboardButton(text=month_label(month), callback_data=f"rep:m:{month}")
        for month in months
    ]
    keyboard = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    keyboard.append(
        [InlineKeyboardButton(text="◀ Назад", callback_data="rep:back")]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def report_loop(bot: Bot, services: Services) -> None:
    """1-го числа в MONTHLY_REPORT_TIME присылает отчёт за прошлый месяц."""
    while True:
        delay = _seconds_until_month_start(
            services.settings.monthly_report_time, services.settings.tz
        )
        await asyncio.sleep(delay)

        try:
            now = datetime.now(services.settings.tz)
            month = previous_month(now.strftime("%Y-%m"))
            rows = await _read_money(services)
            if summarize(rows, month).count:
                for user_id in services.settings.allowed_user_ids:
                    try:
                        await _send_month_widget(
                            bot, user_id, services, rows, month
                        )
                    except TelegramAPIError as exc:
                        logger.warning("Отчёт не ушёл %s: %s", user_id, exc)
        except Exception:  # noqa: BLE001 - фоновая задача не должна падать
            logger.exception("Месячный отчёт не отправился")

        await asyncio.sleep(61)


async def _send_report(
    message: Message, services: Services, view: str
) -> None:
    logger.info("report send view=%r chat=%s", view, message.chat.id)
    try:
        rows = await _read_money(services)
    except GitHubError as exc:
        logger.error("report: %s", exc)
        await message.answer(exc.user_message)
        return
    await _send_report_state(message.bot, message.chat.id, services, rows, view)


def report_state(
    rows: list[dict], view: str, now: datetime
) -> dict:
    """Состояние виджета отчёта для вида ``current``/``prev``/``mon:``/``year:``..."""
    now_month = now.strftime("%Y-%m")
    parts = view.split(":")
    kind = parts[0]
    argument = parts[1] if len(parts) > 1 else ""

    if kind == "current":
        return _month_state(rows, now_month, now_month)
    if kind == "prev":
        return _month_state(rows, previous_month(now_month), now_month)
    if kind == "months":
        return _months_state(rows, _year(argument, now.year))
    if kind == "year":
        return _year_state(rows, _year(argument, now.year), now.year)
    if kind == "mon":
        month = _parse_month(argument) or now_month
        return _month_state(rows, month, now_month)
    if kind in ("mp", "mn"):
        month = _parse_month(argument) or now_month
        shift = -1 if kind == "mp" else 1
        return _month_state(rows, _shift_month(month, shift), now_month)
    if kind in ("yp", "yn"):
        year = _year(argument, now.year)
        return _year_state(rows, year + (-1 if kind == "yp" else 1), now.year)
    return _month_state(rows, now_month, now_month)


def _month_state(rows: list[dict], month: str, now_month: str) -> dict:
    summary = summarize(rows, month)
    total = summary.expense or 1.0
    items = [
        [category, round(amount), round(amount / total * 100)]
        for category, amount in summary.expense_categories[:REPORT_ROWS]
    ]
    if month == now_month:
        active = "current"
    elif month == previous_month(now_month):
        active = "prev"
    else:
        active = "month"
    return {
        "k": "m",
        "v": month,
        "y": int(month[:4]),
        "t": month_label(month),
        "i": round(summary.income),
        "e": round(summary.expense),
        "b": round(summary.balance),
        "r": items,
        "a": active,
    }


def _year_state(rows: list[dict], year: int, now_year: int) -> dict:
    months = [summarize(rows, f"{year}-{number:02d}") for number in range(1, 13)]
    income = sum(item.income for item in months)
    expense = sum(item.expense for item in months)
    maximum = max((item.expense for item in months), default=0.0) or 1.0
    items = [
        [MONTH_SHORT[index], round(item.expense), round(item.expense / maximum * 100)]
        for index, item in enumerate(months)
        if item.count
    ]
    return {
        "k": "y",
        "v": str(year),
        "y": year,
        "t": f"{year} год",
        "i": round(income),
        "e": round(expense),
        "b": round(income - expense),
        "r": items,
        "a": "year" if year == now_year else "",
    }


def _months_state(rows: list[dict], year: int) -> dict:
    counts = [summarize(rows, f"{year}-{number:02d}").count for number in range(1, 13)]
    return {
        "k": "l",
        "v": str(year),
        "y": year,
        "t": f"Выбери месяц · {year}",
        "i": 0,
        "e": 0,
        "b": 0,
        "r": [],
        "a": "month",
        "d": "".join("1" if count else "0" for count in counts),
    }


def dumps_report_state(state: dict) -> str:
    """JSON состояния; подрезает строки, чтобы влезть в лимит chat_data."""
    state = dict(state)
    state["r"] = [list(row) for row in state.get("r", [])]
    payload = json.dumps(state, ensure_ascii=False)
    while state["r"] and len(payload.encode("utf-8")) > REPORT_STATE_LIMIT:
        state["r"].pop()
        payload = json.dumps(state, ensure_ascii=False)
    return payload


def _year(value: str, default: int) -> int:
    if value.isdigit() and 2000 <= int(value) <= 2100:
        return int(value)
    return default


def _shift_month(month: str, delta: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + (number - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


async def read_money(services: Services) -> list[dict]:
    raw = await services.github.get_text(MONEY_PATH)
    return parse_rows(raw)


async def _send_report_state(
    bot: Bot,
    chat_id: int,
    services: Services,
    rows: list[dict],
    view: str,
) -> None:
    state = report_state(rows, view, datetime.now(services.settings.tz))
    markup = build_report_shell()
    if markup:
        ok, reason = await send_widget(
            services.settings.telegram_bot_token,
            chat_id,
            markup,
            REPORT_CAPTION,
            allow_queries=True,
            chat_data=dumps_report_state(state),
        )
        if ok:
            logger.info("report_widget view=%s", view)
            return
        logger.warning("report_widget: %s", reason)

    if state["k"] == "l":
        await bot.send_message(
            chat_id,
            MONTHS_TEXT,
            parse_mode="HTML",
            reply_markup=months_menu(rows),
        )
    elif state["k"] == "y":
        await bot.send_message(
            chat_id,
            render_year(rows, state["y"]),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await bot.send_message(
            chat_id,
            render_report(rows, state["v"]),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def _send_month_report(
    message: Message, services: Services, month: str
) -> None:
    await _send_report(message, services, f"mon:{month}")


async def _send_year_report(
    message: Message, services: Services, year: int
) -> None:
    await _send_report(message, services, f"year:{year}")


async def _send_month_widget(
    bot: Bot,
    chat_id: int,
    services: Services,
    rows: list[dict],
    month: str,
) -> None:
    await _send_report_state(bot, chat_id, services, rows, f"mon:{month}")


async def _send_year_widget(
    bot: Bot,
    chat_id: int,
    services: Services,
    rows: list[dict],
    year: int,
) -> None:
    await _send_report_state(bot, chat_id, services, rows, f"year:{year}")


def render_report(rows: list[dict], month: str) -> str:
    summary = summarize(rows, month)
    label = month_label(month)

    if summary.count == 0:
        return f"📊 <b>Отчёт за {label}</b>\n\nЗаписей нет."

    lines = [
        f"📊 <b>Отчёт за {label}</b>",
        "",
        f"Доход: <b>{format_rub(summary.income)} ₽</b>",
        f"Расход: <b>{format_rub(summary.expense)} ₽</b>",
        f"Остаток: <b>{format_rub(summary.balance)} ₽</b>",
        f"Операций: {summary.count}",
    ]

    lines.extend(_category_lines(summary))

    if summary.income_categories:
        lines.extend(["", "<b>Доходы</b>"])
        for category, amount in summary.income_categories[:5]:
            lines.append(f"• {html.escape(category)} — {format_rub(amount)} ₽")

    if summary.top_expenses:
        lines.extend(["", "<b>Крупные траты</b>"])
        for item in summary.top_expenses:
            note = item["note"]
            suffix = f" · {html.escape(note[:60])}" if note else ""
            lines.append(
                f"• {format_rub(item['amount'])} ₽ · "
                f"{html.escape(item['category'])}{suffix}"
            )

    previous = summarize(rows, previous_month(month))
    if previous.expense > 0:
        delta = (summary.expense - previous.expense) / previous.expense * 100
        sign = "−" if delta < 0 else "+"
        lines.extend(
            [
                "",
                f"<i>Прошлый месяц ({month_label(previous.month)}): "
                f"{format_rub(previous.expense)} ₽ · {sign}{abs(delta):.0f}%</i>",
            ]
        )

    return "\n".join(lines)


def render_year(rows: list[dict], year: int) -> str:
    months = [summarize(rows, f"{year}-{number:02d}") for number in range(1, 13)]
    if not any(item.count for item in months):
        return f"📊 <b>Отчёт за {year} год</b>\n\nЗаписей нет."

    income = sum(item.income for item in months)
    expense = sum(item.expense for item in months)
    lines = [
        f"📊 <b>Отчёт за {year} год</b>",
        "",
        f"Доход: <b>{format_rub(income)} ₽</b>",
        f"Расход: <b>{format_rub(expense)} ₽</b>",
        f"Остаток: <b>{format_rub(income - expense)} ₽</b>",
    ]
    for item in months:
        if not item.count:
            continue
        lines.append(
            f"• {month_label(item.month)} — расход "
            f"{format_rub(item.expense)} ₽, доход {format_rub(item.income)} ₽"
        )
    return "\n".join(lines)


def _category_lines(summary: MonthSummary) -> list[str]:
    if not summary.expense_categories:
        return []
    lines = ["", "<b>Расходы по категориям</b>"]
    total = summary.expense or 1.0
    for category, amount in summary.expense_categories[:10]:
        share = amount / total * 100
        lines.append(
            f"• {html.escape(category)} — {format_rub(amount)} ₽ ({share:.0f}%)"
        )
    hidden = len(summary.expense_categories) - 10
    if hidden > 0:
        lines.append(f"…и ещё {hidden}")
    return lines


async def _read_money(services: Services) -> list[dict]:
    return await read_money(services)

async def _edit(
    message: Message, text: str, markup: InlineKeyboardMarkup | None
) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramAPIError:
        pass


def _parse_month(value: str) -> str | None:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        return None
    if parsed.year < 2000 or parsed.year > 2100:
        return None
    return parsed.strftime("%Y-%m")


def _seconds_until_month_start(hhmm: str, tz: timezone) -> float:
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now(tz)
    target = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return max(1.0, (target - now).total_seconds())
