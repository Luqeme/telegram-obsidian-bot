"""Главное меню бота: одно место со всеми действиями."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

MENU_ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    (("🔎 Найти", "menu:find"), ("💬 Спросить", "menu:ask")),
    (("📅 Сегодня", "menu:today"), ("📊 Отчёт", "menu:report")),
    (("🏠 Дома", "menu:home"), ("📥 Инбокс", "menu:inbox")),
    (("🚀 Проекты", "menu:projects"), ("↩️ Отменить", "menu:undo")),
    (("❓ Помощь", "menu:help"),),
)


def main_menu(dashboard_url: str = "") -> InlineKeyboardMarkup:
    """Кнопка дашборда добавляется, только если адрес задан в .env."""
    rows = [
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in MENU_ROWS
    ]
    if dashboard_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📊 Дашборд",
                    web_app=WebAppInfo(url=dashboard_url),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
