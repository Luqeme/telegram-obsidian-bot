# AGENTS.md

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
