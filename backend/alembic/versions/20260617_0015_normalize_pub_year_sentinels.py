"""Normalise out-of-band pub_year sentinels to NULL.

Upstream FEPU frequently carries MARC "unknown date" sentinels — most commonly
9999, also 0/negatives — which had been stored verbatim as `pub_year`. They
printed as "9999" on the catalogue cards and (before the relevance fix) defined
the top of the recency scale. An unknown year should be NULL, not a bogus
number, so the frontend (which already hides a null year) shows nothing.

Data-only migration: blanks any `pub_year` outside the plausible band
[1, 2100] (matches the browse API's year-filter bound and the parser's new
clamp). The parser now stores NULL for these at ingest, so this is a one-off
cleanup of rows scraped before that fix; re-scrapes keep them NULL.

Revision ID: 20260617_0015
Revises: 20260615_0014
Create Date: 2026-06-17
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260617_0015"
down_revision: str | Sequence[str] | None = "20260615_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE bibliographic_records
        SET pub_year = NULL
        WHERE pub_year IS NOT NULL
          AND (pub_year < 1 OR pub_year > 2100)
        """
    )


def downgrade() -> None:
    # Irreversible: the original sentinel values are not recoverable (and were
    # noise). No-op so `downgrade` doesn't fail the chain.
    pass
