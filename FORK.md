# Как развернуть свой экземпляр

Инструкция для того, кто взял этот проект и хочет собрать своего бота. От нуля до рабочей заметки в Obsidian — примерно 20–30 минут.

Проект не привязан ни к чьим аккаунтам: всё личное живёт в `.env`, в коде персональных данных нет.

---

## Шаг 0. Что понадобится

| Что | Зачем | Сколько стоит |
|---|---|---|
| Аккаунт GitHub | хранилище заметок | бесплатно |
| Аккаунт Groq | распознавание речи и LLM | бесплатно (free tier) |
| Telegram | сам бот | бесплатно |
| Python 3.10+ | локальный запуск | — |
| VPS с systemd | работа 24/7 | от ~200 ₽/мес |

Без VPS тоже работает, но бот будет жить только пока включён компьютер.

---

## Шаг 1. Получить код

**Вариант А — форк** (если репозиторий публичный):

GitHub → кнопка **Fork** → Create fork.

**Вариант Б — копия без истории:**

```bash
git clone https://github.com/your-username/telegram-obsidian-bot.git my-bot
cd my-bot
git remote remove origin
```

Вариант Б удобнее, если не хочется тащить чужую историю коммитов.

---

## Шаг 2. Создать репозиторий для заметок

Отдельный от кода. Это важно: бот коммитит заметки туда, и смешивать их с исходниками нельзя.

1. GitHub → **New repository**
2. Имя: `obsidian-vault` (любое)
3. **Private** — обязательно, если не хочешь публиковать личные заметки
4. Поставь галочку **Add a README file**

> ❗️ Репозиторий должен быть **непустым**. Пустой репозиторий не имеет ветки `main`, и первый коммит бота упадёт с ошибкой `404`.

Папку `00_Inbox` создавать не нужно — она появится сама с первой заметкой.

---

## Шаг 3. Собрать четыре ключа

### 3.1. Telegram-бот

`@BotFather` → `/newbot` → имя и username → получить токен вида `1234567890:AAH...`.

Свой `user_id` узнать у `@userinfobot`.

### 3.2. Groq

console.groq.com/keys → **Create API Key** → скопировать `gsk_...`. Показывается один раз.

### 3.3. GitHub-токен для записи заметок

github.com/settings/tokens → **Tokens (classic)** → Generate new token → галочка **`repo`**.

Либо fine-grained: Repository access → только репозиторий с заметками → Permissions → **Contents: Read and write**.

---

## Шаг 4. Заполнить `.env`

```bash
cp .env.example .env
```

Минимум, без которого не запустится:

| Переменная | Значение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `1234567890:AAH...` |
| `ALLOWED_TELEGRAM_USERS` | твой id, например `123456789` |
| `GROQ_API_KEY` | `gsk_...` |
| `GITHUB_TOKEN` | `ghp_...` или `github_pat_...` |
| `GITHUB_REPO` | `your-username/obsidian-vault` |

Остальное по желанию:

| Переменная | По умолчанию | Зачем |
|---|---|---|
| `GITHUB_BRANCH` | `main` | ветка для коммитов |
| `OBSIDIAN_INBOX_DIR` | `00_Inbox` | папка, куда падают заметки |
| `TIMEZONE` | `Asia/Yekaterinburg` | время в `created` и имени файла |
| `MAX_AUDIO_MB` | `20` | лимит голосового |
| `FILENAME_TRANSLITERATE` | `true` | `true` — латиница в именах, `false` — кириллица |

`.env` уже в `.gitignore`. Проверь, что он не попал в индекс: `git status --short` не должен показывать `.env`.

---

## Шаг 5. Запустить локально

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Проверка конфига встроена: при незаполненном поле бот не стартует и печатает, чего не хватает.

```
❌ Не удалось прочитать .env:
  • GITHUB_REPO: ожидается формат owner/repo, например your-username/your-vault
```

Дальше: `/start` в Telegram → отправь текст на пару предложений → в репозитории появится `.md` в `00_Inbox/`.

---

## Шаг 6. Поставить на VPS (опционально)

Нужен Linux с systemd. Пути и пользователя можно оставить как есть — они указаны в юните.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo useradd --create-home --shell /bin/bash obsidianbot

sudo git clone https://github.com/your-username/telegram-obsidian-bot.git /opt/telegram-obsidian-bot
sudo chown -R obsidianbot:obsidianbot /opt/telegram-obsidian-bot

sudo -u obsidianbot python3 -m venv /opt/telegram-obsidian-bot/.venv
sudo -u obsidianbot /opt/telegram-obsidian-bot/.venv/bin/pip install -r /opt/telegram-obsidian-bot/requirements.txt
```

Скопируй `.env` на сервер (например, через `scp`) и закрой права:

```bash
sudo chown obsidianbot:obsidianbot /opt/telegram-obsidian-bot/.env
sudo chmod 600 /opt/telegram-obsidian-bot/.env
```

Установить службу:

```bash
sudo cp /opt/telegram-obsidian-bot/deploy/telegram-obsidian-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-obsidian-bot
journalctl -u telegram-obsidian-bot -f
```

### Если репозиторий с кодом приватный

Серверу нужен доступ на чтение. Проще всего deploy key:

```bash
# на сервере
sudo -u obsidianbot ssh-keygen -t ed25519 -f /home/obsidianbot/.ssh/deploy -N ""
cat /home/obsidianbot/.ssh/deploy.pub
```

Публичный ключ добавить в GitHub: репозиторий → Settings → Deploy keys → Add deploy key (read-only достаточно).

Затем в `~/.ssh/config` пользователя `obsidianbot`:

```
Host github.com
    IdentityFile ~/.ssh/deploy
    IdentitiesOnly yes
```

---

## Шаг 7. Телефон (опционально)

Нужен, чтобы заметки появлялись и на Android.

1. GitHub → fine-grained token → доступ только к репозиторию с заметками → **Contents: Read and write**
2. Obsidian → Settings → Community plugins → Browse → **Git** → Install → Enable
3. Палитра команд → `Git: Clone an existing remote repo`
4. URL репозитория, логин GitHub, пароль = токен
5. Настройки плагина: Auto pull interval 5 минут, Pull on startup — вкл

Подробнее — в README, раздел «Синхронизация с телефоном».

---

## Шаг 8. Настроить базу знаний

Бот создаёт заметки, но не раскладывает их по папкам. Структура — твоя ответственность, и вот рабочая схема.

Скопируй шаблон из репозитория в корень своего хранилища:

```bash
cp -r examples/vault/* /path/to/your-vault/
```

Появятся папки `00_Inbox`, `10_Notes`, `20_Projects`, `90_Archive`, `99_Templates` и файлы `Dashboard.md`, `Карта.md`.

| Папка | Что кладём |
|---|---|
| `00_Inbox` | сюда пишет бот. Очередь, а не хранилище |
| `10_Notes` | постоянные заметки: идеи, мысли |
| `20_Projects` | задачи и хабы активных дел |
| `30_Дом` | текущие бытовые дела: общий чек-лист |
| `90_Archive` | отработанное |
| `99_Templates` | шаблон хаба проекта |

**Разбор — одно действие:** перенести файл из `00_Inbox` в нужную папку. Поле `status:` менять не нужно.

**Карта и хабы.** `Карта.md` — домашняя страница: инбокс, проекты, темы, последние заметки. Проект — файл в `20_Projects` с `type: project`; заметка привязывается к нему полем `up: "[[Проект]]"`. Хаб сам собирает заметки и задачи, в графе появляется иерархия. Шаблон — `99_Templates/Проект.md`.

**Новый проект.** Скопируй шаблон в `20_Projects/<Название>.md`, поменяй `type` на `project`, заполни `description` и `aliases`, запушь. Бот подхватит хаб в течение 10 минут: LLM начнёт узнавать проект, а в карточках появится кнопка.

**Бытовые дела.** `30_Дом/Бытовые дела.md` — общий чек-лист. Сообщения вроде «купить молоко» или «заехать в аптеку» бот дописывает туда задачами, а не создаёт отдельные заметки.

**Категории денег.** Список лежит в `30_Money/Категории.md`, по одной на строку. Бот передаёт его модели, поэтому новые траты попадают в твои категории. Добавил строку и запушил — через 10 минут бот её видит.

**Автоматический разбор.** Если проект узнан, заметка сохраняется сразу в папку проекта. В карточке есть кнопки «в проект», «в архив», «удалить». Фразы вроде «купил молоко» закрывают открытую задачу. `/undo` откатывает последнее действие.

**Дашборд** требует двух плагинов: **Dataview** (таблицы) и **Charts** (графики). Settings → Community plugins → Browse → установить и включить оба. После этого `Dashboard.md` покажет инбокс, открытые задачи, залежавшиеся заметки, категории, теги и графики активности.

Раз в неделю инбокс должен быть пуст. Это весь процесс.

---

## Чек-лист «что поменять под себя»

- [ ] `GITHUB_REPO` — свой репозиторий с заметками
- [ ] `ALLOWED_TELEGRAM_USERS` — свой `user_id`
- [ ] `TIMEZONE` — свой часовой пояс
- [ ] `FILENAME_TRANSLITERATE` — латиница или кириллица в именах
- [ ] `OBSIDIAN_INBOX_DIR` — если хочешь другую папку
- [ ] Скопировать `examples/vault/*` в хранилище и включить Dataview
- [ ] Пользователь и путь в `deploy/telegram-obsidian-bot.service`, если ставишь не в `/opt`
- [ ] `README.md` — ссылки на репозитории в примерах (косметика)

---

## Чего не делать

- **Не коммить `.env`.** В нём все токены. Файл уже в `.gitignore`, но проверяй.
- **Не делать репозиторий с заметками публичным.** Если сделаешь — личные мысли станут доступны всем, включая поисковики.
- **Не переиспользовать чужие ключи.** Свой Groq-ключ = своя квота.
- **Не давать боту доступ ко всем репозиториям.** Fine-grained токен только на один репозиторий — правильный выбор.

---

## Если что-то не работает

| Симптом | Причина |
|---|---|
| `TelegramUnauthorizedError` | токен неверный или отозван |
| `GitHub 404` | неверный `owner/repo` или в репозитории нет ветки `main` |
| `GitHub 403` | у токена нет прав на запись |
| Бот молчит | твой `user_id` не в `ALLOWED_TELEGRAM_USERS` |
| `429` от Groq | исчерпан free tier, бот повторит запрос с паузой |
| Дашборд пустой на телефоне | хранилище на уровень выше репозитория — см. раздел про Android |
