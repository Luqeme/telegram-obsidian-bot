"""Обработка нажатий внутри HTML-виджетов (widget_query)."""

from __future__ import annotations

import logging
from datetime import datetime

from services import GitHubError, Services
from services.widget_shim import WidgetQuery, answer_widget_query, edit_widget_data

from .digest import build_today_state, collect_today, dumps_state

logger = logging.getLogger(__name__)


async def on_widget_query(query: WidgetQuery, services: Services) -> None:
    token = services.settings.telegram_bot_token
    logger.info("widget_query id=%s data=%r", query.id, (query.data or "")[:200])

    try:
        if query.from_user.id not in services.settings.allowed_user_ids:
            await answer_widget_query(token, query.id, "denied")
            return

        data = query.data or ""
        if data.startswith("done:"):
            await _close_task(services, token, query, data[5:])
            return

        logger.info("widget_query data=%r", data[:300])
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

    if not updated:
        await answer_widget_query(token, query.id, "changed")
        return

    services.index.invalidate()
    logger.info("task_done_widget path=%s", task.note.path)
    await answer_widget_query(token, query.id, "ok")
    await _refresh_today(services, token, query)


async def _refresh_today(services: Services, token: str, query: WidgetQuery) -> None:
    """Пересчитывает состояние и обновляет виджет на месте."""
    if query.chat is None or query.message_id is None:
        return

    try:
        state = build_today_state(await collect_today(services))
    except GitHubError as exc:
        logger.error("widget today refresh: %s", exc)
        return

    ok = await edit_widget_data(
        token,
        query.chat.id,
        query.message_id,
        dumps_state(state),
    )
    if not ok:
        logger.warning("widget today refresh failed chat=%s", query.chat.id)
