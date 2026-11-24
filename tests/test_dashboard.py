"""Тесты дашборда: проверка initData, порядок задач, сборка денег."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import date
from urllib.parse import urlencode

import pytest

from dashboard.auth import InitDataError, verify_init_data
from dashboard.data import Dashboard, order_tasks, task_view
from services.money import parse_rows

TOKEN = "123456:TESTTOKEN"
OWNER = 4242


def sign(fields: dict[str, str], token: str = TOKEN) -> str:
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields = dict(fields)
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def make(user_id: int = OWNER, *, age: int = 0) -> str:
    return sign(
        {
            "auth_date": str(int(time.time()) - age),
            "query_id": "AAA",
            "user": json.dumps({"id": user_id}),
        }
    )


def test_valid_init_data_passes() -> None:
    payload = verify_init_data(make(), TOKEN)
    assert payload["user"]["id"] == OWNER


def test_tampered_hash_rejected() -> None:
    raw = make().replace("hash=", "hash=0")
    with pytest.raises(InitDataError):
        verify_init_data(raw, TOKEN)


def test_wrong_token_rejected() -> None:
    with pytest.raises(InitDataError):
        verify_init_data(make(), "999:OTHER")


def test_expired_rejected() -> None:
    with pytest.raises(InitDataError):
        verify_init_data(make(age=90_000), TOKEN)


def test_empty_rejected() -> None:
    with pytest.raises(InitDataError):
        verify_init_data("", TOKEN)


class FakeTask:
    def __init__(self, text: str, due: str) -> None:
        self.text = text
        self.due = due


def test_order_tasks_puts_overdue_first() -> None:
    today = date(2026, 11, 24)
    tasks = [
        FakeTask("позже", "2026-12-01"),
        FakeTask("без срока", ""),
        FakeTask("просрочено", "2026-11-20"),
        FakeTask("сегодня", "2026-11-24"),
    ]
    assert [t.text for t in order_tasks(tasks, today)] == [
        "просрочено",
        "сегодня",
        "позже",
        "без срока",
    ]


def test_task_view_labels() -> None:
    today = date(2026, 11, 24)
    assert task_view(FakeTask("x", "2026-11-23"), today)["state"] == "overdue"
    assert task_view(FakeTask("x", "2026-11-24"), today)["label"] == "сегодня"
    assert task_view(FakeTask("x", "2026-11-27"), today)["label"] == "пт"
    assert task_view(FakeTask("x", "2026-12-15"), today)["label"] == "15.12"
    assert task_view(FakeTask("x", "мусор"), today)["label"] == ""


CSV = """date,kind,amount,category,note
2026-11-24,expense,500,Еда,обед
2026-11-01,expense,1000,Еда,
2026-10-31,expense,999,Еда,прошлый месяц
2026-11-02,income,3000,Зарплата,
"""


class FakeGithub:
    async def get_text(self, path: str) -> str:
        return CSV


class FakeIndex:
    async def notes(self):
        return []

    async def open_tasks(self):
        return [FakeTask("Задача", "2026-11-30")]

    async def money_budgets(self):
        return {"Еда": 8000}


class FakeSettings:
    """Ровно те поля, которые нужны Dashboard."""

    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Yekaterinburg")
    obsidian_inbox_dir = "00_Inbox"


def run(coro):
    return asyncio.run(coro)


def test_payload_aggregates_month() -> None:
    dash = Dashboard(FakeSettings(), FakeGithub(), FakeIndex())
    data = run(dash.payload())

    assert data["money"]["expense"] == 1500
    assert data["money"]["income"] == 3000
    assert data["money"]["balance"] == 1500
    assert data["money"]["daily"][0] == 1000
    assert data["money"]["daily"][23] == 500
    assert len(data["money"]["daily"]) == 30

    budget = data["money"]["budgets"][0]
    assert budget["name"] == "Еда"
    assert budget["spent"] == 1500
    assert budget["pct"] == 19
    assert budget["over"] is False


def test_payload_marks_overrun() -> None:
    class TinyBudget(FakeIndex):
        async def money_budgets(self):
            return {"Еда": 1000}

    dash = Dashboard(FakeSettings(), FakeGithub(), TinyBudget())
    budget = run(dash.payload())["money"]["budgets"][0]
    assert budget["over"] is True
    assert budget["left"] == -500
    assert budget["pct"] == 150


def test_rows_parse_helper_matches_csv() -> None:
    rows = parse_rows(CSV)
    assert len(rows) == 4
