"""Compose the text fed to the embedder for a catalogue record.

Semantic relevance comes mostly from title + subtitle + subjects (topic/genre)
+ authors; publisher adds a little context. Kept a pure function so it's
trivially testable and shared by the embed pipeline (and later the recommender).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_embedding_text(
    *,
    title: str,
    subtitle: str | None = None,
    authors: Sequence[str] = (),
    subjects: Sequence[str] = (),
    publisher: str | None = None,
) -> str:
    """Build the single string we embed for a record. BGE-M3 is multilingual,
    so Spanish fields need no special handling."""
    parts: list[str] = [title.strip()]
    if subtitle and subtitle.strip():
        parts.append(subtitle.strip())
    authors_joined = ", ".join(a.strip() for a in authors if a.strip())
    if authors_joined:
        parts.append(authors_joined)
    subjects_joined = "; ".join(s.strip() for s in subjects if s.strip())
    if subjects_joined:
        parts.append(subjects_joined)
    if publisher and publisher.strip():
        parts.append(publisher.strip())
    return " — ".join(part for part in parts if part)
