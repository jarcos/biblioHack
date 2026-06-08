"""Widen over-length catalogue columns to TEXT.

`bibliographic_records.document_type` and `.classification` were `varchar(64)`
and `.language` was `varchar(8)`. Some upstream records carry longer or
multi-valued strings (e.g. composite CDU classifications, multi-language
notes), which raised `StringDataRightTruncationError` on insert and aborted
the whole ingest run — freezing catalogue growth while `scrape_tasks` piled up
in `discovered`. TEXT removes the limit; `varchar -> text` is a metadata-only
change in PostgreSQL (no table rewrite).

Revision ID: 20260608_0006
Revises: 20260604_0005
Create Date: 2026-06-08
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260608_0006"
down_revision: str | Sequence[str] | None = "20260604_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("document_type", sa.String(length=64)),
    ("classification", sa.String(length=64)),
    ("language", sa.String(length=8)),
)


def upgrade() -> None:
    for name, _old in _COLUMNS:
        op.alter_column("bibliographic_records", name, type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    for name, old in _COLUMNS:
        op.alter_column(
            "bibliographic_records",
            name,
            type_=old,
            existing_type=sa.Text(),
            existing_nullable=True,
        )
