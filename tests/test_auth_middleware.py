"""Тесты белого списка: единственная точка авторизации."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


def _event(user_id: int, answers: list[str] | None = None) -> SimpleNamespace:
    async def answer(text: str, **kwargs: object) -> None:
        if answers is not None:
            answers.append(text)

    return SimpleNamespace(from_user=SimpleNamespace(id=user_id), answer=answer)


def test_allows_known_user() -> None:
    from middlewares.auth import AllowedUsersMiddleware

    middleware = AllowedUsersMiddleware(frozenset({7}))
    calls: list[int] = []

    async def handler(event: object, data: dict) -> str:
        calls.append(event.from_user.id)  # type: ignore[attr-defined]
        return "ok"

    result = asyncio.run(middleware(handler, _event(7), {}))

    assert result == "ok"
    assert calls == [7]


def test_blocks_unknown_user() -> None:
    from middlewares.auth import AllowedUsersMiddleware

    middleware = AllowedUsersMiddleware(frozenset({7}))
    answers: list[str] = []
    called = False

    async def handler(event: object, data: dict) -> str:
        nonlocal called
        called = True
        return "ok"

    result = asyncio.run(middleware(handler, _event(42, answers), {}))

    assert result is None
    assert called is False
    assert answers and "Доступ" in answers[0]


def test_warns_only_once() -> None:
    from middlewares.auth import AllowedUsersMiddleware

    middleware = AllowedUsersMiddleware(frozenset({7}))
    answers: list[str] = []

    async def handler(event: object, data: dict) -> str:  # pragma: no cover
        return "ok"

    asyncio.run(middleware(handler, _event(42, answers), {}))
    asyncio.run(middleware(handler, _event(42, answers), {}))

    assert len(answers) == 1


def test_event_without_user_is_dropped() -> None:
    from middlewares.auth import AllowedUsersMiddleware

    middleware = AllowedUsersMiddleware(frozenset({7}))
    called = False

    async def handler(event: object, data: dict) -> str:
        nonlocal called
        called = True
        return "ok"

    event = SimpleNamespace(from_user=None)

    assert asyncio.run(middleware(handler, event, {})) is None
    assert called is False
