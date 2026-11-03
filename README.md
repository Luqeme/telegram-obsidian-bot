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
