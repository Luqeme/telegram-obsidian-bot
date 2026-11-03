"""Тесты ограничений на голосовые сообщения."""

from __future__ import annotations

from handlers.notes import MAX_AUDIO_SECONDS, check_voice_limits

LIMIT_MB = 20


def test_normal_voice_is_allowed() -> None:
    assert check_voice_limits(size=1_000_000, duration=30, limit_mb=LIMIT_MB) is None


def test_exact_limits_are_allowed() -> None:
    assert (
        check_voice_limits(
            size=LIMIT_MB * 1024 * 1024,
            duration=MAX_AUDIO_SECONDS,
            limit_mb=LIMIT_MB,
        )
        is None
    )


def test_too_large_is_rejected() -> None:
    reason = check_voice_limits(
        size=LIMIT_MB * 1024 * 1024 + 1, duration=30, limit_mb=LIMIT_MB
    )
    assert reason is not None
    assert "МБ" in reason


def test_too_long_is_rejected() -> None:
    reason = check_voice_limits(
        size=1000, duration=MAX_AUDIO_SECONDS + 1, limit_mb=LIMIT_MB
    )
    assert reason is not None
    assert "мин" in reason


def test_card_has_no_github_link() -> None:
    from services.note_builder import NoteDraft

    from handlers.notes import _render_card

    draft = NoteDraft(
        is_meaningful=True,
        title="Тест",
        category="Мысль",
        tags=["тест"],
        summary="Проверка карточки.",
    )
    card = _render_card("00_Inbox/2026-11-04_00-00-00_test.md", draft)
    assert "github.com" not in card
    assert "00_Inbox/2026-11-04_00-00-00_test.md" in card
