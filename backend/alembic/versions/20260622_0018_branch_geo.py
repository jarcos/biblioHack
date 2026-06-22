"""Branch geo/contact enrichment (Libraries milestone — phase L0).

Adds the nullable branch fields the Libraries milestone needs to let users
follow a branch by proximity (see ``docs/design/relevance-and-libraries.html``
→ Phase L / L0): ``address``, ``lat``, ``lng``, ``url``, ``phone``,
``opening_hours``.

It also backfills the two columns that already existed but were always NULL,
**independently of geo** (no network needed):

- ``municipality`` ← ``name`` (in this catalogue the branch ``name`` *is* the
  municipality, e.g. ``AL03`` → "Adra").
- ``province``     ← the AbsysNET ``BranchCode`` 2-letter prefix (verified in
  prod: ``AL00`` … ``SE99``). The eight Andalusian provinces are mapped; any
  other prefix (a stray non-RBPA code) is left NULL.

``lat``/``lng`` stay NULL here — they're filled off-OPAC by
``bibliohack holdings enrich-branches`` (Nominatim town-centroid geocode).

Revision ID: 20260622_0018
Revises: 20260620_0017
Create Date: 2026-06-22
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260622_0018"
down_revision: str | Sequence[str] | None = "20260620_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# AbsysNET BranchCode prefix → Andalusian province (verified against prod).
_PROVINCE_BY_PREFIX = {
    "AL": "Almería",
    "CA": "Cádiz",
    "CO": "Córdoba",
    "GR": "Granada",
    "HU": "Huelva",
    "JA": "Jaén",
    "MA": "Málaga",
    "SE": "Sevilla",
}


def upgrade() -> None:
    op.add_column("branches", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("branches", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("branches", sa.Column("url", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("opening_hours", sa.Text(), nullable=True))

    # Backfill municipality from name where missing (geo-independent).
    op.execute(
        "UPDATE branches SET municipality = name "
        "WHERE municipality IS NULL AND name IS NOT NULL AND btrim(name) <> ''"
    )
    # Backfill province from the BranchCode 2-letter prefix.
    case = " ".join(
        f"WHEN left(code, 2) = '{prefix}' THEN '{province}'"
        for prefix, province in _PROVINCE_BY_PREFIX.items()
    )
    op.execute(
        f"UPDATE branches SET province = CASE {case} ELSE province END "  # noqa: S608 (static map, no user input)
        "WHERE province IS NULL"
    )

    # Distance-sort / province-scope read path hits these.
    op.create_index("ix_branches_province", "branches", ["province"])


def downgrade() -> None:
    op.drop_index("ix_branches_province", table_name="branches")
    op.drop_column("branches", "opening_hours")
    op.drop_column("branches", "phone")
    op.drop_column("branches", "url")
    op.drop_column("branches", "lng")
    op.drop_column("branches", "lat")
    op.drop_column("branches", "address")
    # municipality/province pre-existed the revision; leave the backfilled values.
