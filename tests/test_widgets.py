"""Тесты HTML-виджета отчёта и отправки через Bot API."""

from __future__ import annotations

import asyncio

import httpx

from services.money import summarize
from services.widgets import (
    MAX_COMPRESSED,
    WeeklyReview,
    build_report_shell,
    build_report_widget,
    build_today_widget,
    build_weekly_widget,
    build_year_widget,
    compressed_size,
    report_caption,
    send_widget,
    weekly_caption,
    year_caption,
)

ROWS = [
    {
        "date": "2026-10-01",
        "kind": "income",
        "amount": "90000",
        "category": "Зарплата",
        "note": "Октябрь",
    },
    {
        "date": "2026-10-02",
        "kind": "expense",
        "amount": "25000",
        "category": "Аренда",
        "note": "Квартира",
    },
    {
        "date": "2026-10-03",
        "kind": "expense",
        "amount": "2000",
        "category": "Еда",
        "note": "Продукты",
    },
]


def test_widget_contains_totals_and_categories() -> None:
    summary = summarize(ROWS, "2026-10")
    markup = build_report_widget(summary, "2026-10")

    assert "90 000" in markup
    assert "27 000" in markup
    assert "Аренда" in markup
    assert "Еда" in markup
    assert 'class="t"' in markup


def test_widget_fits_telegram_limit() -> None:
    summary = summarize(ROWS, "2026-10")
    markup = build_report_widget(summary, "2026-10")

    assert markup
    assert compressed_size(markup) <= MAX_COMPRESSED


def test_widget_escapes_category() -> None:
    rows = [
        {
            "date": "2026-10-01",
            "kind": "expense",
            "amount": "100",
            "category": "<b>злые</b>",
            "note": "",
        }
    ]
    markup = build_report_widget(summarize(rows, "2026-10"), "2026-10")

    assert "&lt;b&gt;злые&lt;/b&gt;" in markup
    assert "<b>злые</b>" not in markup


def test_today_widget_shell_reads_chat_data() -> None:
    markup = build_today_widget()

    assert markup
    assert "TelegramWidget.chatData" in markup
    assert "chatDataChanged" in markup
    assert "data = 'done:' + el.dataset.id" in markup
    assert "data-act=\"due\"" in markup
    assert "data-act=\"more\"" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED


def test_today_widget_script_has_no_python_artifacts() -> None:
    import re

    markup = build_today_widget()
    script = re.search(r"<script>(.*?)</script>", markup, re.S)
    assert script is not None

    code = script.group(1)
    assert "function render(" in code
    assert not re.search(r"^\s*def\s+\w+\s*\(", code, re.M)


def test_today_state_payload() -> None:
    from types import SimpleNamespace

    from handlers.digest import build_today_state

    overdue = SimpleNamespace(
        id="a1",
        raw="Просроченная задача",
        text="Просроченная задача",
        due="2026-11-10",
    )
    due_today = SimpleNamespace(
        id="b2", raw="Купить молоко ⏳ 2026-11-13", text="Купить молоко", due="2026-11-13"
    )
    plain = SimpleNamespace(id="c3", raw="Позвонить", text="Позвонить", due="")

    state = build_today_state(
        {
            "today_notes": [1, 2],
            "inbox": [1, 2, 3],
            "tasks": [overdue, due_today, plain],
            "ordered": [overdue, due_today, plain],
            "overdue": [overdue],
            "due_today": [due_today],
            "expense": 540,
            "income": 0,
            "truncated": None,
        }
    )

    assert state["n"] == 2
    assert state["in"] == 3
    assert state["o"] == 3
    assert state["ov"] == 1
    assert state["du"] == 1
    assert "540" in state["m"]
    assert [task["i"] for task in state["t"]] == ["a1", "b2", "c3"]
    assert [task["k"] for task in state["t"]] == ["⏳", "📅", "•"]
    assert state["t"][1]["d"] == "13.11"


def test_today_state_pages_tasks() -> None:
    from types import SimpleNamespace

    from handlers.digest import build_today_state

    tasks = [
        SimpleNamespace(id=f"id{index}", raw=f"Задача {index}", text=f"Задача {index}", due="")
        for index in range(7)
    ]
    data = {
        "today_notes": [],
        "inbox": [],
        "tasks": tasks,
        "ordered": tasks,
        "overdue": [],
        "due_today": [],
        "expense": 0,
        "income": 0,
        "truncated": None,
    }

    first = build_today_state(data)
    assert first["off"] == 0
    assert first["tot"] == 7
    assert [task["i"] for task in first["t"]] == [f"id{index}" for index in range(5)]

    second = build_today_state(data, 5)
    assert second["off"] == 5
    assert [task["i"] for task in second["t"]] == ["id5", "id6"]

    reset = build_today_state(data, 99)
    assert reset["off"] == 0


def test_today_state_fits_chat_data_limit() -> None:
    from types import SimpleNamespace

    from handlers.digest import CHAT_DATA_LIMIT, build_today_state, dumps_state

    tasks = [
        SimpleNamespace(
            id=f"id{index}",
            raw="Очень длинная задача " * 5,
            text="Очень длинная задача " * 5,
            due="",
        )
        for index in range(6)
    ]

    state = build_today_state(
        {
            "today_notes": [],
            "inbox": [],
            "tasks": tasks,
            "ordered": tasks,
            "overdue": [],
            "due_today": [],
            "expense": 0,
            "income": 0,
            "truncated": None,
        }
    )

    assert len(dumps_state(state).encode("utf-8")) <= CHAT_DATA_LIMIT
    assert len(state["t"]) < len(tasks)
    assert all(len(task["x"]) <= 42 for task in state["t"])


def test_weekly_widget_contains_review() -> None:
    review = WeeklyReview(
        period="06.11–12.11",
        notes_week=3,
        tasks_done=5,
        tasks_open=2,
        overdue=1,
        inbox=4,
        inbox_stale=1,
        expense=1000,
        income=2000,
        prev_expense=500,
        prev_income=0,
        projects_idle=["Дашборд"],
    )

    markup = build_weekly_widget(review)

    assert "Заметок" in markup
    assert "Закрыто" in markup
    assert "1 000" in markup
    assert "Дашборд" in markup
    assert "старше недели" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED
    assert weekly_caption(review) == "🗓 Итоги недели · 06.11–12.11"


def test_today_widget_shell_requests_done() -> None:
    markup = build_today_widget()

    assert "TelegramWidget.request(data)" in markup


def test_year_widget_contains_months_and_fits() -> None:
    markup = build_year_widget(ROWS, 2026)

    assert markup
    assert "окт" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED
    assert year_caption(2026) == "📊 Отчёт за 2026 год"


def test_year_widget_empty_year() -> None:
    assert build_year_widget(ROWS, 2025) == ""


def test_report_shell_is_stateful_and_fits() -> None:
    import re

    markup = build_report_shell()

    assert markup
    assert "TelegramWidget.chatData" in markup
    assert "chatDataChanged" in markup
    assert "report:current" in markup
    assert "report:months:" in markup
    assert 'request(d)' in markup
    assert compressed_size(markup) <= MAX_COMPRESSED

    script = re.search(r"<script>(.*?)</script>", markup, re.S)
    assert script is not None
    assert not re.search(r"^\s*def\s+\w+\s*\(", script.group(1), re.M)


def test_report_month_state() -> None:
    from datetime import datetime, timezone

    from handlers.report import report_state

    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    state = report_state(ROWS, "current", now)

    assert state["k"] == "m"
    assert state["v"] == "2026-10"
    assert state["i"] == 90000
    assert state["e"] == 27000
    assert state["b"] == 63000
    assert state["a"] == "current"
    assert state["r"][0] == ["Аренда", 25000, 93]


def test_report_state_navigation() -> None:
    from datetime import datetime, timezone

    from handlers.report import report_state

    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    prev = report_state(ROWS, "prev", now)
    assert prev["v"] == "2026-10"
    assert prev["a"] == "prev"

    old = report_state(ROWS, "mon:2026-09", now)
    assert old["v"] == "2026-09"
    assert old["a"] == "month"
    assert old["e"] == 0

    assert report_state(ROWS, "mp:2026-01", now)["v"] == "2025-12"
    assert report_state(ROWS, "mn:2026-12", now)["v"] == "2027-01"


def test_report_year_and_months_states() -> None:
    from datetime import datetime, timezone

    from handlers.report import report_state

    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    year = report_state(ROWS, "year:2026", now)
    assert year["k"] == "y"
    assert year["y"] == 2026
    assert year["e"] == 27000
    assert year["a"] == "year"
    assert [row[0] for row in year["r"]] == ["окт"]
    assert report_state(ROWS, "yp:2026", now)["y"] == 2025
    assert report_state(ROWS, "yn:2026", now)["y"] == 2027

    months = report_state(ROWS, "months:2026", now)
    assert months["k"] == "l"
    assert months["y"] == 2026
    assert months["d"] == "000000000100"
    assert months["a"] == "month"


def test_report_state_fits_chat_data_limit() -> None:
    from datetime import datetime, timezone

    from handlers.report import REPORT_STATE_LIMIT, dumps_report_state, report_state

    rows = [
        {
            "date": "2026-10-01",
            "kind": "expense",
            "amount": "1000",
            "category": f"Очень длинная категория {index}",
            "note": "",
        }
        for index in range(8)
    ]
    state = report_state(rows, "mon:2026-10", datetime(2026, 11, 1, tzinfo=timezone.utc))
    payload = dumps_report_state(state)

    assert len(payload.encode("utf-8")) <= REPORT_STATE_LIMIT
    assert len(state["r"]) < 8


def test_caption_is_short() -> None:
    caption = report_caption("2026-10")

    assert caption == "📊 Отчёт за октябрь 2026"


def test_send_widget_payload() -> None:
    import json

    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> tuple[bool, str]:
        try:
            return await send_widget(
                "token",
                42,
                "<div>hi</div>",
                "caption",
                reply_markup={"inline_keyboard": [[{"text": "x", "callback_data": "t:1"}]]},
                allow_queries=True,
                chat_data='{"o":1}',
                client=client,
            )
        finally:
            await client.aclose()

    ok, reason = asyncio.run(run())
    assert ok is True
    assert reason == ""
    assert requests and requests[0].url.path.endswith("/sendWidget")
    payload = json.loads(requests[0].content)
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "t:1"
    assert payload["allow_queries"] is True
    assert payload["chat_data"] == '{"o":1}'


def test_send_widget_reports_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "bad"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> tuple[bool, str]:
        try:
            return await send_widget("token", 42, "<div>hi</div>", "cap", client=client)
        finally:
            await client.aclose()

    ok, reason = asyncio.run(run())
    assert ok is False
    assert "400" in reason
