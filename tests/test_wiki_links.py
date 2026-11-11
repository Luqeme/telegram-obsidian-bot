"""Тесты подстановки ссылок на существующие заметки."""

from __future__ import annotations

from services.note_builder import wiki_link

TARGETS = [
    ("Дашборд 2026-11-04", "Дашборд"),
    ("Проект Х 2026-11-04", "Проект Х"),
]


def test_links_existing_title() -> None:
    linked = wiki_link("Надо обновить дашборд и добавить график.", TARGETS)
    assert "[[Дашборд 2026-11-04|Дашборд]]" in linked


def test_does_not_invent_links() -> None:
    linked = wiki_link("Ничего про проекты тут нет.", TARGETS)
    assert "[[" not in linked


def test_does_not_link_twice() -> None:
    linked = wiki_link("Дашборд и ещё раз дашборд.", TARGETS)
    assert linked.count("[[Дашборд 2026-11-04|Дашборд]]") == 1


def test_ignores_short_titles() -> None:
    linked = wiki_link("Это про ИИ и всё.", [("ИИ 2026-11-04", "ИИ")])
    assert "[[" not in linked


def test_empty_input_is_safe() -> None:
    assert wiki_link("", TARGETS) == ""
    assert wiki_link("текст", []) == "текст"


def test_does_not_break_words() -> None:
    """Ссылка не должна вставляться внутрь слова: «молокозавод» ≠ «молоко»."""
    linked = wiki_link("Построили молокозавод.", [("Молоко 2026-11-04", "Молоко")])
    assert linked == "Построили молокозавод."


def test_links_standalone_word() -> None:
    linked = wiki_link("Купил молоко.", [("Молоко 2026-11-04", "Молоко")])
    assert "[[Молоко 2026-11-04|Молоко]]" in linked


def test_links_word_before_punctuation() -> None:
    linked = wiki_link("Нужен дашборд, срочно.", TARGETS)
    assert "[[Дашборд 2026-11-04|Дашборд]]," in linked
