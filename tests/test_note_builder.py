"""Тесты сборки Markdown-заметки. Сеть не используется."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

from services.note_builder import (
    NoteDraft,
    build_markdown,
    normalize_tags,
    sanitize_tag,
)

TZ = ZoneInfo("Asia/Yekaterinburg")
NOW = datetime(2026, 11, 3, 14, 30, 5, tzinfo=TZ)

ORIGINAL = (
    "Слушай, надо не забыть в четверг оплатить интернет, "
    "а ещё я подумал, что можно в пет-проекте переписать авторизацию на JWT."
)


def make_draft(**overrides):
    payload = dict(
        is_meaningful=True,
        title="Рефакторинг авторизации на JWT",
        category="Задача",
        tags=["backend", "пет-проект"],
        summary="Нужно отказаться от сессий в пользу JWT.",
        tasks=["Изучить PyJWT", "Оплатить интернет в четверг"],
    )
    payload.update(overrides)
    return NoteDraft(**payload)


def parse_frontmatter(markdown: str) -> dict:
    _, raw, _ = markdown.split("---", 2)
    return yaml.safe_load(raw)


def test_frontmatter_is_valid_yaml() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    front = parse_frontmatter(markdown)

    # YAML парсит ISO-дату в datetime — именно этого ждёт Dataview
    assert front["created"] == datetime(2026, 11, 3, 14, 30, 5)
    assert front["type"] == "inbox-voice"
    assert front["category"] == "Задача"
    assert front["tags"] == ["backend", "пет-проект"]
    assert front["status"] == "inbox"
    assert front["source"] == "telegram"


def test_text_source_marks_type() -> None:
    markdown = build_markdown(make_draft(), "текст заметки", "text", NOW)
    assert parse_frontmatter(markdown)["type"] == "inbox-text"


def test_title_is_rendered_as_h1() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    assert "\n# Рефакторинг авторизации на JWT\n" in markdown


def test_summary_section_present() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    assert "## 💡 Суть" in markdown
    assert "Нужно отказаться от сессий в пользу JWT." in markdown


def test_tasks_rendered_as_checkboxes() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    assert "## 📋 Задачи" in markdown
    assert "- [ ] Изучить PyJWT" in markdown
    assert "- [ ] Оплатить интернет в четверг" in markdown


def test_tasks_section_omitted_when_empty() -> None:
    markdown = build_markdown(make_draft(tasks=[]), ORIGINAL, "voice", NOW)
    assert "📋 Задачи" not in markdown
    assert "Задач не обнаружено" not in markdown


def test_original_text_is_verbatim() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    assert ORIGINAL in markdown


def test_multiline_original_is_quoted() -> None:
    original = "первая строка\nвторая строка\n\nпосле пустой"
    markdown = build_markdown(make_draft(), original, "text", NOW)

    tail = markdown.split("**Оригинал:**", 1)[1]
    quoted = [line for line in tail.splitlines() if line.strip()]
    assert quoted[0] == "> первая строка"
    assert quoted[1] == "> вторая строка"


def test_file_ends_with_single_newline() -> None:
    markdown = build_markdown(make_draft(), ORIGINAL, "voice", NOW)
    assert markdown.endswith("\n")
    assert not markdown.endswith("\n\n")


def test_tags_are_sanitized_and_deduplicated() -> None:
    assert sanitize_tag("#Backend") == "backend"
    assert sanitize_tag("пет проект") == "пет-проект"
    assert sanitize_tag("  #AI!! ") == "ai"
    assert normalize_tags(["backend", "Backend", "#backend", "", "JWT"]) == [
        "backend",
        "jwt",
    ]


def test_numeric_tag_is_quoted_in_yaml() -> None:
    markdown = build_markdown(make_draft(tags=["2026"]), ORIGINAL, "voice", NOW)
    assert parse_frontmatter(markdown)["tags"] == ["2026"]


def test_no_tasks_key_when_llm_says_not_meaningful() -> None:
    draft = make_draft(is_meaningful=False, tasks=[])
    assert draft.is_meaningful is False
