"""Тесты конвертера Markdown в HTML для Telegram."""

from __future__ import annotations

from handlers.base import _markdown_to_html


def test_bold_is_converted() -> None:
    assert _markdown_to_html("Заметка **«Дашборд»** важна") == "Заметка <b>«Дашборд»</b> важна"


def test_html_is_escaped() -> None:
    assert _markdown_to_html("<script>") == "&lt;script&gt;"


def test_headings_become_bold() -> None:
    assert _markdown_to_html("### Итог\nтекст") == "<b>Итог</b>\nтекст"


def test_bullets_are_normalized() -> None:
    assert _markdown_to_html("- пункт") == "• пункт"


def test_extra_blank_lines_collapse() -> None:
    assert _markdown_to_html("а\n\n\n\nб") == "а\n\nб"


def test_plain_text_untouched() -> None:
    assert _markdown_to_html("просто текст") == "просто текст"
