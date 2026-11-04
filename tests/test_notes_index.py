"""Тесты разбора заметок для индекса."""

from __future__ import annotations

from datetime import datetime, timezone

from services.notes_index import parse_note

SAMPLE = """---
created: 2026-11-04T12:34:00
title: "Работа над внешним видом дашборда"
type: inbox-voice
category: Задача
tags:
  - дашборд
  - внешний-вид
status: inbox
source: telegram
---

# Работа над внешним видом дашборда

## 💡 Суть
Собрать красивый дашборд.

## 📋 Задачи
- [ ] Сделать графики
- [ ] Убрать лишнее
- [x] Сделать заготовку

---
> 🎙 **Оригинал:**
> текст
"""


def test_parses_frontmatter() -> None:
    note = parse_note("10_Notes/Работа 2026-11-04.md", SAMPLE)

    assert note.title == "Работа над внешним видом дашборда"
    assert note.category == "Задача"
    assert note.tags == ("дашборд", "внешний-вид")
    assert note.created == datetime(2026, 11, 4, 12, 34, tzinfo=timezone.utc)


def test_collects_only_open_tasks() -> None:
    note = parse_note("10_Notes/x.md", SAMPLE)
    assert note.tasks == ("Сделать графики", "Убрать лишнее")


def test_falls_back_to_heading() -> None:
    raw = "---\ncreated: 2026-11-04T10:00:00\n---\n\n# Заголовок из H1\n\nтекст"
    note = parse_note("00_Inbox/x.md", raw)
    assert note.title == "Заголовок из H1"
    assert note.tags == ()


def test_survives_broken_frontmatter() -> None:
    raw = "---\ntitle: [не закрыт\n---\n\n# Резерв\n"
    note = parse_note("00_Inbox/x.md", raw)
    assert note.title  # не падаем, берём хоть что-то


def test_stem_and_folder() -> None:
    note = parse_note("20_Projects/Заметка 2026-11-04.md", "---\ntitle: x\n---\n")
    assert note.stem == "Заметка 2026-11-04"
    assert note.folder == "20_Projects"
