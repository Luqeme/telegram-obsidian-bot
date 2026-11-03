"""Тесты транслитерации и имён файлов."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.note_builder import make_filename, slugify

TZ = ZoneInfo("Asia/Yekaterinburg")


def test_transliterates_russian_title() -> None:
    assert (
        slugify("Рефакторинг авторизации на JWT", max_len=60)
        == "refaktoring-avtorizacii-na-jwt"
    )


def test_handles_yo_y_and_shch() -> None:
    assert slugify("Ёжик, йод и щи") == "ezhik-yod-i-shchi"


def test_keeps_latin_and_digits() -> None:
    assert slugify("JWT / OAuth 2.0") == "jwt-oauth-2-0"


def test_falls_back_to_note() -> None:
    assert slugify("🎙️🔥") == "note"
    assert slugify("   ") == "note"


def test_truncates_to_limit_without_trailing_dash() -> None:
    slug = slugify("Рефакторинг авторизации на JWT")
    assert len(slug) <= 30
    assert not slug.endswith("-")
    assert "--" not in slug


def test_no_leading_dash_from_punctuation() -> None:
    assert slugify("...привет!!!") == "privet"


def test_make_filename_uses_local_time() -> None:
    moment = datetime(2026, 11, 3, 14, 30, 5, tzinfo=TZ)
    name = make_filename("Тестовая заметка", moment)
    assert name.startswith("2026-11-03_14-30-05_")
    assert name.endswith(".md")
    assert name == "2026-11-03_14-30-05_testovaya-zametka.md"
