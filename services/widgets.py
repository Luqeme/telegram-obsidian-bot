"""HTML-виджет для /report: один пузырь с графиком, без Mini App."""

from __future__ import annotations

import html
import zlib

import httpx

from .money import MonthSummary, format_rub, month_label, summarize

WIDGET_URL = "https://api.telegram.org/bot{token}/sendWidget"
WIDGET_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_COMPRESSED = 4096
MAX_CATEGORIES = 6
MONTH_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def compressed_size(markup: str) -> int:
    return len(zlib.compress(markup.encode("utf-8"), 9))


def build_report_widget(summary: MonthSummary, month: str) -> str:
    """HTML виджета. Пустая строка, если не влез в лимит Telegram."""
    total = summary.expense or 1.0
    bars: list[str] = []
    for category, amount in summary.expense_categories[:MAX_CATEGORIES]:
        share = amount / total * 100
        bars.append(
            '<div class="r"><span class="n">'
            f"{html.escape(category)}</span><span class=\"t\"><i style=\"width:{share:.0f}%\">"
            f'</i></span><span class="v">{format_rub(amount)}</span></div>'
        )
    if not bars:
        bars.append('<div class="empty">Расходов нет.</div>')

    markup = f"""
<div class="w">
  <div class="totals">
    <div><span>Доход</span><b>{format_rub(summary.income)} ₽</b></div>
    <div><span>Расход</span><b>{format_rub(summary.expense)} ₽</b></div>
    <div><span>Остаток</span><b>{format_rub(summary.balance)} ₽</b></div>
  </div>
  <div class="bars">{''.join(bars)}</div>
</div>
<style>
.w{{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}}
.totals{{display:flex;gap:10px;margin-bottom:12px}}
.totals div{{flex:1}}
.totals span{{display:block;color:var(--tg-theme-hint-color);font-size:12px}}
.r{{display:flex;align-items:center;gap:8px;margin:6px 0}}
.n{{width:88px;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.t{{flex:1;height:8px;border-radius:4px;background:var(--tg-theme-secondary-bg-color);overflow:hidden}}
.t i{{display:block;height:100%;border-radius:4px;background:var(--tg-theme-button-color)}}
.v{{width:68px;text-align:right;font-size:12px;color:var(--tg-theme-hint-color)}}
.empty{{color:var(--tg-theme-hint-color);font-size:13px}}
</style>
"""
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


def report_caption(month: str) -> str:
    return f"📊 Отчёт за {month_label(month)}"


def build_year_widget(rows: list[dict], year: int) -> str:
    """Годовой виджет: 12 месяцев, полоски расходов."""
    months = [summarize(rows, f"{year}-{number:02d}") for number in range(1, 13)]
    income = sum(item.income for item in months)
    expense = sum(item.expense for item in months)
    balance = income - expense
    if not any(item.count for item in months):
        return ""

    maximum = max((item.expense for item in months), default=0.0) or 1.0
    bars: list[str] = []
    for label, item in zip(MONTH_SHORT, months):
        share = item.expense / maximum * 100
        bars.append(
            f'<div class="r"><span class="n">{label}</span>'
            f'<span class="t"><i style="width:{share:.0f}%"></i></span>'
            f'<span class="v">{format_rub(item.expense)}</span></div>'
        )

    markup = f"""
<div class="w">
  <div class="totals">
    <div><span>Доход</span><b>{format_rub(income)} ₽</b></div>
    <div><span>Расход</span><b>{format_rub(expense)} ₽</b></div>
    <div><span>Остаток</span><b>{format_rub(balance)} ₽</b></div>
  </div>
  <div class="bars">{''.join(bars)}</div>
</div>
<style>
.w{{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}}
.totals{{display:flex;gap:10px;margin-bottom:12px}}
.totals div{{flex:1}}
.totals span{{display:block;color:var(--tg-theme-hint-color);font-size:12px}}
.r{{display:flex;align-items:center;gap:8px;margin:4px 0}}
.n{{width:34px;font-size:12px;color:var(--tg-theme-hint-color)}}
.t{{flex:1;height:7px;border-radius:4px;background:var(--tg-theme-secondary-bg-color);overflow:hidden}}
.t i{{display:block;height:100%;border-radius:4px;background:var(--tg-theme-button-color)}}
.v{{width:68px;text-align:right;font-size:12px;color:var(--tg-theme-hint-color)}}
</style>
"""
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


def year_caption(year: int) -> str:
    return f"📊 Отчёт за {year} год"


async def send_widget(
    token: str,
    chat_id: int,
    markup: str,
    caption: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[bool, str]:
    """Отправляет виджет сырым Bot API. Возвращает (успех, причина ошибки)."""
    payload = {"chat_id": chat_id, "html": markup, "caption": caption}
    own = client is None
    client = client or httpx.AsyncClient(timeout=WIDGET_TIMEOUT)
    try:
        response = await client.post(
            WIDGET_URL.format(token=token), json=payload, timeout=WIDGET_TIMEOUT
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 200 and data.get("ok"):
            return True, ""
        return False, f"HTTP {response.status_code}: {data.get('description', '')}"
    except httpx.HTTPError as exc:
        return False, repr(exc)
    finally:
        if own:
            await client.aclose()
