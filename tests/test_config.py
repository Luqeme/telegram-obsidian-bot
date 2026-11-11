"""Тесты конфигурации: всё должно падать на старте, а не в рантайме."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Settings, parse_user_ids

BASE = {
    "telegram_bot_token": "123456789:AAExampleTokenValue",
    "allowed_telegram_users": "111,222",
    "groq_api_key": "gsk_example",
    "github_token": "github_pat_example",
    "github_repo": "owner/repo",
}


def make_settings(**overrides: object) -> Settings:
    values = dict(BASE)
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_valid_settings() -> None:
    settings = make_settings()

    assert settings.allowed_user_ids == frozenset({111, 222})
    assert settings.obsidian_inbox_dir == "00_Inbox"
    assert settings.github_branch == "main"


def test_empty_whitelist_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(allowed_telegram_users="")


def test_non_numeric_whitelist_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(allowed_telegram_users="111,admin")


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(timezone="Mars/Olympus")


def test_repo_without_owner_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(github_repo="obsidian-vault")


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(groq_api_key="   ")


def test_inbox_dir_defaults_when_blank() -> None:
    assert make_settings(obsidian_inbox_dir="  ").obsidian_inbox_dir == "00_Inbox"


def test_digest_time_is_normalized() -> None:
    assert make_settings(digest_time="9:05").digest_time == "09:05"
    assert make_settings(digest_time="").digest_time == ""


def test_invalid_digest_time_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(digest_time="25:00")


def test_parse_user_ids_accepts_separators() -> None:
    assert parse_user_ids("1, 2;3") == frozenset({1, 2, 3})
    assert parse_user_ids("  ") == frozenset()


def test_placeholders_are_detected() -> None:
    settings = make_settings(
        telegram_bot_token="123456789:abc",
        groq_api_key="gsk_xxxxxxxxxxxx",
        github_repo="username/my-vault",
    )

    problems = settings.placeholder_problems()

    assert any("TELEGRAM_BOT_TOKEN" in item for item in problems)
    assert any("GROQ_API_KEY" in item for item in problems)
    assert any("GITHUB_REPO" in item for item in problems)


def test_real_values_have_no_placeholder_problems() -> None:
    assert make_settings().placeholder_problems() == []
