"""Дата задачи: установка, перенос и снятие."""

from __future__ import annotations

from services.notes_index import with_due


def test_with_due_sets_date() -> None:
    assert with_due("Купить молоко", "2026-11-14") == "Купить молоко 📅 2026-11-14"


def test_with_due_replaces_existing_date() -> None:
    assert (
        with_due("Купить молоко 📅 2026-11-10", "2026-11-14")
        == "Купить молоко 📅 2026-11-14"
    )


def test_with_due_clears_date() -> None:
    assert with_due("Купить молоко 📅 2026-11-10", None) == "Купить молоко"
    assert with_due("Купить молоко", None) == "Купить молоко"


def test_with_due_keeps_priority_mark() -> None:
    assert (
        with_due("Купить молоко 🔼 📅 2026-11-10", "2026-11-15")
        == "Купить молоко 🔼 📅 2026-11-15"
    )
