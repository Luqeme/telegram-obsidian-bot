"""Создание Markdown-файлов в репозитории Obsidian через GitHub REST API.

Используется один запрос PUT /contents/{path}. PyGithub намеренно не нужен:
он синхронный и потребовал бы asyncio.to_thread вокруг каждого вызова.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx

from .note_builder import with_up_link

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
FILE_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class GitHubError(RuntimeError):
    """Ошибка GitHub. user_message — текст, который безопасно показать в чате."""

    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


class GitHubPathExists(GitHubError):
    """Файл с таким путём уже есть в ветке."""


def drop_last_lines(content: str, lines: list[str]) -> tuple[str, int]:
    """Удаляет последние вхождения строк. Возвращает (новый текст, сколько удалено)."""
    removed = 0
    for line in lines:
        target = line + "\n"
        index = content.rfind(target)
        if index == -1:
            continue
        content = content[:index] + content[index + len(target) :]
        removed += 1
    return content, removed


class GitHubService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        repo: str,
        branch: str,
        inbox_dir: str,
    ) -> None:
        self._client = client
        self._repo = repo
        self._branch = branch
        self._inbox = inbox_dir
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "telegram-obsidian-bot",
        }

    # ── Публичный вход ───────────────────────────────────────

    async def save_note(
        self,
        filename: str,
        content: str,
        commit_message: str,
        *,
        directory: str | None = None,
    ) -> tuple[str, str]:
        """Кладёт файл в инбокс (или в указанную папку). Возвращает (путь, ссылку).

        При коллизии имени добавляет суффикс -2, -3, ... (максимум 5 попыток).
        """
        base = (directory or self._inbox).strip("/")
        stem, dot, suffix = filename.partition(".")
        for attempt in range(1, 6):
            name = filename if attempt == 1 else f"{stem}-{attempt}.{suffix}"
            path = f"{base}/{name}"
            try:
                url = await self.push_markdown_note(path, content, commit_message)
            except GitHubPathExists:
                logger.warning("Файл %s уже существует, пробую другое имя", path)
                continue
            return path, url

        raise GitHubError(
            "не удалось подобрать свободное имя файла",
            "❌ Не удалось сохранить: имя файла занято 5 раз подряд.",
        )

    async def check_access(self) -> tuple[bool, str]:
        """Проверка, что репозиторий и токен живы."""
        try:
            response = await self._client.get(
                f"{API_URL}/repos/{self._repo}",
                headers=self._headers,
                timeout=FILE_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return False, f"сеть недоступна: {exc!r}"

        if response.status_code == 200:
            return True, ""
        if response.status_code == 401:
            return False, "токен недействителен или отозван"
        if response.status_code == 404:
            return False, f"репозиторий {self._repo} недоступен"
        return False, f"HTTP {response.status_code}"

    async def get_text(self, path: str) -> str:
        """Читает файл из репозитория. Пустая строка, если файла нет."""
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"
        response = await self._client.get(
            url,
            headers=self._headers,
            params={"ref": self._branch},
            timeout=FILE_TIMEOUT,
        )
        if response.status_code == 404:
            return ""
        if response.status_code != 200:
            raise GitHubError(
                f"GitHub GET {path}: {response.status_code}",
                "❌ Не удалось прочитать данные из GitHub.",
            )
        return base64.b64decode(response.json()["content"]).decode("utf-8")

    async def list_markdown_blobs(self) -> list[tuple[str, str]]:
        """Пары (путь, sha блоба) для всех .md — основа инкрементального индекса."""
        url = f"{API_URL}/repos/{self._repo}/git/trees/{quote(self._branch, safe='')}"
        response = await self._client.get(
            url,
            headers=self._headers,
            params={"recursive": "1"},
            timeout=FILE_TIMEOUT,
        )
        if response.status_code != 200:
            raise GitHubError(
                f"GitHub trees: {response.status_code}",
                "❌ Не удалось получить список заметок.",
            )
        return [
            (item["path"], item["sha"])
            for item in response.json().get("tree", [])
            if item.get("type") == "blob" and item["path"].endswith(".md")
        ]

    async def replace_line(
        self, path: str, old_line: str, new_line: str, commit_message: str
    ) -> bool:
        """Меняет одну строку в файле. False, если строки уже нет."""
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(2):
            try:
                response = await self._client.get(
                    url,
                    headers=self._headers,
                    params={"ref": self._branch},
                    timeout=FILE_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                raise GitHubError(
                    f"GitHub недоступен: {exc!r}",
                    "❌ GitHub временно недоступен, попробуй ещё раз.",
                ) from exc

            if response.status_code == 404:
                return False
            if response.status_code != 200:
                raise GitHubError(
                    f"GitHub GET {path}: {response.status_code}",
                    "❌ Не удалось прочитать заметку.",
                )

            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            if old_line not in content:
                return False

            payload = {
                "message": commit_message,
                "content": base64.b64encode(
                    content.replace(old_line, new_line, 1).encode("utf-8")
                ).decode("ascii"),
                "sha": data["sha"],
                "branch": self._branch,
            }

            put = await self._client.put(
                url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
            )
            if put.status_code in (200, 201):
                return True
            if put.status_code == 409 and attempt == 0:
                logger.warning("GitHub: конфликт при правке строки, повторяю")
                continue

            raise GitHubError(
                f"GitHub PUT {path}: {put.status_code}",
                "❌ Не удалось обновить заметку.",
            )

        return False

    async def set_up_link(
        self, path: str, project: str, commit_message: str
    ) -> bool:
        """Прописывает up: "[[Проект]]" в frontmatter. False, если файла нет."""
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(2):
            try:
                response = await self._client.get(
                    url,
                    headers=self._headers,
                    params={"ref": self._branch},
                    timeout=FILE_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                raise GitHubError(
                    f"GitHub недоступен: {exc!r}",
                    "❌ GitHub временно недоступен, попробуй ещё раз.",
                ) from exc

            if response.status_code == 404:
                return False
            if response.status_code != 200:
                raise GitHubError(
                    f"GitHub GET {path}: {response.status_code}",
                    "❌ Не удалось прочитать заметку.",
                )

            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            updated = with_up_link(content, project)
            if updated == content:
                return True

            payload = {
                "message": commit_message,
                "content": base64.b64encode(updated.encode("utf-8")).decode("ascii"),
                "sha": data["sha"],
                "branch": self._branch,
            }
            put = await self._client.put(
                url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
            )
            if put.status_code in (200, 201):
                return True
            if put.status_code in (409, 422) and attempt == 0:
                logger.warning("GitHub: конфликт при записи up, повторяю")
                continue

            raise GitHubError(
                f"GitHub PUT {path}: {put.status_code}",
                "❌ Не удалось обновить заметку.",
            )

        return False

    async def move_file(
        self, src: str, destination_dir: str, commit_message: str
    ) -> str | None:
        """Переносит файл в другую папку. None, если исходника нет."""
        raw = await self.get_text(src)
        if not raw:
            return None

        destination = destination_dir.strip("/")
        name = PurePosixPath(src).name
        if f"{destination}/{name}" == src:
            return src

        stem, dot, suffix = name.rpartition(".")
        if not dot:
            stem, suffix = name, ""

        for attempt in range(1, 6):
            if attempt == 1:
                candidate = name
            elif suffix:
                candidate = f"{stem}-{attempt}.{suffix}"
            else:
                candidate = f"{stem}-{attempt}"
            target = f"{destination}/{candidate}"
            try:
                await self.push_markdown_note(target, raw, commit_message)
            except GitHubPathExists:
                logger.warning("Файл %s уже есть, пробую другое имя", target)
                continue

            if not await self.delete_file(src, commit_message):
                logger.warning("move: исходный файл уже исчез: %s", src)
            return target

        raise GitHubError(
            "не удалось подобрать свободное имя при переносе",
            "❌ Не удалось перенести заметку: имя занято 5 раз подряд.",
        )

    async def delete_file(self, path: str, commit_message: str) -> bool:
        """Удаляет файл из ветки. False, если файла уже нет."""
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(2):
            response = await self._client.get(
                url,
                headers=self._headers,
                params={"ref": self._branch},
                timeout=FILE_TIMEOUT,
            )
            if response.status_code == 404:
                return False
            if response.status_code != 200:
                raise GitHubError(
                    f"GitHub GET {path}: {response.status_code}",
                    "❌ Не удалось прочитать заметку.",
                )

            payload = {
                "message": commit_message,
                "sha": response.json()["sha"],
                "branch": self._branch,
            }
            deleted = await self._client.request(
                "DELETE", url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
            )
            if deleted.status_code in (200, 201):
                return True
            if deleted.status_code == 404:
                return False
            if deleted.status_code in (409, 422) and attempt == 0:
                logger.warning("GitHub: конфликт при удалении, повторяю")
                continue
            raise GitHubError(
                f"GitHub DELETE {path}: {deleted.status_code}",
                "❌ Не удалось удалить заметку.",
            )

        return False

    async def remove_lines(
        self, path: str, lines: list[str], commit_message: str
    ) -> int:
        """Удаляет последние вхождения строк. Возвращает число удалённых."""
        if not lines:
            return 0
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(2):
            response = await self._client.get(
                url,
                headers=self._headers,
                params={"ref": self._branch},
                timeout=FILE_TIMEOUT,
            )
            if response.status_code == 404:
                return 0
            if response.status_code != 200:
                raise GitHubError(
                    f"GitHub GET {path}: {response.status_code}",
                    "❌ Не удалось прочитать файл.",
                )

            data = response.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            content, removed = drop_last_lines(content, lines)
            if removed == 0:
                return 0

            payload = {
                "message": commit_message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "sha": data["sha"],
                "branch": self._branch,
            }
            put = await self._client.put(
                url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
            )
            if put.status_code in (200, 201):
                return removed
            if put.status_code in (409, 422) and attempt == 0:
                logger.warning("GitHub: конфликт при откате, повторяю")
                continue
            raise GitHubError(
                f"GitHub PUT {path}: {put.status_code}",
                "❌ Не удалось отменить действие.",
            )

        return 0

    async def append_line(
        self,
        path: str,
        line: str,
        commit_message: str,
        *,
        header: str | None = None,
    ) -> None:
        """Дописывает строку в файл, создавая его при отсутствии."""
        await self.append_lines(path, [line], commit_message, header=header)

    async def append_lines(
        self,
        path: str,
        lines: list[str],
        commit_message: str,
        *,
        header: str | None = None,
    ) -> None:
        """Дописывает несколько строк одним коммитом."""
        if not lines:
            return
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(2):
            content = ""
            sha: str | None = None

            try:
                response = await self._client.get(
                    url,
                    headers=self._headers,
                    params={"ref": self._branch},
                    timeout=FILE_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                raise GitHubError(
                    f"GitHub недоступен: {exc!r}",
                    "❌ GitHub временно недоступен, попробуй ещё раз.",
                ) from exc

            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                sha = data["sha"]
            elif response.status_code == 404:
                content = f"{header}\n" if header else ""
            else:
                logger.error("GitHub GET %s: HTTP %s", path, response.status_code)
                raise GitHubError(
                    f"GitHub GET {path}: {response.status_code}",
                    "❌ Не удалось прочитать файл в GitHub.",
                )

            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n".join(lines) + "\n"

            payload: dict = {
                "message": commit_message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": self._branch,
            }
            if sha:
                payload["sha"] = sha

            put = await self._client.put(
                url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
            )
            if put.status_code in (200, 201):
                return
            if put.status_code in (409, 422) and attempt == 0:
                logger.warning("GitHub: конфликт при дописывании, повторяю")
                continue

            logger.error("GitHub PUT %s: HTTP %s", path, put.status_code)
            raise GitHubError(
                f"GitHub PUT {path}: {put.status_code}",
                "❌ Не удалось записать в GitHub.",
            )

    async def push_markdown_note(
        self, path: str, content: str, commit_message: str
    ) -> str:
        """PUT /repos/{owner}/{repo}/contents/{path}. Возвращает html_url."""
        payload = {
            "message": commit_message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": self._branch,
        }
        url = f"{API_URL}/repos/{self._repo}/contents/{quote(path, safe='/')}"

        for attempt in range(3):
            try:
                response = await self._client.put(
                    url, json=payload, headers=self._headers, timeout=FILE_TIMEOUT
                )
            except httpx.HTTPError as exc:
                logger.warning("GitHub: сеть, попытка %s: %r", attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GitHubError(
                    f"GitHub недоступен: {exc!r}",
                    "❌ GitHub временно недоступен, попробуй ещё раз.",
                ) from exc

            status = response.status_code

            if status in (200, 201):
                data = response.json()
                return (data.get("content") or {}).get("html_url") or ""

            if status == 422:
                body = response.text[:500]
                if "sha" in body.lower() or "already exists" in body.lower():
                    raise GitHubPathExists(f"файл уже существует: {path}")
                raise GitHubError(
                    f"GitHub 422: {body}",
                    "❌ GitHub отклонил файл: неверный путь или содержимое.",
                )

            if status == 401:
                logger.error("GitHub 401: токен недействителен")
                raise GitHubError(
                    "GitHub 401: недействительный токен",
                    "❌ GitHub: токен недействителен или истёк.",
                )

            if status == 403:
                logger.error("GitHub 403: нет прав")
                raise GitHubError(
                    "GitHub 403: нет прав",
                    f"❌ GitHub: нет доступа к репозиторию {self._repo}.",
                )

            if status == 404:
                logger.error("GitHub 404: репозиторий или ветка не найдены")
                raise GitHubError(
                    "GitHub 404: репозиторий или ветка не найдены",
                    f"❌ GitHub: репозиторий {self._repo} или ветка "
                    f"{self._branch} не найдены.",
                )

            if status in RETRY_STATUSES:
                logger.warning("GitHub %s, попытка %s", status, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GitHubError(
                    f"GitHub {status} после 3 попыток",
                    "❌ GitHub временно недоступен, попробуй ещё раз.",
                )

            logger.error("GitHub неожиданный ответ %s: %s", status, response.text[:300])
            raise GitHubError(
                f"GitHub {status}: {response.text[:300]}",
                f"❌ GitHub вернул ошибку {status}.",
            )

        raise GitHubError(  # pragma: no cover - недостижимо
            "исчерпаны попытки", "❌ GitHub временно недоступен."
        )
