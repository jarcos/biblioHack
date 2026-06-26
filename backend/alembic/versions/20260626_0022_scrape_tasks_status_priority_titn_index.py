"""Composite index on scrape_tasks (status, priority, titn) for the backlist claim.

M7's backlist sweep (`docs/design/m7-backlist-crawl.md`) seeds the whole TITN
space — up to ~2.66M `discovered` rows — at a lower priority than novedades.
The worker claims with
``WHERE status='discovered' ORDER BY priority, titn ... FOR UPDATE SKIP LOCKED``
(`scrape_task_repository.claim_next_batch`), which the single-column
``ix_scrape_tasks_status`` can't serve efficiently at that scale. This adds the
covering composite index so the claim stays index-driven as the backlog grows.

**Operational note (production-size table).** Creating an index inside the
deploy migration transaction takes a write lock on `scrape_tasks` for the build
duration. On the ~millions-of-rows production table, **pre-build it concurrently
on the NAS before deploying this revision**:

    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scrape_tasks_status_priority_titn
        ON scrape_tasks (status, priority, titn);

The ``IF NOT EXISTS`` below then makes this migration a no-op on prod, while
fresh/CI/dev databases (tiny tables) build it instantly. `CREATE INDEX
CONCURRENTLY` cannot run inside Alembic's transaction, which is why it's a
manual pre-step rather than the migration body.

Revision ID: 20260626_0022
Revises: 20260625_0021
Create Date: 2026-06-26
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260626_0022"
down_revision: str | Sequence[str] | None = "20260625_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_scrape_tasks_status_priority_titn"


def upgrade() -> None:
    # IF NOT EXISTS so a concurrent pre-build on the NAS makes this a no-op.
    op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON scrape_tasks (status, priority, titn)")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
