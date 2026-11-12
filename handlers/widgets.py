"""Обработка нажатий внутри HTML-виджетов (widget_query)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services import GitHubError, Services
from services.notes_index import with_due
from services.widget_shim import WidgetQuery, answer_widget_query, edit_widget_data

from .digest import build_today_state, collect_today, dumps_state
from .report import dumps_report_state, read_money, report_state

logger = logging.getLogger(__name__)

REPORT_PREFIX = "report:"


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
        if data.startswith("due:"):
            await _set_due(services, token, query, data[4:])
            return
        if data.startswith("more:"):
            await _page_today(services, token, query, data[5:])
            return
        if data.startswith("prev:"):
            await _page_today(services, token, query, data[5:])
            return
        if data.startswith(REPORT_PREFIX):
            await _report(services, token, query, data[len(REPORT_PREFIX):])
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


async def _page_today(
    services: Services, token: str, query: WidgetQuery, value: str
) -> None:
    """Листает список задач внутри виджета."""
    if query.chat is None or query.message_id is None:
        await answer_widget_query(token, query.id, "missing")
        return

    try:
        offset = max(0, int(value))
    except ValueError:
        offset = 0

    await answer_widget_query(token, query.id, "ok")
    try:
        data = await collect_today(services)
    except GitHubError as exc:
        logger.error("widget today page: %s", exc)
        return

    state = build_today_state(data, offset)
    await edit_widget_data(
        token,
        query.chat.id,
        query.message_id,
        dumps_state(state),
    )


async def _set_due(
    services: Services, token: str, query: WidgetQuery, payload: str
) -> None:
    """Переносит задачу на завтра / +3 дня или убирает дату."""
    task_id, _, mode = payload.partition(":")
    try:
        task = await services.index.find_task(task_id)
    except GitHubError as exc:
        logger.error("widget due: %s", exc)
        await answer_widget_query(token, query.id, "error")
        return

    if task is None:
        await answer_widget_query(token, query.id, "missing")
        return

    today = datetime.now(services.settings.tz).date()
    if mode == "tomorrow":
        due: str | None = (today + timedelta(days=1)).isoformat()
    elif mode == "plus3":
        due = (today + timedelta(days=3)).isoformat()
    elif mode == "clear":
        due = None
    else:
        await answer_widget_query(token, query.id, "unknown")
        return

    new_raw = with_due(task.raw, due)
    if new_raw == task.raw:
        await answer_widget_query(token, query.id, "same")
        return

    try:
        updated = await services.github.replace_line(
            task.note.path,
            f"- [ ] {task.raw}",
            f"- [ ] {new_raw}",
            f"Task due: {task.text}",
        )
    except GitHubError as exc:
        logger.error("widget due: %s", exc)
        await answer_widget_query(token, query.id, "error")
        return

    if not updated:
        await answer_widget_query(token, query.id, "changed")
        return

    services.index.invalidate()
    logger.info("task_due_widget path=%s mode=%s", task.note.path, mode)
    await answer_widget_query(token, query.id, "ok")
    await _refresh_today(services, token, query)


async def _report(
    services: Services, token: str, query: WidgetQuery, view: str
) -> None:
    """Переключает период отчёта внутри того же сообщения."""
    if query.chat is None or query.message_id is None:
        await answer_widget_query(token, query.id, "missing")
        return

    await answer_widget_query(token, query.id, "ok")

    try:
        rows = await read_money(services)
        state = report_state(
            rows, view, datetime.now(services.settings.tz)
        )
    except GitHubError as exc:
        logger.error("widget report: %s", exc)
        return

    ok = await edit_widget_data(
        token,
        query.chat.id,
        query.message_id,
        dumps_report_state(state),
    )
    if not ok:
        logger.warning("widget report refresh failed chat=%s", query.chat.id)
