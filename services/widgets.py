"""HTML-виджет для /report: один пузырь с графиком, без Mini App."""

from __future__ import annotations

import html
import zlib
from dataclasses import dataclass, field

import httpx

from .money import MonthSummary, format_rub, month_label, summarize

WIDGET_URL = "https://api.telegram.org/bot{token}/sendWidget"
WIDGET_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_COMPRESSED = 4096
MAX_CATEGORIES = 6
MAX_TASKS = 6

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


def build_today_widget() -> str:
    """Оболочка виджета «Сегодня»; данные приходят в TelegramWidget.chatData."""
    markup = r"""
<div id="w" class="w"></div>
<script>
const root = document.getElementById('w');
let last = null;
let open = null;
function esc(v) { const d = document.createElement('div'); d.textContent = String(v ?? ''); return d.innerHTML; }
function render(force) {
  let s = {};
  const raw = TelegramWidget.chatData;
  if (!raw) {
    root.textContent = 'Загрузка…';
    return;
  }
  if (!force && raw === last) return;
  if (raw !== last) open = null;
  last = raw;
  if (typeof raw === 'object') {
    s = raw;
  } else {
    try { s = JSON.parse(raw); } catch (e) { return; }
  }
  let h = '<div class="stats">';
  h += '<div><span>Задач</span><b>' + (s.o || 0) + '</b></div>';
  h += '<div><span>Просрочено</span><b>' + (s.ov || 0) + '</b></div>';
  h += '<div><span>На сегодня</span><b>' + (s.du || 0) + '</b></div>';
  h += '<div><span>Инбокс</span><b>' + (s.in || 0) + '</b></div></div>';
  h += '<div class="date">Заметок сегодня: ' + (s.n || 0) + (s.m ? ' \u00b7 ' + esc(s.m) : '') + '</div><div class="tasks">';
  const tasks = s.t || [];
  if (tasks.length) {
    for (const t of tasks) {
      h += '<div class="task"><span class="i">' + esc(t.k || '\u2022') + '</span><span class="x">' + esc(t.x) + '</span>';
      if (t.d) h += '<span class="d">' + esc(t.d) + '</span>';
      if (t.i) h += '<button class="b" data-act="done" data-id="' + esc(t.i) + '">\u2713</button>';
      if (t.i) h += '<button class="b more" data-act="open" data-id="' + esc(t.i) + '">\u22ef</button>';
      h += '</div>';
      if (t.i && open === t.i) {
        h += '<div class="acts">';
        h += '<button class="b" data-act="due" data-id="' + esc(t.i) + '" data-mode="tomorrow">Завтра</button>';
        h += '<button class="b" data-act="due" data-id="' + esc(t.i) + '" data-mode="plus3">+3 дня</button>';
        h += '<button class="b" data-act="due" data-id="' + esc(t.i) + '" data-mode="clear">Без даты</button>';
        h += '</div>';
      }
    }
  } else {
    h += '<div class="empty">Открытых задач нет.</div>';
  }
  h += '</div>';
  const off = s.off || 0;
  const total = s.tot || tasks.length;
  if (off > 0 || off + tasks.length < total) {
    h += '<div class="pager">';
    if (off > 0) h += '<button class="b" data-act="prev" data-off="' + Math.max(0, off - 5) + '">\u2190 Назад</button>';
    if (off + tasks.length < total) h += '<button class="b" data-act="more" data-off="' + (off + tasks.length) + '">Ещё \u2192</button>';
    h += '</div>';
  }
  root.innerHTML = h;
}
root.addEventListener('click', (e) => {
  const el = e.target;
  if (!el || !el.dataset) return;
  const act = el.dataset.act;
  if (!act) return;
  if (act === 'open') {
    open = open === el.dataset.id ? null : el.dataset.id;
    render(true);
    return;
  }
  let data = null;
  if (act === 'done') data = 'done:' + el.dataset.id;
  else if (act === 'due') data = 'due:' + el.dataset.id + ':' + el.dataset.mode;
  else if (act === 'more') data = 'more:' + el.dataset.off;
  else if (act === 'prev') data = 'prev:' + el.dataset.off;
  if (!data) return;
  el.disabled = true;
  TelegramWidget.request(data).catch(() => { el.disabled = false; });
});
try { TelegramWidget.onEvent('chatDataChanged', () => render(false)); } catch (e) {}
render(false);
setInterval(() => render(false), 1500);
</script>
<style>
.w{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}
.stats{display:flex;gap:10px;margin-bottom:8px}
.stats div{flex:1}
.stats span{display:block;color:var(--tg-theme-hint-color);font-size:11px}
.date{font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:10px}
.task{display:flex;align-items:center;gap:6px;margin:5px 0}
.i{width:16px}
.x{flex:1;font-size:13px}
.d{font-size:11px;color:var(--tg-theme-hint-color)}
.b{border:0;border-radius:6px;padding:3px 8px;background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color);font-size:12px}
.b.more{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-hint-color);padding:3px 7px}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 8px 22px}
.acts .b{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:11px}
.pager{display:flex;gap:6px;margin-top:10px}
.pager .b{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:11px}
.empty{font-size:13px;color:var(--tg-theme-hint-color)}
</style>
"""
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


@dataclass(slots=True)
class WeeklyReview:
    period: str
    notes_week: int
    tasks_done: int
    tasks_open: int
    overdue: int
    inbox: int
    inbox_stale: int
    expense: float
    income: float
    prev_expense: float
    prev_income: float
    projects_idle: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return any(
            (
                self.notes_week,
                self.tasks_done,
                self.tasks_open,
                self.inbox,
                self.expense,
                self.income,
            )
        )


def build_weekly_widget(review: WeeklyReview) -> str:
    money_parts: list[str] = []
    if review.expense:
        money_parts.append(f"−{format_rub(review.expense)} ₽")
    if review.income:
        money_parts.append(f"+{format_rub(review.income)} ₽")
    money = " · ".join(money_parts) or "нет трат"

    comparison = ""
    if review.prev_expense > 0:
        delta = (review.expense - review.prev_expense) / review.prev_expense * 100
        sign = "−" if delta < 0 else "+"
        comparison = (
            f'<div class="muted">Расход к прошлой неделе: '
            f"{sign}{abs(delta):.0f}%</div>"
        )

    extra: list[str] = []
    if review.inbox_stale:
        extra.append(
            f'<div class="muted">В инбоксе старше недели: '
            f"<b>{review.inbox_stale}</b></div>"
        )
    if review.projects_idle:
        names = ", ".join(html.escape(name) for name in review.projects_idle[:4])
        extra.append(f'<div class="muted">Без движения: {names}</div>')

    markup = f"""
<div class="w">
  <div class="stats">
    <div><span>Заметок</span><b>{review.notes_week}</b></div>
    <div><span>Закрыто</span><b>{review.tasks_done}</b></div>
    <div><span>Открыто</span><b>{review.tasks_open}</b></div>
    <div><span>Инбокс</span><b>{review.inbox}</b></div>
  </div>
  <div class="money">Деньги: <b>{money}</b></div>
  {comparison}
  {''.join(extra)}
</div>
<style>
.w{{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}}
.stats{{display:flex;gap:10px;margin-bottom:10px}}
.stats div{{flex:1}}
.stats span{{display:block;color:var(--tg-theme-hint-color);font-size:11px}}
.money{{font-size:13px;margin-bottom:4px}}
.muted{{font-size:12px;color:var(--tg-theme-hint-color);margin:3px 0}}
</style>
"""
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


def weekly_caption(review: WeeklyReview) -> str:
    return f"🗓 Итоги недели · {review.period}"


def report_caption(month: str) -> str:
    return f"📊 Отчёт за {month_label(month)}"


def build_report_shell() -> str:
    """Оболочка отчёта: периоды и данные переключаются через chatData."""
    markup = r"""
<div id="w" class="w"></div>
<script>
const MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const root = document.getElementById('w');
let last = null;
function esc(v) { const d = document.createElement('div'); d.textContent = String(v ?? ''); return d.innerHTML; }
function money(v) { return Math.round(Number(v) || 0).toLocaleString('ru-RU') + ' ₽'; }
function btn(label, data, cls) {
  return '<button class="b ' + (cls || '') + '" data-d="' + esc(data) + '">' + esc(label) + '</button>';
}
function render() {
  const raw = TelegramWidget.chatData;
  if (!raw) {
    root.textContent = 'Загрузка…';
    return;
  }
  if (raw === last) return;
  last = raw;
  let s = {};
  if (typeof raw === 'object') s = raw;
  else { try { s = JSON.parse(raw); } catch (e) { return; } }

  const kind = s.k || 'm';
  const active = s.a || '';
  let h = '<div class="hdr">' + esc(s.t || '') + '</div>';

  if (kind !== 'l') {
    h += '<div class="tot">';
    h += '<div><span>Доход</span><b>' + money(s.i) + '</b></div>';
    h += '<div><span>Расход</span><b>' + money(s.e) + '</b></div>';
    h += '<div><span>Остаток</span><b>' + money(s.b) + '</b></div>';
    h += '</div>';
    const rows = s.r || [];
    if (rows.length) {
      h += '<div class="bars">';
      for (const r of rows) {
        h += '<div class="row"><span class="n">' + esc(r[0]) + '</span>';
        h += '<span class="t"><i style="width:' + (Number(r[2]) || 0) + '%"></i></span>';
        h += '<span class="v">' + money(r[1]) + '</span></div>';
      }
      h += '</div>';
    } else {
      h += '<div class="empty">Записей нет.</div>';
    }
  }

  h += '<div class="nav">';
  h += btn('Текущий', 'report:current', active === 'current' ? 'on' : '');
  h += btn('Прошлый', 'report:prev', active === 'prev' ? 'on' : '');
  h += btn('Месяц', 'report:months:' + (s.y || ''), active === 'month' ? 'on' : '');
  h += btn('Год', 'report:year:' + (s.y || ''), active === 'year' ? 'on' : '');
  h += '</div>';

  if (kind === 'l') {
    const d = s.d || '000000000000';
    h += '<div class="months">';
    for (let m = 0; m < 12; m++) {
      const mm = ('0' + (m + 1)).slice(-2);
      h += '<button class="b ' + (d.charAt(m) === '1' ? '' : 'off') + '" data-d="report:mon:' + s.y + '-' + mm + '">' + MONTHS[m] + '</button>';
    }
    h += '</div>';
  }
  if (kind === 'm' && s.v) {
    h += '<div class="nav">' + btn('‹', 'report:mp:' + s.v) + btn('›', 'report:mn:' + s.v) + '</div>';
  }
  if (kind === 'y' && s.y) {
    h += '<div class="nav">' + btn('‹ ' + (s.y - 1), 'report:yp:' + s.y) + btn((s.y + 1) + ' ›', 'report:yn:' + s.y) + '</div>';
  }

  root.innerHTML = h;
}
root.addEventListener('click', (e) => {
  const d = e.target && e.target.dataset ? e.target.dataset.d : null;
  if (!d) return;
  e.target.disabled = true;
  TelegramWidget.request(d).catch(() => { e.target.disabled = false; });
});
try { TelegramWidget.onEvent('chatDataChanged', render); } catch (e) {}
render();
setInterval(render, 1500);
</script>
<style>
.w{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}
.hdr{font-size:13px;font-weight:600;margin-bottom:8px}
.tot{display:flex;gap:10px;margin-bottom:10px}
.tot div{flex:1}
.tot span{display:block;color:var(--tg-theme-hint-color);font-size:11px}
.tot b{font-size:13px}
.row{display:flex;align-items:center;gap:8px;margin:5px 0}
.n{width:88px;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.t{flex:1;height:8px;border-radius:4px;background:var(--tg-theme-secondary-bg-color);overflow:hidden}
.t i{display:block;height:100%;border-radius:4px;background:var(--tg-theme-button-color)}
.v{width:78px;text-align:right;font-size:11px;color:var(--tg-theme-hint-color)}
.empty{color:var(--tg-theme-hint-color);font-size:13px;margin-bottom:10px}
.nav{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.months{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.b{border:0;border-radius:6px;padding:4px 8px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:12px}
.b.on{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
.b.off{opacity:.45}
</style>
"""
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


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
    reply_markup: dict | None = None,
    allow_queries: bool = False,
    chat_data: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[bool, str]:
    """Отправляет виджет сырым Bot API. Возвращает (успех, причина ошибки)."""
    payload: dict = {"chat_id": chat_id, "html": markup, "caption": caption}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if allow_queries:
        payload["allow_queries"] = True
    if chat_data is not None:
        payload["chat_data"] = chat_data
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
