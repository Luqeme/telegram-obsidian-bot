"""Тесты GitHub API без сети: чтение, запись, конфликты, архив ветки."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import tarfile

import httpx
import pytest

from services.github_service import GitHubError, GitHubService

REPO = "owner/repo"


def make_service(handler) -> tuple[GitHubService, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = GitHubService(
        client, token="t", repo=REPO, branch="main", inbox_dir="00_Inbox"
    )
    return service, client


def run(coro):
    return asyncio.run(coro)


def encoded(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def make_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"owner-repo-sha/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_get_text_decodes_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": encoded("привет"), "sha": "s"})

    service, client = make_service(handler)

    async def go():
        try:
            return await service.get_text("00_Inbox/x.md")
        finally:
            await client.aclose()

    assert run(go()) == "привет"


def test_get_text_returns_empty_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    service, client = make_service(handler)

    async def go():
        try:
            return await service.get_text("00_Inbox/missing.md")
        finally:
            await client.aclose()

    assert run(go()) == ""


def test_append_lines_creates_file_with_header() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404)
        payloads.append(json.loads(request.content))
        return httpx.Response(201, json={"content": {"html_url": "u"}})

    service, client = make_service(handler)

    async def go():
        try:
            await service.append_line(
                "30_Money/transactions.csv",
                "2026-11-11,expense,100,Еда,обед",
                "Money",
                header="date,kind,amount,category,note",
            )
        finally:
            await client.aclose()

    run(go())

    text = base64.b64decode(payloads[0]["content"]).decode()
    assert text.startswith("date,kind,amount,category,note\n")
    assert "2026-11-11,expense,100,Еда,обед" in text


def test_append_lines_retries_on_conflict() -> None:
    puts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"content": encoded("a\n"), "sha": "s1"}
            )
        puts.append(1)
        if len(puts) == 1:
            return httpx.Response(409, json={"message": "conflict"})
        return httpx.Response(201, json={"content": {"html_url": "u"}})

    service, client = make_service(handler)

    async def go():
        try:
            await service.append_lines("30_Money/transactions.csv", ["b"], "msg")
        finally:
            await client.aclose()

    run(go())

    assert len(puts) == 2


def test_replace_line_returns_false_when_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"content": encoded("другой текст"), "sha": "s"}
            )
        raise AssertionError("PUT не должен вызываться")

    service, client = make_service(handler)

    async def go():
        try:
            return await service.replace_line("a.md", "- [ ] нет", "- [x] нет", "m")
        finally:
            await client.aclose()

    assert run(go()) is False


def test_delete_file_returns_false_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    service, client = make_service(handler)

    async def go():
        try:
            return await service.delete_file("a.md", "m")
        finally:
            await client.aclose()

    assert run(go()) is False


def test_save_note_picks_free_name_on_collision() -> None:
    puts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        puts.append(request.url.path)
        if len(puts) == 1:
            return httpx.Response(422, json={"message": "sha wasn't supplied"})
        return httpx.Response(201, json={"content": {"html_url": "u"}})

    service, client = make_service(handler)

    async def go():
        try:
            return await service.save_note("Заметка.md", "текст", "msg")
        finally:
            await client.aclose()

    path, _ = run(go())

    assert path == "00_Inbox/Заметка-2.md"
    assert len(puts) == 2


def test_save_note_gives_up_after_five_collisions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "sha wasn't supplied"})

    service, client = make_service(handler)

    async def go():
        try:
            await service.save_note("Заметка.md", "текст", "msg")
        finally:
            await client.aclose()

    with pytest.raises(GitHubError):
        run(go())


def test_download_snapshot_extracts_markdown() -> None:
    archive = make_archive(
        {
            "00_Inbox/a.md": "# A",
            "10_Notes/b.md": "# B",
            "images/c.png": "нет",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "abc123"})
        if "/tarball/" in request.url.path:
            return httpx.Response(200, content=archive)
        raise AssertionError(f"неожиданный запрос: {request.url.path}")

    service, client = make_service(handler)

    async def go():
        try:
            return await service.download_snapshot()
        finally:
            await client.aclose()

    head, files = run(go())

    assert head == "abc123"
    assert files == {"00_Inbox/a.md": "# A", "10_Notes/b.md": "# B"}


def test_download_snapshot_raises_on_bad_archive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "abc"})
        return httpx.Response(200, content="это точно не архив".encode())

    service, client = make_service(handler)

    async def go():
        try:
            await service.download_snapshot()
        finally:
            await client.aclose()

    with pytest.raises(GitHubError):
        run(go())
