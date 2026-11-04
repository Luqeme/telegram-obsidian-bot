"""Тесты вспомогательных функций: медиа, расписание, здоровье."""

from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from handlers.health import _seconds_until_weekday
from handlers.notes import _media_info

TZ = ZoneInfo("Asia/Yekaterinburg")


def _message(**kwargs):
    fields = {"voice": None, "video_note": None, "audio": None, "document": None}
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def test_voice_media() -> None:
    message = _message(
        voice=SimpleNamespace(file_id="v1", file_size=100, duration=5)
    )
    assert _media_info(message) == ("v1", 100, 5, "voice.ogg")


def test_video_note_media() -> None:
    message = _message(
        video_note=SimpleNamespace(file_id="n1", file_size=200, duration=10)
    )
    assert _media_info(message) == ("n1", 200, 10, "note.mp4")


def test_audio_file_media() -> None:
    message = _message(
        audio=SimpleNamespace(
            file_id="a1", file_size=300, duration=60, file_name="talk.mp3"
        )
    )
    assert _media_info(message) == ("a1", 300, 60, "talk.mp3")


def test_audio_document_media() -> None:
    message = _message(
        document=SimpleNamespace(
            file_id="d1",
            file_size=400,
            file_name="record.ogg",
            mime_type="application/octet-stream",
        )
    )
    assert _media_info(message) == ("d1", 400, 0, "record.ogg")


def test_plain_document_is_ignored() -> None:
    message = _message(
        document=SimpleNamespace(
            file_id="d2", file_size=10, file_name="report.pdf", mime_type="application/pdf"
        )
    )
    assert _media_info(message) is None


def test_seconds_until_weekday_is_within_a_week() -> None:
    delay = _seconds_until_weekday("10:00", 6, TZ)
    assert 0 < delay <= 7 * 86400
