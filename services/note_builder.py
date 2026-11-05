"""Модель заметки и сборка Markdown-файла для Obsidian.

Модуль намеренно не знает ни про Telegram, ни про сеть: на вход — данные,
на выход — строка. Поэтому его можно покрыть тестами целиком.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field, field_validator

Category = Literal["Идея", "Задача", "Мысль", "Контент", "Встреча"]
NoteSource = Literal["voice", "text"]

MAX_SLUG_LEN = 40
MAX_TAGS = 4
PRIORITY_MARKS = {"high": "⏫", "medium": "🔼", "low": "🔽"}

_ORIGIN_ICON: dict[str, str] = {"voice": "🎙", "text": "📝"}

# Упрощённая практическая транслитерация (близко к unidecode).
_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "c", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_YAML_RESERVED = frozenset(
    {"true", "false", "yes", "no", "on", "off", "null", "~", ""}
)
_SAFE_YAML_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_\-]+")


class TaskItem(BaseModel):
    """Задача в формате плагина Tasks: текст + срок + приоритет."""

    text: str
    due: str = ""
    priority: Literal["none", "low", "medium", "high"] = "none"

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("пустая задача")
        return value

    @field_validator("due")
    @classmethod
    def _check_due(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return ""
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().lower()
            if value in {"high", "medium", "low", "none"}:
                return value
            return "none"
        return value


class NoteDraft(BaseModel):
    """То, что вернула LLM. Ни одного поля, которое придумывает код."""

    is_meaningful: bool = True
    title: str = Field(min_length=1)
    category: Category
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    tasks: list[TaskItem] = Field(default_factory=list)

    money_kind: Literal["none", "expense", "income"] = "none"
    money_amount: float = 0
    money_category: str = ""
    project: str = ""

    @field_validator("tasks", mode="before")
    @classmethod
    def _tasks_from_strings(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                {"text": item} if isinstance(item, str) else item for item in value
            ]
        return value

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        value = value.lstrip("#").strip()
        value = value.strip("\"'«»“”„").strip()
        value = value.rstrip(".").strip()
        if not value:
            raise ValueError("пустой заголовок")
        return value[:120]

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().capitalize()
        return value

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        return " ".join(value.split()).strip()


# ── Ссылки ───────────────────────────────────────────────────


def wiki_link(text: str, targets: Sequence[tuple[str, str]]) -> str:
    """Оборачивает упоминания существующих заметок в [[файл|подпись]].

    Ссылки строятся только по реальным заголовкам из индекса — выдуманных
    узлов в графе не появляется.
    """
    if not text or not targets:
        return text

    ordered = sorted(targets, key=lambda pair: len(pair[1]), reverse=True)
    for stem, title in ordered:
        if len(title) < 4 or f"[[{stem}|" in text:
            continue
        pattern = re.compile(re.escape(title), re.IGNORECASE)
        if not pattern.search(text):
            continue
        text = pattern.sub(f"[[{stem}|{title}]]", text, count=1)
    return text


# ── Slug ─────────────────────────────────────────────────────


def slugify(
    title: str, max_len: int = MAX_SLUG_LEN, *, transliterate: bool = True
) -> str:
    """Делает безопасное имя файла.

    transliterate=True — латиница («oplatit-internet»), False — кириллица
    («оплатить-интернет»). Оба варианта валидны для GitHub, Obsidian и Android.
    """
    chars: list[str] = []
    for char in title.strip().lower():
        if char in _TRANSLIT:
            chars.append(_TRANSLIT[char] if transliterate else char)
        elif char.isascii() and char.isalnum():
            chars.append(char)
        elif not transliterate and char.isalpha():
            chars.append(char)
        else:
            chars.append("-")

    slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        if "-" in cut:
            cut = cut.rsplit("-", 1)[0]
        slug = cut.strip("-") or slug[:max_len].strip("-")
    return slug or "note"


_BAD_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def human_name(title: str, max_len: int = MAX_SLUG_LEN) -> str:
    """Заголовок как есть, без служебных символов файловой системы."""
    name = _BAD_FILENAME_RE.sub("", title)
    name = " ".join(name.split()).strip(" .")
    return name[:max_len].strip(" .") or "заметка"


def make_filename(
    title: str,
    moment: datetime,
    max_len: int = MAX_SLUG_LEN,
    *,
    transliterate: bool = True,
) -> str:
    """Заголовок YYYY-MM-DD.md — заголовок для поиска, дата для порядка."""
    name = (
        slugify(title, max_len, transliterate=True)
        if transliterate
        else human_name(title, max_len)
    )
    return f"{name} {moment:%Y-%m-%d}.md"


# ── Теги ─────────────────────────────────────────────────────


def sanitize_tag(tag: str) -> str:
    value = tag.strip().lstrip("#").strip().lower()
    value = value.replace("_", "-").replace(" ", "-")
    value = re.sub(r"[^\w\-]", "", value, flags=re.UNICODE)
    return re.sub(r"-+", "-", value).strip("-")


def normalize_tags(tags: list[str], limit: int = MAX_TAGS) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        clean = sanitize_tag(tag)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


# ── YAML ─────────────────────────────────────────────────────


def _yaml_scalar(value: str) -> str:
    """Кавычки только там, где без них YAML поймёт значение неправильно."""
    if value in _YAML_RESERVED or value.lstrip("-").isdigit():
        return f'"{value}"'
    if _SAFE_YAML_RE.fullmatch(value) is None:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def with_up_link(content: str, project: str) -> str:
    """Добавляет или заменяет поле up в frontmatter, не трогая остальной файл."""
    safe = project.strip().replace('"', '\\"')
    line = f'up: "[[{safe}]]"'

    if not content.startswith("---"):
        return f"---\n{line}\n---\n\n{content}"

    end = content.find("\n---", 3)
    if end == -1:
        return content

    header = content[3:end]  # начинается с \n
    body = content[end + 4 :]
    lines = [item for item in header.split("\n") if not item.startswith("up:")]
    lines.append(line)
    return "---" + "\n".join(lines) + "\n---" + body


def build_frontmatter(
    draft: NoteDraft, source: NoteSource, created: datetime
) -> str:
    lines = [
        "---",
        f"created: {created:%Y-%m-%dT%H:%M:%S}",
        f"title: {_yaml_scalar(draft.title)}",
        f"type: inbox-{source}",
        f"category: {draft.category}",
    ]
    tags = normalize_tags(draft.tags)
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {_yaml_scalar(tag)}" for tag in tags)
    lines.extend(["status: inbox", "source: telegram", "up:", "---"])
    return "\n".join(lines)


# ── Markdown ─────────────────────────────────────────────────


def _quote_block(text: str) -> str:
    lines = text.splitlines() or [""]
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


def format_task(task: TaskItem) -> str:
    """Строка задачи в синтаксисе плагина Tasks."""
    line = f"- [ ] {task.text}"
    if task.due:
        line += f" 📅 {task.due}"
    mark = PRIORITY_MARKS.get(task.priority, "")
    if mark:
        line += f" {mark}"
    return line


def build_markdown(
    draft: NoteDraft,
    original_text: str,
    source: NoteSource,
    created: datetime,
    related: Sequence[tuple[str, str]] = (),
) -> str:
    parts: list[str] = [
        build_frontmatter(draft, source, created),
        "",
        f"# {draft.title}",
        "",
    ]

    if draft.summary:
        parts.extend(["## 💡 Суть", draft.summary, ""])

    if draft.tasks:
        parts.append("## 📋 Задачи")
        for task in draft.tasks:
            parts.append(format_task(task))
        parts.append("")

    if related:
        parts.append("## 🔗 Связанное")
        for stem, title in related:
            parts.append(f"- [[{stem}|{title}]]")
        parts.append("")

    parts.extend(
        [
            "---",
            f"> {_ORIGIN_ICON[source]} **Оригинал:**",
            _quote_block(original_text),
        ]
    )

    return "\n".join(parts).rstrip("\n") + "\n"
