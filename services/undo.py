"""История последних действий для /undo.

Хранится в JSON рядом с кодом, чтобы переживать перезапуск бота.
У каждого пользователя свой небольшой стек.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

MAX_ACTIONS = 10
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "undo_state.json"


@dataclass(slots=True)
class Action:
    kind: str  # note | lines | replace | move
    path: str
    lines: list[str] = field(default_factory=list)
    label: str = "действие"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "lines": self.lines,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "Action | None":
        if not isinstance(raw, dict):
            return None
        kind = raw.get("kind")
        path = raw.get("path")
        if kind not in {"note", "lines", "replace", "move"} or not isinstance(path, str) or not path:
            return None
        lines = raw.get("lines")
        if not isinstance(lines, list) or not all(isinstance(item, str) for item in lines):
            lines = []
        label = raw.get("label")
        return cls(
            kind=kind,
            path=path,
            lines=lines,
            label=label if isinstance(label, str) and label else "действие",
        )


class UndoStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self._path = path
        self._lock = Lock()
        self._data = self._load()

    def _load(self) -> dict[str, list[Action]]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}

        data: dict[str, list[Action]] = {}
        for user_id, items in raw.items():
            if not isinstance(items, list):
                continue
            actions = [action for item in items if (action := Action.from_dict(item))]
            if actions:
                data[str(user_id)] = actions[-MAX_ACTIONS:]
        return data

    def _save(self) -> None:
        payload = {
            user_id: [action.to_dict() for action in actions]
            for user_id, actions in self._data.items()
        }
        try:
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(self._path)
        except OSError as exc:
            logger.warning("Не удалось сохранить undo_state: %s", exc)

    def push(self, user_id: int, action: Action) -> None:
        with self._lock:
            stack = self._data.setdefault(str(user_id), [])
            stack.append(action)
            del stack[:-MAX_ACTIONS]
            self._save()

    def pop(self, user_id: int) -> Action | None:
        with self._lock:
            stack = self._data.get(str(user_id))
            if not stack:
                return None
            action = stack.pop()
            if not stack:
                self._data.pop(str(user_id), None)
            self._save()
            return action
