"""Обработка нажатий внутри HTML-виджетов (widget_query)."""

from __future__ import annotations

import logging
from datetime import datetime

from services import GitHubError, Services
from services.widget_shim import WidgetQuery, answer_widget_query

logger = logging.getLogger(__name__)


async def on_widget_query(query: WidgetQuery, services: Services) -> None:
    token = services.settings.telegram_bot_token

    try:
        if query.from_user.id not in services.settings.allowed_user_ids:
            await answer_widget_query(token, query.id, "denied")
            return

        data = query.data or ""
        if data.startswith("done:"):
            await _close_task(services, token, query, data[5:])
            return

        await answer_widget_query(token, query.id, "unknown")
    except Exception:  # noqa: BLE001 - виджет не должен зависать
        logger.exception("widget_query не обработан")
        await answer_widget_query(token, query.id, "error")


async def _close_task(
    services: Services, token: str, query: WidgetQuery, task_id: str
) -> None:
    try:
        task = await services.index.find_task(task_id)
    except GitHubError as exc:
        logger.error("widget task: %s", exc)
        await answer_widget_query(token, query.id, "error")
        return

    if task is None:
        await answer_widget_query(token, query.id, "missing")
        return

    done = datetime.now(services.settings.tz).strftime("%Y-%m-%d")
    old_line = f"- [ ] {task.raw}"
    new_line = f"- [x] {task.raw} ✅ {done}"

    try:
        updated = await services.github.replace_line(
            task.note.path, old_line, new_line, f"Task done: {task.text}"
        )
    except GitHubError as exc:
        logger.error("widget task: %s", exc)
        await answer_widget_query(token, query.id, "error")
        return

    if updated:
        services.index.invalidate()
        logger.info("task_done_widget path=%s", task.note.path)
        await answer_widget_query(token, query.id, "ok")
    else:
        await answer_widget_query(token, query.id, "changed")
