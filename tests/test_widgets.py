"""Тесты HTML-виджета отчёта и отправки через Bot API."""

from __future__ import annotations

import asyncio

import httpx

from services.money import summarize
from services.widgets import (
    MAX_COMPRESSED,
    WeeklyReview,
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
    assert "TelegramWidget.request('done:'" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED


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

    assert "request('done:' + b.dataset.id)" in markup


def test_year_widget_contains_months_and_fits() -> None:
    markup = build_year_widget(ROWS, 2026)

    assert markup
    assert "окт" in markup
    assert compressed_size(markup) <= MAX_COMPRESSED
    assert year_caption(2026) == "📊 Отчёт за 2026 год"


def test_year_widget_empty_year() -> None:
    assert build_year_widget(ROWS, 2025) == ""


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
