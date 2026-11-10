"""Тесты GitHub API без сети: сохранение в папку и перенос файла."""

from __future__ import annotations

import asyncio
import base64

import httpx

from services.github_service import GitHubService


def make_service(calls: list[tuple[str, str]]):
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "content": base64.b64encode("текст".encode()).decode(),
                    "sha": "sha1",
                },
            )
        if request.method in ("PUT", "DELETE"):
            return httpx.Response(
                200 if request.method == "DELETE" else 201,
                json={"content": {"html_url": "https://github.com/x"}},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = GitHubService(
        client, token="t", repo="owner/repo", branch="main", inbox_dir="00_Inbox"
    )
    return service, client


def test_save_note_into_directory() -> None:
    calls: list[tuple[str, str]] = []
    service, client = make_service(calls)

    async def run() -> tuple[str, str]:
        try:
            return await service.save_note(
                "Заметка.md", "текст", "msg", directory="20_Projects"
            )
        finally:
            await client.aclose()

    path, url = asyncio.run(run())
    assert path == "20_Projects/Заметка.md"
    assert url == "https://github.com/x"
    assert calls[0][0] == "PUT"
    assert "20_Projects" in calls[0][1]
    assert "Заметка.md" in calls[0][1]


def test_move_file_creates_target_and_deletes_source() -> None:
    calls: list[tuple[str, str]] = []
    service, client = make_service(calls)

    async def run() -> str | None:
        try:
            return await service.move_file(
                "00_Inbox/Заметка.md", "90_Archive", "move"
            )
        finally:
            await client.aclose()

    moved = asyncio.run(run())
    assert moved == "90_Archive/Заметка.md"
    methods = [method for method, _ in calls]
    assert methods == ["GET", "PUT", "GET", "DELETE"]
