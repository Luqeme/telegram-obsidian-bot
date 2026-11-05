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


def test_task_text_strips_metadata() -> None:
    from services.notes_index import task_text

    assert task_text("Оплатить интернет 📅 2026-11-06 ⏫") == "Оплатить интернет"
    assert task_text("Позвонить ✅ 2026-11-04") == "Позвонить"


def test_task_due_extracted() -> None:
    from services.notes_index import task_due

    assert task_due("Купить хлеб 📅 2026-11-05 🔼") == "2026-11-05"
    assert task_due("Без срока") == ""


def test_task_id_depends_on_path() -> None:
    from services.notes_index import task_id

    assert task_id("a.md", "текст") != task_id("b.md", "текст")
    assert task_id("a.md", "текст") == task_id("a.md", "текст")


def test_seconds_until_is_within_a_day() -> None:
    from zoneinfo import ZoneInfo

    from handlers.digest import _seconds_until

    delay = _seconds_until("00:00", ZoneInfo("Asia/Yekaterinburg"))
    assert 0 < delay <= 86400


def test_search_understands_question_phrasing() -> None:
    import asyncio

    from services.notes_index import NotesIndex

    async def run() -> list[str]:
        index = NotesIndex(github=None)  # type: ignore[arg-type]
        index._notes = [parse_note("10_Notes/Дашборд 2026-11-04.md", SAMPLE)]
        index._loaded_at = asyncio.get_running_loop().time()
        found = await index.search("что я писал про дашборд")
        return [note.title for note in found]

    titles = asyncio.run(run())
    assert titles == ["Работа над внешним видом дашборда"]


def test_search_ignores_stopwords_only() -> None:
    import asyncio

    from services.notes_index import NotesIndex

    async def run() -> int:
        index = NotesIndex(github=None)  # type: ignore[arg-type]
        index._notes = [parse_note("10_Notes/Дашборд 2026-11-04.md", SAMPLE)]
        index._loaded_at = asyncio.get_running_loop().time()
        return len(await index.search("что я писал"))

    assert asyncio.run(run()) == 0


def test_reads_note_type() -> None:
    note = parse_note("20_Projects/Бот.md", '---\ntype: project\ntitle: "Бот"\n---\n\n# Бот\n')
    assert note.note_type == "project"


def test_index_skips_project_hubs() -> None:
    import asyncio

    from services.notes_index import NotesIndex

    class FakeGitHub:
        async def list_markdown_blobs(self) -> list[tuple[str, str]]:
            return [
                ("20_Projects/Бот.md", "hub"),
                ("99_Templates/Проект.md", "template"),
                ("10_Notes/Note.md", "note"),
            ]

        async def get_text(self, path: str) -> str:
            if path.endswith("Бот.md"):
                return '---\ntype: project\ntitle: "Бот"\n---\n\n# Бот\n'
            if path.endswith("Проект.md"):
                return '---\ntype: project-template\ntitle: "Шаблон"\n---\n\n# Шаблон\n'
            return SAMPLE

    async def run() -> list[str]:
        index = NotesIndex(FakeGitHub())  # type: ignore[arg-type]
        return [note.title for note in await index.notes()]

    assert asyncio.run(run()) == ["Работа над внешним видом дашборда"]
