"""Загрузка и валидация конфигурации из .env.

Все ошибки конфигурации должны проявляться на старте, а не в рантайме:
бот, который поднялся с пустым белым списком или битым репозиторием,
опаснее, чем бот, который не запустился.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def parse_user_ids(raw: str) -> frozenset[int]:
    """Разбирает строку вида "12345678,87654321" в набор id."""
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            raise ValueError(
                f"ALLOWED_TELEGRAM_USERS: ожидаются числовые id через запятую, "
                f"получено {chunk!r}"
            )
        ids.add(int(chunk))
    return frozenset(ids)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────
    telegram_bot_token: str
    allowed_telegram_users: str

    # ── Groq ──────────────────────────────────────────────────
    groq_api_key: str
    groq_stt_model: str = "whisper-large-v3"
    groq_llm_model: str = "openai/gpt-oss-120b"

    # ── GitHub ────────────────────────────────────────────────
    github_token: str
    github_repo: str
    github_branch: str = "main"
    obsidian_inbox_dir: str = "00_Inbox"

    # ── Прочее ────────────────────────────────────────────────
    timezone: str = "Asia/Yekaterinburg"
    log_level: str = "INFO"
    max_audio_mb: int = Field(default=20, ge=1, le=100)
    filename_transliterate: bool = True

    # ── Валидаторы ────────────────────────────────────────────

    @field_validator("telegram_bot_token", "groq_api_key", "github_token")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("значение не заполнено")
        return value

    @field_validator("github_repo")
    @classmethod
    def _check_repo(cls, value: str) -> str:
        value = value.strip().strip("/")
        if value.count("/") != 1:
            raise ValueError("ожидается формат owner/repo, например your-username/your-vault")
        owner, repo = value.split("/")
        if not owner or not repo or " " in value:
            raise ValueError("ожидается формат owner/repo, например your-username/your-vault")
        return value

    @field_validator("obsidian_inbox_dir")
    @classmethod
    def _clean_inbox_dir(cls, value: str) -> str:
        value = value.strip().strip("/").strip()
        return value or "00_Inbox"

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"неизвестная таймзона {value!r}, например Asia/Yekaterinburg"
            ) from None
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in LOG_LEVELS:
            raise ValueError(f"допустимо: {', '.join(sorted(LOG_LEVELS))}")
        return value

    @model_validator(mode="after")
    def _require_whitelist(self) -> "Settings":
        if not self.allowed_user_ids:
            raise ValueError(
                "ALLOWED_TELEGRAM_USERS пуст: без белого списка бот не запускается"
            )
        return self

    # ── Производные значения ─────────────────────────────────

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        return parse_user_ids(self.allowed_telegram_users)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def placeholder_problems(self) -> list[str]:
        """Значения, которые остались от .env.example."""
        problems: list[str] = []
        secrets = {
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "GROQ_API_KEY": self.groq_api_key,
            "GITHUB_TOKEN": self.github_token,
        }
        for name, value in secrets.items():
            lowered = value.lower()
            if "your_" in lowered or "xxxx" in lowered or "123456789:abc" in lowered:
                problems.append(f"{name} всё ещё содержит заглушку из .env.example")
        if self.github_repo.startswith("username/"):
            problems.append("GITHUB_REPO всё ещё содержит заглушку из .env.example")
        if self.allowed_telegram_users.strip() in {
            "123456789",
            "123456789,987654321",
        }:
            problems.append(
                "ALLOWED_TELEGRAM_USERS всё ещё содержит заглушку из .env.example"
            )
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
