"""HTML-виджеты: оболочки, общий JS и отправка через Bot API."""

from __future__ import annotations

import html
import zlib
from dataclasses import dataclass, field

import httpx

from .money import format_rub

WIDGET_URL = "https://api.telegram.org/bot{token}/sendWidget"
WIDGET_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_COMPRESSED = 4096

# Общие функции для всех виджетов. Держим в одном месте, чтобы не расходились.
WIDGET_JS = r"""
function esc(v) {
  const d = document.createElement('div');
  d.textContent = String(v ?? '');
  return d.innerHTML;
}
function attr(v) { return esc(v).replace(/"/g, '&quot;'); }
function num(v) { return Math.round(Number(v) || 0).toLocaleString('ru-RU'); }
function money(v) { return num(v) + ' ₽'; }
function chip(label, data, cls) {
  return '<button class="b ' + (cls || '') + '" data-d="' + attr(data) + '">' + esc(label) + '</button>';
}
function bind(root) {
  root.addEventListener('click', (e) => {
    const el = e.target;
    const request = el && el.dataset ? el.dataset.d : null;
    if (!request) return;
    el.disabled = true;
    TelegramWidget.request(request).catch(() => { el.disabled = false; });
  });
}
function start(render) {
  try { TelegramWidget.onEvent('chatDataChanged', () => render(false)); } catch (e) {}
  render(false);
  setInterval(() => { if (!document.hidden) render(false); }, 3000);
}
""".strip()


def compressed_size(markup: str) -> int:
    return len(zlib.compress(markup.encode("utf-8"), 9))


def _shell(script: str, style: str) -> str:
    markup = (
        '<div id="w" class="w"></div>\n'
        f"<script>\n{WIDGET_JS}\n{script.strip()}\n</script>\n"
        f"<style>\n{style.strip()}\n</style>\n"
    )
    if compressed_size(markup) > MAX_COMPRESSED:
        return ""
    return markup


TODAY_JS = r"""
const root = document.getElementById('w');
let last = null;
let open = null;
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
  if (typeof raw === 'object') s = raw;
  else { try { s = JSON.parse(raw); } catch (e) { return; } }

  let h = '<div class="stats">';
  h += '<div><span>Задач</span><b>' + (s.o || 0) + '</b></div>';
  h += '<div><span>Просрочено</span><b>' + (s.ov || 0) + '</b></div>';
  h += '<div><span>На сегодня</span><b>' + (s.du || 0) + '</b></div>';
  h += '<div><span>Инбокс</span><b>' + (s.in || 0) + '</b></div></div>';
  h += '<div class="date">Заметок сегодня: ' + (s.n || 0) + (s.m ? ' · ' + esc(s.m) : '') + '</div>';
  h += '<div class="tasks">';

  const tasks = s.t || [];
  if (tasks.length) {
    for (const t of tasks) {
      h += '<div class="task"><span class="i">' + esc(t.k || '•') + '</span>';
      h += '<span class="x">' + esc(t.x) + '</span>';
      if (t.d) h += '<span class="d">' + esc(t.d) + '</span>';
      if (t.i) {
        h += chip('✓', 'done:' + t.i);
        h += '<button class="b more" data-open="' + attr(t.i) + '">⋯</button>';
      }
      h += '</div>';
      if (t.i && open === t.i) {
        h += '<div class="acts">';
        h += chip('Завтра', 'due:' + t.i + ':tomorrow');
        h += chip('+3 дня', 'due:' + t.i + ':plus3');
        h += chip('Без даты', 'due:' + t.i + ':clear');
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
    if (off > 0) h += chip('← Назад', 'prev:' + Math.max(0, off - 5));
    if (off + tasks.length < total) h += chip('Ещё →', 'more:' + (off + tasks.length));
    h += '</div>';
  }
  root.innerHTML = h;
}
root.addEventListener('click', (e) => {
  const el = e.target;
  if (!el || !el.dataset || !el.dataset.open) return;
  open = open === el.dataset.open ? null : el.dataset.open;
  render(true);
});
bind(root);
start(render);
"""

TODAY_CSS = """
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
.acts .b,.pager .b{background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:11px}
.pager{display:flex;gap:6px;margin-top:10px}
.empty{font-size:13px;color:var(--tg-theme-hint-color)}
"""


def build_today_widget() -> str:
    """Оболочка виджета «Сегодня»; данные приходят в TelegramWidget.chatData."""
    return _shell(TODAY_JS, TODAY_CSS)


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


SPEND_JS = r"""
const root = document.getElementById('w');
let last = null;
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

  const income = s.g === 1;
  let h = '<div class="hdr">' + (income ? 'Доход' : 'Расход');
  if (s.t) h += ' · сегодня ' + money(s.t);
  h += '</div>';
  h += '<div class="sum' + (income ? ' in' : '') + '">' + (income ? '+' : '−') + money(s.a) + '</div>';
  if (s.n) h += '<div class="note">' + esc(s.n) + '</div>';

  if (s.s === 'off') {
    h += '<div class="off">Отменено</div>';
    root.innerHTML = h;
    return;
  }

  if (s.lim) {
    const spent = Number(s.sp) || 0;
    const pct = Math.round(spent / s.lim * 100);
    const left = s.lim - spent;
    const tone = pct > 100 ? ' over' : pct >= 80 ? ' warn' : '';
    h += '<div class="bud">';
    h += '<div class="bl">' + esc(s.c) + ': ' + num(spent) + ' из ' + num(s.lim) + '</div>';
    h += '<span class="t"><i class="' + tone + '" style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></span>';
    h += '<div class="bl">' + (left >= 0 ? 'осталось ' + num(left) + ' ₽' : 'перерасход ' + num(-left) + ' ₽') + (pct >= 80 ? ' · ' + pct + '%' : '') + '</div>';
    h += '</div>';
  }

  if (s.k && s.k.length) {
    h += '<div class="chips">';
    for (const c of s.k) h += chip(c, 'cat:' + s.a + ':' + s.h + ':' + c, c === s.c ? 'on' : '');
    h += '</div>';
  }
  h += '<div class="row"><button class="b del" data-d="' + attr('undo:' + s.a + ':' + s.h) + '">Отменить</button></div>';
  root.innerHTML = h;
}
bind(root);
start(render);
"""

SPEND_CSS = """
.w{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}
.hdr{font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:4px}
.sum{font-size:22px;font-weight:600;margin-bottom:2px}
.sum.in{color:#31a24c}
.note{font-size:13px;color:var(--tg-theme-hint-color);margin-bottom:10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.b{border:0;border-radius:8px;padding:5px 9px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:12px}
.b.on{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
.row{display:flex;gap:6px}
.b.del{background:transparent;color:var(--tg-theme-destructive-text-color);border:1px solid var(--tg-theme-secondary-bg-color);font-size:11px}
.off{font-size:13px;color:var(--tg-theme-hint-color);margin-top:6px}
.bud{margin-bottom:10px}
.bl{font-size:11px;color:var(--tg-theme-hint-color);margin:2px 0}
.t{display:block;height:6px;border-radius:3px;background:var(--tg-theme-secondary-bg-color);overflow:hidden}
.t i{display:block;height:100%;border-radius:3px;background:var(--tg-theme-button-color)}
.t i.over{background:#e5534b}
.t i.warn{background:#f0a020}
"""


def build_spend_widget() -> str:
    """Оболочка виджета траты: категории, бюджет и отмена в сообщении."""
    return _shell(SPEND_JS, SPEND_CSS)


REPORT_JS = r"""
const MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const root = document.getElementById('w');
let last = null;
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
    let ok = 0, warn = 0, over = 0;
    for (const r of rows) {
      const lim = Number(r[3]) || 0;
      if (!lim) continue;
      const p = Number(r[2]) || 0;
      if (p > 100) over += 1;
      else if (p >= 80) warn += 1;
      else ok += 1;
    }
    if (ok + warn + over) {
      h += '<div class="bud">Бюджеты: ' + ok + ' в норме';
      if (warn) h += ' · ' + warn + ' на пределе';
      if (over) h += ' · ' + over + ' перерасход';
      h += '</div>';
    }

    if (rows.length) {
      h += '<div class="bars">';
      for (const r of rows) {
        const lim = Number(r[3]) || 0;
        const pct = Number(r[2]) || 0;
        const width = Math.max(0, Math.min(100, pct));
        const tone = lim ? (pct > 100 ? ' over' : pct >= 80 ? ' warn' : '') : '';
        h += '<div class="row"><span class="n">' + esc(r[0]) + '</span>';
        h += '<span class="t"><i class="' + tone + '" style="width:' + width + '%"></i></span>';
        h += '<span class="v">' + num(r[1]) + (lim ? ' / ' + num(lim) : ' ₽') + '</span></div>';
      }
      h += '</div>';
    } else {
      h += '<div class="empty">Записей нет.</div>';
    }
  }

  h += '<div class="nav">';
  h += chip('Текущий', 'report:current', active === 'current' ? 'on' : '');
  h += chip('Прошлый', 'report:prev', active === 'prev' ? 'on' : '');
  h += chip('Месяц', 'report:months:' + (s.y || ''), active === 'month' ? 'on' : '');
  h += '</div>';

  if (kind === 'l') {
    const d = s.d || '000000000000';
    h += '<div class="months">';
    for (let m = 0; m < 12; m++) {
      const mm = ('0' + (m + 1)).slice(-2);
      h += chip(MONTHS[m], 'report:mon:' + s.y + '-' + mm, d.charAt(m) === '1' ? '' : 'off');
    }
    h += '</div>';
  }
  if (kind === 'm' && s.v) {
    h += '<div class="nav">' + chip('‹', 'report:mp:' + s.v) + chip('›', 'report:mn:' + s.v) + '</div>';
  }

  root.innerHTML = h;
}
bind(root);
start(render);
"""

REPORT_CSS = """
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
.t i.over{background:#e5534b}
.t i.warn{background:#f0a020}
.v{width:96px;text-align:right;font-size:10px;color:var(--tg-theme-hint-color)}
.bud{font-size:11px;color:var(--tg-theme-hint-color);margin-bottom:8px}
.empty{color:var(--tg-theme-hint-color);font-size:13px;margin-bottom:10px}
.nav{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.months{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.b{border:0;border-radius:6px;padding:4px 8px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:12px}
.b.on{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}
.b.off{opacity:.45}
"""


def build_report_shell() -> str:
    """Оболочка отчёта: периоды и данные переключаются через chatData."""
    return _shell(REPORT_JS, REPORT_CSS)


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
