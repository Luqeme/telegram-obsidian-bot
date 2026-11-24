"""FastAPI-приложение дашборда: статика + три read-only эндпоинта."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from config import get_settings
from services import GitHubError, GitHubService, NotesIndex

from .auth import InitDataError, verify_init_data
from .data import Dashboard

logger = logging.getLogger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0))
    github = GitHubService(
        client,
        token=settings.github_token,
        repo=settings.github_repo,
        branch=settings.github_branch,
        inbox_dir=settings.obsidian_inbox_dir,
    )
    app.state.dashboard = Dashboard(settings, github, NotesIndex(github))
    logger.info(
        "Дашборд запущен: repo=%s tz=%s",
        settings.github_repo,
        settings.timezone,
    )
    try:
        yield
    finally:
        await client.aclose()


app = FastAPI(
    title="Обсидиан",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.endswith(".html") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


def authorize(raw: str) -> dict:
    dashboard: Dashboard = app.state.dashboard
    settings = dashboard.settings
    try:
        payload = verify_init_data(raw, settings.telegram_bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = 0
    try:
        user_id = int(payload["user"].get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    if user_id not in settings.allowed_user_ids:
        raise HTTPException(status_code=403, detail="доступ разрешён только владельцу")
    return payload


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/api/today")
async def api_today(
    request: Request,
    x_init_data: str = Header(default="", alias="X-Init-Data"),
) -> dict:
    authorize(x_init_data)
    dashboard: Dashboard = request.app.state.dashboard
    try:
        return await dashboard.payload()
    except GitHubError as exc:
        logger.error("Не удалось собрать дашборд: %s", exc)
        raise HTTPException(status_code=502, detail="хранилище недоступно") from exc


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
