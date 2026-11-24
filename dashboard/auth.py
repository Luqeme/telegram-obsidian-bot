"""Проверка initData от Telegram: без внешних зависимостей.

Mini App приходит со строкой `initData`, подписанной токеном бота.
Если подпись не сходится — любой, кто узнал адрес, увидел бы финансы.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE = 24 * 60 * 60
FUTURE_SKEW = 5 * 60


class InitDataError(Exception):
    """initData отсутствует, битый или просроченный."""


def verify_init_data(raw: str, bot_token: str, *, max_age: int = MAX_AGE) -> dict:
    """Возвращает разобранные поля или бросает InitDataError."""
    if not raw or not raw.strip():
        raise InitDataError("нет initData")

    try:
        pairs = dict(parse_qsl(raw, strict_parsing=False, keep_blank_values=True))
    except ValueError as exc:
        raise InitDataError("initData не разбирается") from exc

    received = pairs.pop("hash", "")
    if not received:
        raise InitDataError("нет подписи")

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received):
        raise InitDataError("подпись не сходится")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("битая дата авторизации") from exc

    now = time.time()
    if auth_date <= 0:
        raise InitDataError("нет даты авторизации")
    if now - auth_date > max_age:
        raise InitDataError("initData устарел, открой дашборд заново")
    if auth_date - now > FUTURE_SKEW:
        raise InitDataError("дата авторизации из будущего")

    user: dict = {}
    if "user" in pairs:
        try:
            parsed = json.loads(pairs["user"])
        except ValueError as exc:
            raise InitDataError("битый user") from exc
        if isinstance(parsed, dict):
            user = parsed

    return {"user": user, "auth_date": auth_date, "query_id": pairs.get("query_id", "")}
