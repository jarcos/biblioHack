"""Unit tests for the embedding-text builder (pure, no model)."""

from __future__ import annotations

from bibliohack.catalog.application.embedding_text import build_embedding_text


def test_combines_fields_title_first() -> None:
    text = build_embedding_text(
        title="Rayuela",
        subtitle="novela",
        authors=["Cortázar, Julio"],
        subjects=["Literatura argentina", "Siglo XX"],
        publisher="Alfaguara",
    )
    assert text.startswith("Rayuela")
    for needle in ("novela", "Cortázar, Julio", "Literatura argentina; Siglo XX", "Alfaguara"):
        assert needle in text


def test_omits_missing_optional_fields() -> None:
    assert build_embedding_text(title="Solo Título") == "Solo Título"


def test_strips_and_skips_blanks() -> None:
    text = build_embedding_text(title="  T  ", authors=["", "  A  "], subjects=[], publisher="  ")
    assert text == "T — A"
