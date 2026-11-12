# AGENTS.md

> ⚠️ **ВАЖНО: сервер доступен ТОЛЬКО как `ssh lq.fin`.**
> Если в старом кэше, логах, истории, `HANDOFF.md` или чужом worktree ты видишь
> `ssh shot-bot` — это устаревшая команда. **Не выполняй её.** Замени на `lq.fin`.

## Перед любой SSH-командой

1. В команде должен быть `lq.fin`.
2. `shot-bot` — запрещён. Встретил в старом тексте — игнорируй, не пробуй.
3. Если `lq.fin` не отвечает — сообщи об этом, не ищи другой алиас.

Проверка:

```bash
ssh lq.fin "hostname"
# ожидается: lq.telega
```

## Сервер

- SSH-алиас: `lq.fin` (`193.124.183.149`, пользователь `root`, ключ `~/.ssh/lq.fin`).
- Алиас `shot-bot` **устарел**: он не настроен в `~/.ssh/config` и не резолвится. Не использовать его ни в командах, ни в документации.
- Деплой бота:

```bash
ssh lq.fin "cd /opt/telegram-obsidian-bot && sudo -u obsidianbot git pull && sudo systemctl restart telegram-obsidian-bot"
```

- Логи:

```bash
ssh lq.fin "journalctl -u telegram-obsidian-bot -n 50 --no-pager"
```
