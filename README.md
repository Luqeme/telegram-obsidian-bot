# Telegram-бот «Второй мозг»

Асинхронный Telegram-бот, который превращает голосовые и текстовые заметки в структурированные Markdown-файлы Obsidian и коммитит их в GitHub.

Наговорил мысль на бегу → через несколько секунд она лежит в `00_Inbox/` твоего хранилища с заголовком, тегами, выжимкой и чек-листом задач.

## Что умеет

- 🎙 **Голос → текст** — Groq Whisper `whisper-large-v3`, русский язык
- 🧠 **Структурирование** — `openai/gpt-oss-120b` выделяет заголовок, категорию, 2–4 тега, суть и задачи
- 📝 **Валидный frontmatter** — Obsidian Properties и Dataview видят все поля
- 🔒 **Белый список** — бот реагирует только на разрешённые `user_id`
- ♻️ **Устойчивость** — ретраи на 429/5xx, понятные ошибки, текст не теряется при сбое GitHub
- 💾 **Без временных файлов** — аудио живёт только в памяти

## Установка

```bash
git clone https://github.com/Luqeme/telegram-obsidian-bot.git
cd telegram-obsidian-bot
python -m venv .venv
```

Активация окружения:

```powershell
# Windows
.\.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

## Настройка

Скопируй `.env.example` в `.env` и заполни:

| Переменная | Обязательна | Откуда взять |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `ALLOWED_TELEGRAM_USERS` | да | свой id у [@userinfobot](https://t.me/userinfobot), через запятую |
| `GROQ_API_KEY` | да | [console.groq.com/keys](https://console.groq.com/keys) |
| `GITHUB_TOKEN` | да | classic PAT со scope `repo`, либо fine-grained с **Contents: Read & Write** |
| `GITHUB_REPO` | да | `owner/repo`, репозиторий должен быть **непустым** |
| `GITHUB_BRANCH` | нет | по умолчанию `main` |
| `OBSIDIAN_INBOX_DIR` | нет | по умолчанию `00_Inbox` |
| `TIMEZONE` | нет | по умолчанию `Asia/Yekaterinburg` |
| `MAX_AUDIO_MB` | нет | по умолчанию `20` |

Что важно знать:

- **Репозиторий должен содержать хотя бы один коммит.** Пустой репозиторий не имеет ветки `main`, и первый `PUT` вернёт `404`. Создай его с README.
- Папку `00_Inbox` создавать не нужно — GitHub создаст её вместе с первым файлом.
- `.env` в `.gitignore`. Токены в репозиторий не попадают.

## Запуск

```powershell
python bot.py
```

Первый запуск проверяет конфиг и падает с понятным сообщением, если что-то не заполнено:

```
❌ Не удалось прочитать .env:
  • GITHUB_REPO: ожидается формат owner/repo, например kozhi/my-vault
```

Дальше — `/start` в Telegram и любая заметка.

## Как это работает

```
Telegram → whitelist → Whisper (если голос) → LLM (JSON) → сборка Markdown → GitHub API
```

Ключевое решение: **LLM не пишет Markdown**. Она возвращает строгий JSON:

```json
{
  "is_meaningful": true,
  "title": "Рефакторинг авторизации на JWT",
  "category": "Задача",
  "tags": ["backend", "пет-проект"],
  "summary": "…",
  "tasks": ["Изучить PyJWT"]
}
```

Frontmatter, дата, тип записи и дословный оригинал подставляются кодом. Поэтому файл всегда валиден, а дата всегда настоящая.

## Структура

```
bot.py                      точка входа, polling, логи, глобальные ошибки
config.py                   валидация .env
prompts.py                  системный промпт + JSON-схема
middlewares/auth.py         белый список user_id
handlers/base.py            /start, /help, /id
handlers/notes.py           голос и текст
services/groq_service.py    Whisper + LLM, ретраи
services/github_service.py  PUT /contents, коллизии имён
services/note_builder.py    NoteDraft, slug, frontmatter, Markdown
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Тесты не ходят в сеть и не требуют ключей.

## Частые проблемы

| Симптом | Причина |
|---|---|
| `TelegramUnauthorizedError` | токен отозван или скопирован с опечаткой |
| `GitHub 404` | неверный `owner/repo` или в репозитории нет ветки `main` |
| `GitHub 403` | у токена нет прав на запись в этот репозиторий |
| `Бот молчит` | твой `user_id` не в `ALLOWED_TELEGRAM_USERS`; узнать: `/id` не сработает — используй @userinfobot |
| `429` от Groq | исчерпан лимит free tier, бот повторит запрос с паузой |

## Безопасность

- Бот обрабатывает сообщения только от `ALLOWED_TELEGRAM_USERS`.
- Токены читаются из `.env` и никогда не пишутся в логи.
- Аудио не сохраняется на диск.
- Рекомендуется приватный репозиторий хранилища.

## Стек

Python 3.10+ · aiogram 3 · httpx · pydantic-settings · Groq Cloud · GitHub REST API

---

## Деплой на VPS (systemd)

Проверено на Ubuntu 22.04 / 24.04. Нужен любой сервер с systemd.

### 1. Подготовка системы

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
sudo useradd --create-home --shell /bin/bash obsidianbot
```

### 2. Код и зависимости

```bash
sudo git clone https://github.com/Luqeme/telegram-obsidian-bot.git /opt/telegram-obsidian-bot
sudo chown -R obsidianbot:obsidianbot /opt/telegram-obsidian-bot

sudo -u obsidianbot python3 -m venv /opt/telegram-obsidian-bot/.venv
sudo -u obsidianbot /opt/telegram-obsidian-bot/.venv/bin/pip install -r /opt/telegram-obsidian-bot/requirements.txt
```

### 3. Конфигурация

```bash
sudo -u obsidianbot nano /opt/telegram-obsidian-bot/.env
sudo chmod 600 /opt/telegram-obsidian-bot/.env
```

### 4. Служба

```bash
sudo cp /opt/telegram-obsidian-bot/deploy/telegram-obsidian-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-obsidian-bot
```

### 5. Проверка

```bash
systemctl status telegram-obsidian-bot
journalctl -u telegram-obsidian-bot -f
```

В логах должно появиться:

```
INFO | bot | Запуск: llm=openai/gpt-oss-120b, stt=whisper-large-v3, repo=...
INFO | aiogram.dispatcher | Start polling
```

### Обслуживание

```bash
# после изменения .env
sudo systemctl restart telegram-obsidian-bot

# обновление кода
cd /opt/telegram-obsidian-bot
sudo -u obsidianbot git pull
sudo -u obsidianbot .venv/bin/pip install -r requirements.txt
sudo systemctl restart telegram-obsidian-bot

# последние 100 строк логов
journalctl -u telegram-obsidian-bot -n 100 --no-pager
```

### Если что-то не так

- `status=203/EXEC` — неверный путь в `ExecStart` или venv не создан.
- `status=1` сразу после старта — смотри `journalctl`: скорее всего незаполненный `.env`, бот печатает, какого поля не хватает.
- `TelegramUnauthorizedError` — токен отозван, нужен новый у `@BotFather`.
- Бот работает, но не отвечает — проверь `ALLOWED_TELEGRAM_USERS`.

---

## Синхронизация с телефоном (Android)

Бот коммитит заметки в GitHub. Чтобы они появлялись на телефоне, нужно связать хранилище с репозиторием и там.

### 1. Токен

GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token:

| Поле | Значение |
|---|---|
| Repository access | Only select repositories → `obsidian-vault` |
| Permissions → Contents | **Read and write** |
| Expiration | 90 дней (по умолчанию) |

### 2. Плагин

Obsidian на Android → Settings → Community plugins → Browse → **Git** (Vinzent03) → Install → Enable.

### 3. Клонирование

Командная палитра → `Git: Clone an existing remote repo`:

| Поле | Значение |
|---|---|
| Repository URL | `https://github.com/Luqeme/obsidian-vault.git` |
| Username | `Luqeme` |
| Password | `github_pat_...` |

### 4. Настройки

| Параметр | Значение |
|---|---|
| Auto pull interval | 5 минут |
| Pull updates on startup | вкл |
| Author name / email | `Luqeme` / `26500323+Luqeme@users.noreply.github.com` |

### Ограничения

- **Токен истекает.** Через 90 дней синхронизация молча перестанет работать — это самая частая причина «заметки не приходят». Обновляй токен заранее.
- **Конфликты.** Если править один файл на двух устройствах одновременно, git создаст конфликт. Практически не случается: бот только создаёт новые файлы.
- **Фоновая синхронизация на Android ограничена** системой. Надёжнее всего синхронизировать при открытии Obsidian (Pull on startup).


