"""Тесты истории /undo и удаления строк из файлов."""

from __future__ import annotations

from services.github_service import drop_last_lines
from services.undo import Action, UndoStore


def test_undo_store_persists(tmp_path) -> None:
    path = tmp_path / "undo.json"
    store = UndoStore(path)
    store.push(1, Action(kind="note", path="00_Inbox/x.md", label="заметка"))
    store.push(
        1,
        Action(
            kind="lines",
            path="30_Money/transactions.csv",
            lines=["2026-11-06,expense,93,Прочее,потратил 93 рубля"],
            label="транзакция",
        ),
    )

    assert store.pop(1).kind == "lines"

    restored = UndoStore(path)
    action = restored.pop(1)
    assert action is not None
    assert action.kind == "note"
    assert action.path == "00_Inbox/x.md"
    assert restored.pop(1) is None


def test_undo_store_keeps_last_ten(tmp_path) -> None:
    store = UndoStore(tmp_path / "undo.json")
    for index in range(15):
        store.push(1, Action(kind="note", path=f"note-{index}.md"))

    paths = [store.pop(1).path for _ in range(10)]  # type: ignore[union-attr]
    assert paths[0] == "note-14.md"
    assert paths[-1] == "note-5.md"
    assert store.pop(1) is None


def test_action_kinds_persist(tmp_path) -> None:
    path = tmp_path / "undo.json"
    store = UndoStore(path)
    store.push(2, Action(kind="replace", path="a.md", lines=["new", "old"]))
    store.push(2, Action(kind="move", path="b.md", lines=["00_Inbox/b.md"]))

    restored = UndoStore(path)
    assert restored.pop(2).kind == "move"
    assert restored.pop(2).kind == "replace"


def test_drop_last_lines_removes_last_occurrence() -> None:
    content, removed = drop_last_lines("a\nb\nb\nc\n", ["b"])
    assert removed == 1
    assert content == "a\nb\nc\n"


def test_drop_last_lines_multiple() -> None:
    content, removed = drop_last_lines("a\nb\nc\n", ["b", "c", "нет"])
    assert removed == 2
    assert content == "a\n"
