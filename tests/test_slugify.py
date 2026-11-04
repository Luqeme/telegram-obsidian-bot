"""Тесты транслитерации и имён файлов."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.note_builder import MAX_SLUG_LEN, make_filename, slugify

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
    assert len(slug) <= MAX_SLUG_LEN
    assert not slug.endswith("-")
    assert "--" not in slug


def test_cyrillic_mode_keeps_russian() -> None:
    assert slugify("Оплатить интернет", transliterate=False) == "оплатить-интернет"


def test_cyrillic_mode_keeps_latin_terms() -> None:
    assert slugify("JWT и пет-проект", transliterate=False) == "jwt-и-пет-проект"


def test_cyrillic_mode_strips_punctuation() -> None:
    assert slugify("«Завтра»: купить хлеб!", transliterate=False) == "завтра-купить-хлеб"


def test_cyrillic_mode_truncates() -> None:
    slug = slugify("Очень длинный заголовок заметки про важные дела", transliterate=False)
    assert len(slug) <= MAX_SLUG_LEN
    assert not slug.endswith("-")


def test_cyrillic_filename() -> None:
    moment = datetime(2026, 11, 4, 1, 37, 0, tzinfo=TZ)
    name = make_filename("Заехать купить молоко", moment, transliterate=False)
    assert name == "Заехать купить молоко 2026-11-04.md"


def test_human_name_strips_forbidden_chars() -> None:
    moment = datetime(2026, 11, 4, 1, 37, 0, tzinfo=TZ)
    name = make_filename('Планы: что делать? "срочно"', moment, transliterate=False)
    assert name == "Планы что делать срочно 2026-11-04.md"


def test_no_leading_dash_from_punctuation() -> None:
    assert slugify("...привет!!!") == "privet"


def test_make_filename_uses_local_time() -> None:
    moment = datetime(2026, 11, 3, 14, 30, 5, tzinfo=TZ)
    name = make_filename("Тестовая заметка", moment)
    assert name == "testovaya-zametka 2026-11-03.md"
