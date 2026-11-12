"""Главное меню бота: одно место со всеми действиями."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MENU_ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    (("🔎 Найти", "menu:find"), ("💬 Спросить", "menu:ask")),
    (("📅 Сегодня", "menu:today"), ("💰 Деньги", "menu:money")),
    (("📊 Отчёт", "menu:report"), ("🏠 Дома", "menu:home")),
    (("📥 Инбокс", "menu:inbox"), ("🚀 Проекты", "menu:projects")),
    (("↩️ Отменить", "menu:undo"), ("❓ Помощь", "menu:help")),
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text, callback_data=data)
                for text, data in row
            ]
            for row in MENU_ROWS
        ]
    )
