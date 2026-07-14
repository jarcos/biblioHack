"""Index-eligible pg_trgm title(+author) record matcher (canon + shelf).

One implementation shared by the canon C1 matcher and the Goodreads shelf
matcher — same conservative thresholds, same precedence (callers try ISBN-13
first; this is only the fallback).

Why the operator form matters: ``similarity(col, q) >= t`` looks equivalent
to ``col % q`` but is NOT to the planner — only the ``%`` / ``<->`` operators
can use the trigram GIN index (``ix_bibliographic_records_title_trgm``); the
function form computes trigrams for every row in a sequential scan. Invisible
at the June catalogue size, but at ~236k records the canon sweep (~1k
unmatched seeds, one full scan each) blew past canon_resolve's 30-min budget
and pegged Postgres for the whole window every 4 hours (diagnosed 2026-07-14).

Two subtleties, both validated with EXPLAIN ANALYZE on prod:

* The ``%`` cut-off is the ``pg_trgm.similarity_threshold`` GUC, not a
  per-query constant. It is pinned per-transaction (``SET LOCAL`` — reverts on
  commit/rollback, never leaks through the connection pool) to the TITLE
  threshold: at the default 0.3 a common-trigram Spanish title pulls ~50k
  candidates off the index (1.8s); at 0.5 that drops to ~3.6k (~0.2-0.5s).
  The explicit ``similarity() >= t`` stays as a belt-and-braces post-filter.
* The author check deliberately KEEPS the function form: the EXISTS is
  correlated on ``record_id`` (an indexed nested-loop semi-join probing a
  handful of contributor rows per title candidate, ~0.1ms each), and using
  ``%`` there would wrongly apply the 0.5 GUC to authors, whose threshold
  is 0.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    ContributorModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Trigram thresholds settled by the Goodreads matcher; canon inherits them.
# Precision over recall: a wrong link pollutes the signal, a miss simply
# re-matches for free as the catalogue grows. Author names differ in ordering
# across sources ("Salman Rushdie" vs "Rushdie, Salman") but trigrams are
# substring-based, so a modest author floor still helps.
TITLE_SIMILARITY_MIN = 0.5
AUTHOR_SIMILARITY_MIN = 0.3


async def match_title_author(session: AsyncSession, title: str, author: str | None) -> str | None:
    """Best ``bibliographic_records.id`` for a title(+author), or None.

    Must run inside a transaction (both callers use ``transactional_session``);
    ``SET LOCAL`` warns and no-ops outside one.
    """
    await session.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = {TITLE_SIMILARITY_MIN}"))

    title_sim = func.similarity(BibliographicRecordModel.title, title)
    stmt = (
        select(BibliographicRecordModel.id)
        .where(
            # Index-eligible candidate filter (GIN, gin_trgm_ops)…
            BibliographicRecordModel.title.op("%", is_comparison=True)(title),
            # …then the exact threshold on those candidates only.
            title_sim >= TITLE_SIMILARITY_MIN,
        )
        .order_by(title_sim.desc())
        .limit(1)
    )
    if author:
        author_match = (
            select(ContributorModel.record_id)
            .where(
                ContributorModel.record_id == BibliographicRecordModel.id,
                ContributorModel.role == "author",
                func.similarity(ContributorModel.name, author) >= AUTHOR_SIMILARITY_MIN,
            )
            .exists()
        )
        stmt = stmt.where(author_match)

    record_id = (await session.execute(stmt)).scalar_one_or_none()
    return str(record_id) if record_id is not None else None
