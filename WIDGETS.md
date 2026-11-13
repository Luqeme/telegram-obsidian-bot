# Виджеты и кнопки внутри них

Практическая инструкция: как устроены HTML-виджеты в этом боте, как добавить
новый виджет или кнопку и на какие грабли мы уже наступали.

Всё проверено на живой Bot API 10.4 и телефоне (Android) в ноябре 2026.

---

## 1. Что такое виджет

Виджет — это сообщение, внутри которого Telegram рисует **ваш HTML** и выполняет
**ваш JavaScript** в песочнице QuickJS. Это не Mini App: нет сети, нет WebView,
нет ввода текста. Зато есть состояние, которое пишет бот, и запросы от кнопок.

Схема работы:

```
бот: sendWidget(html, chat_data)  →  сообщение с виджетом
виджет: TelegramWidget.chatData    →  рисует себя
юзер: тап по кнопке
виджет: TelegramWidget.request("done:abc")
        ↓
Telegram присылает боту update widget_query
        ↓
бот: answerWidgetQuery() + editMessageWidgetData(new chat_data)
        ↓
виджет: событие chatDataChanged → перерисовка на месте
```

Ключевое: **HTML после отправки не меняется никогда**. Меняется только
состояние (`chat_data`). Всё, что должно измениться, рисуется из состояния.

---

## 2. Ограничения, которые определяют дизайн

| Что | Лимит | Следствие |
|---|---|---|
| HTML | 32 768 байт, ≤ 4096 после zlib 9 | держим оболочку маленькой |
| `chat_data` | 1024 байта UTF-8 | состояние — короткие ключи, обрезка |
| Запрос из виджета | 64 байта | в запрос кладём id/индекс, не текст |
| Ввод текста | нет | числа и текст приходят из сообщения/голоса |
| Сеть | нет | данные считает бот и присылает готовыми |
| Библиотеки | нет | только свой JS/SVG/CSS |
| Прокрутка | нет | всё должно влезать в высоту 50–600 px |
| Запросы | только по тапу* | *один запрос при появлении виджета на экране, дальше не чаще раза в 5 с |
| Чаты | только личка с ботом | в группах виджет не отправится, нужен текстовый fallback |
| `protected content` | всегда | скриншоты на телефоне заблокированы, это не баг |

Что поддерживается из HTML/CSS/JS: div/span/p/ul/table/details/button, inline SVG,
flex/grid, CSS-переменные темы, `innerHTML`, `addEventListener`, `dataset`,
`setInterval`, `Intl`, `localStorage`. Шрифты — только системные.

Чего нет: `input/select/textarea`, внешние `<script src>`, `fetch`,
`window.open`, `alert`, `onclick="..."` в атрибуте (см. грабли).

---

## 3. Шим для aiogram

aiogram 3.31 не знает тип `widget_query`. Шим живёт в
`services/widget_shim.py` и делает три вещи:

1. Патчит `Update.event_type` / `Update.event` — только для поля `widget_query`.
2. Добавляет observer `widget_query` в диспетчер.
3. Даёт две функции: `answer_widget_query()` и `edit_widget_data()`.

Подключение — `bot.py`:

```python
from handlers import widgets as widget_handlers
from services.widget_shim import install_widget_shim

widget_observer = install_widget_shim(dispatcher)
widget_observer.register(widget_handlers.on_widget_query)

allowed_updates = dispatcher.resolve_used_update_types()
if "widget_query" not in allowed_updates:
    allowed_updates.append("widget_query")
await dispatcher.start_polling(bot, allowed_updates=allowed_updates)
```

Когда aiogram добавит `widget_query` официально — шим удалить, оставить только
`register` на штатном observer и вызовы `answer`/`edit`.

`WidgetQuery` — pydantic-модель с полями `id`, `from_user` (alias `from`),
`data`, `chat`, `message_id`, `widget_id`.

---

## 4. Отправка виджета

```python
from services.widgets import send_widget

ok, reason = await send_widget(
    services.settings.telegram_bot_token,
    chat_id,
    build_my_widget(),          # HTML
    "Подпись сообщения",         # caption
    allow_queries=True,          # без этого кнопки не пришлют widget_query
    chat_data=json.dumps(state, ensure_ascii=False),
)
if not ok:
    logger.warning("my_widget: %s", reason)
    await bot.send_message(chat_id, text_fallback)   # обязательный fallback
```

`send_widget` — сырой HTTP `POST /sendWidget` (httpx), потому что в Bot API
этого метода нет в aiogram. Возвращает `(успех, причина)`.

Правила:

- всегда `allow_queries=True`, если внутри есть кнопки;
- всегда текстовый fallback: старый клиент, группа, ошибка API;
- `chat_data` — строка JSON, не объект;
- подпись (`caption`) после отправки менять нельзя, но её можно
  отредактировать через `editMessageCaption`, если очень надо.

---

## 5. Состояние и обновление

```python
from services.widget_shim import edit_widget_data

await edit_widget_data(
    token,
    query.chat.id,
    query.message_id,
    json.dumps(state, ensure_ascii=False),
)
```

- Передавать только изменившиеся поля **нельзя** — бот не читает текущее
  состояние. Каждый раз отправляем полное.
- Пустая строка очищает состояние; виджет увидит `null`.
- Размер проверять до отправки. В проекте есть готовые `dumps_*` функции,
  которые подрезают список, пока не влезет в 1024 байта.

Пример подсчёта:

```python
payload = json.dumps(state, ensure_ascii=False)
while state["t"] and len(payload.encode("utf-8")) > 1024:
    state["t"].pop()
    payload = json.dumps(state, ensure_ascii=False)
```

Схемы, которые уже используются:

- `/today`: `{n,in,o,ov,du,m,t[],off,tot}` — счётчики, задачи, страница;
- трата: `{a,g,c,n,h,k[],t,s,lim,sp}` — сумма, категория, хеш, чипы, бюджет;
- `/report`: `{k,v,y,t,i,e,b,r[][],a,d}` — вид, месяц, суммы, строки, флаги.

Ключи короткие не для красоты: 1024 байта — это ~400 символов кириллицы.

---

## 6. Общий JS

В `services/widgets.py` есть `WIDGET_JS` — один набор функций на все виджеты:

```js
esc(v)            // безопасный текст для innerHTML
attr(v)           // то же, но для значения атрибута
num(v)            // 1234.5 -> "1 234"
money(v)          // "1 234 ₽"
chip(label, data) // <button class="b" data-d="...">label</button>
bind(root)        // один обработчик тапов: берёт data-d и шлёт request
start(render)     // подписка на chatDataChanged + первый рендер
```

Оболочка собирается через `_shell(script, style)`:

```python
def build_my_widget() -> str:
    return _shell(MY_JS, MY_CSS)
```

`_shell` склеивает `<div>`, `<script>` (с `WIDGET_JS` + вашим кодом) и
`<style>`, а также проверяет лимит сжатия (вернёт `""`, если не влезло).

### Скелет нового виджета

```python
MY_JS = r"""
const root = document.getElementById('w');
let last = null;
function render() {
  const raw = TelegramWidget.chatData;
  if (!raw) { root.textContent = 'Загрузка…'; return; }
  if (raw === last) return;         // состояние не менялось
  last = raw;
  let s = {};
  if (typeof raw === 'object') s = raw;
  else { try { s = JSON.parse(raw); } catch (e) { return; } }

  let h = '<div class="hdr">' + esc(s.title || '') + '</div>';
  h += '<div class="row">' + chip('Нажми', 'my:' + s.id) + '</div>';
  root.innerHTML = h;
}
bind(root);
start(render);
"""

MY_CSS = """
.w{font:14px system-ui,sans-serif;color:var(--tg-theme-text-color);padding:4px 2px}
.hdr{font-size:13px;font-weight:600;margin-bottom:8px}
.b{border:0;border-radius:8px;padding:5px 9px;background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color);font-size:12px}
"""


def build_my_widget() -> str:
    return _shell(MY_JS, MY_CSS)
```

### Локальные действия без запроса

Если нажатие меняет только вид (раскрыть строку), не надо ходить к боту:

```js
let open = null;
function render(force) { /* ... */ }
root.addEventListener('click', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.open) return;
  open = open === el.dataset.open ? null : el.dataset.open;
  render(true);              // force — обойти проверку raw === last
});
bind(root);
start(render);
```

Так сделано раскрытие `⋯` в `/today`.

---

## 7. Кнопки и протокол запросов

Кнопка — обычный `<button>` с `data-d`, где лежит строка запроса:

```html
<button class="b" data-d="done:48c8c2">✓</button>
```

`bind(root)` ловит тап, выключает кнопку и вызывает
`TelegramWidget.request(data-d)`. Никаких inline `onclick`.

Правила протокола:

- до 64 байт;
- префикс = тип действия, двоеточия = поля;
- только латиница/цифры/короткие id в полях, текст — в состоянии;
- если данных много (название категории), лучше передавать индекс или хеш.

Уже занятые префиксы (`handlers/widgets.py`):

| Префикс | Что делает |
|---|---|
| `done:<task_id>` | закрыть задачу |
| `due:<task_id>:tomorrow\|plus3\|clear` | перенести/снять дату |
| `more:<offset>` / `prev:<offset>` | листать задачи |
| `cat:<сумма>:<хеш>:<категория>` | сменить категорию траты |
| `undo:<сумма>:<хеш>` | отменить трату |
| `report:<вид>` | переключить период отчёта |

Обработчик — один на всё, в `handlers/widgets.py`:

```python
async def on_widget_query(query: WidgetQuery, services: Services) -> None:
    token = services.settings.telegram_bot_token
    logger.info("widget_query id=%s data=%r", query.id, query.data[:200])
    try:
        if query.from_user.id not in services.settings.allowed_user_ids:
            await answer_widget_query(token, query.id, "denied")
            return

        data = query.data or ""
        if data.startswith("done:"):
            await _close_task(services, token, query, data[5:])
            return
        ...
        await answer_widget_query(token, query.id, "unknown")
    except Exception:
        logger.exception("widget_query не обработан")
        await answer_widget_query(token, query.id, "error")
```

Порядок в любом действии:

1. `answer_widget_query(..., "ok")` — снять «крутилку» с кнопки;
2. сделать работу (GitHub, пересчёт);
3. `edit_widget_data(...)` — перерисовать.

Если строка уже изменилась — отвечаем `"changed"`, ничего не портим. Если
не нашли — `"missing"`.

---

## 8. Как бот находит «свою» строку

Виджет запоминает не саму строку, а её признаки. Это позволяет не хранить
ничего на сервере и переживать рестарт.

Траты: `cat:<сумма>:<hash(note)[:6]>:<категория>`.
Бот читает CSV, идёт с конца и ищет последнюю строку с такой суммой и таким
хешем заметки (`services/money.py: locate_row`).

Задачи: в состоянии лежит `task_id` = sha1(path + raw)[:16]
(`services/notes_index.py: task_id`), по нему `find_task`.

Дата задачи меняется через `with_due(raw, "2026-11-14")` — она аккуратно
убирает старый `📅` и ставит новый.

---

## 9. Добавление новой кнопки: чек-лист

1. Добавить поле в состояние (и обрезку, если это список).
2. В рендере добавить `chip('Текст', 'my:...')`.
3. В `on_widget_query` добавить ветку `data.startswith("my:")`.
4. В обработчике: `answer` → работа → `edit_widget_data`.
5. Написать тест: состояние, ветка обработчика, при необходимости — `node --check`.
6. Проверить в Telegram на телефоне (десктоп может выглядеть иначе).

---

## 10. Тесты

Юнит-тесты состояния и обработчиков — обычный pytest. JS проверяем синтаксически:

```python
import re, pathlib
markup = build_my_widget()
js = re.search(r"<script>(.*?)</script>", markup, re.S).group(1)
pathlib.Path("tmp.js").write_text(js, encoding="utf-8")
# затем: node --check tmp.js
```

В тестах полезно проверять, что в скрипте нет питоновских артефактов:

```python
assert "function render(" in code
assert not re.search(r"^\s*def\s+\w+\s*\(", code, re.M)
```

И что оболочка влезает:

```python
from services.widgets import compressed_size, MAX_COMPRESSED
assert compressed_size(markup) <= MAX_COMPRESSED
```

Живой тест событий (когда непонятно, приходит ли `chatDataChanged`):
отправить виджет, который на событие шлёт `request("probe:evt")`, изменить
`chat_data` через API и посмотреть в лог бота:

```bash
ssh lq.fin "journalctl -u telegram-obsidian-bot --since '-2 min' --no-pager | grep probe:evt"
```

Так мы проверили, что событие доставляется, и убрали таймер-опрос.

---

## 11. Грабли (все проверены на практике)

| Симптом | Причина | Лечение |
|---|---|---|
| Виджет пустой, только подпись | синтаксическая ошибка в JS (`def render()` вместо `function`) | `node --check` перед деплоем |
| Кнопка не реагирует | `onclick="..."` в атрибуте — не выполняется | только `addEventListener`/`bind` из `<script>` |
| Кнопка «залипла» | не вызвали `answerWidgetQuery` | `answer` до тяжёлой работы |
| Виджет не обновился | не пришло событие или состояние не изменилось | проверено: событие приходит; смотреть логи `editMessageWidgetData` |
| `chatData` пустой | `chat_data` не передан или передан объектом | передавать строку JSON |
| Ничего не пришло на кнопку | старый клиент/группа, либо `allow_queries=False` | fallback + `allow_queries=True` |
| Кнопка в меню не работает | сообщение старше 48 ч → `InaccessibleMessage` | обрабатывать до `isinstance(message, Message)`, брать `callback.bot` + `chat.id` |
| Скриншот не делается | виджеты всегда protected content | это не исправить, пока это виджет |
| Виджет «тормозит» | QuickJS-песочница + валидация HTML | не делать виджет там, где хватает текста |

Ещё: `editMessageWidgetData` не умеет менять HTML и подпись — только состояние.
Новый вид — новое сообщение.

---

## 12. Деплой и проверка

```bash
.\.venv\Scripts\python.exe -m pytest -q
git add -A && git commit -m "..." && git push

ssh lq.fin "cd /opt/telegram-obsidian-bot && sudo -u obsidianbot git pull && sudo systemctl restart telegram-obsidian-bot"
ssh lq.fin "journalctl -u telegram-obsidian-bot -n 30 --no-pager"
```

Сервер: `lq.fin`, путь `/opt/telegram-obsidian-bot`, сервис
`telegram-obsidian-bot`, пользователь `obsidianbot`.

Отправить виджет вручную (минуя хендлер) можно скриптом на сервере:
`sendWidget` + `editMessageWidgetData` через httpx, токен из `config.get_settings()`.

---

## 13. Где что лежит

| Файл | Что |
|---|---|
| `services/widget_shim.py` | шим `widget_query`, `answer_widget_query`, `edit_widget_data` |
| `services/widgets.py` | `WIDGET_JS`, оболочки, `send_widget` |
| `handlers/widgets.py` | маршрутизация префиксов, действия |
| `handlers/digest.py` | состояние `/today` |
| `handlers/report.py` | состояние `/report`, виды и бюджеты |
| `handlers/notes.py` | виджет траты, фразы «лимит …» |
| `services/money.py` | состояние траты, поиск строки по хешу, бюджеты |
| `tests/test_widget_shim.py` | шим, роутинг, действия |
| `tests/test_widgets.py` | оболочки, состояния отчёта |
| `tests/test_spend_widget.py` | состояние траты |
| `tests/test_budgets.py` | лимиты и фразы |
