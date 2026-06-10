"""Integration tests for the recommendations Postgres adapters.

Real Postgres via testcontainers. Seeds a small catalogue with hand-crafted
1024-d embeddings whose geometry makes the expected ranking obvious: the
anchor points along axis 0, one candidate sits close to it, another sits
orthogonal (far), and a third close record is already on the shelf and must
therefore never be recommended.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

from bibliohack.catalog.infrastructure.absysnet.parser import ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.catalog.infrastructure.postgres.embedding_repository import (
    PostgresEmbeddingRepository,
)
from bibliohack.catalog.infrastructure.postgres.models import BibliographicRecordModel
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.application.ports import ShelfEntryData
from bibliohack.reading_history.domain.shelf import MatchVia, Shelf
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)
from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.recommendations.infrastructure.postgres.recommendation_repository import (
    PostgresCandidateRetriever,
    PostgresRecommendationRepository,
    PostgresShelfTasteReader,
)

pytestmark = pytest.mark.integration

_DIM = 1024


def _vector(**components: float) -> list[float]:
    """A 1024-d vector with the given axis→value components ("a0", "a1", …)."""
    vector = [0.0] * _DIM
    for axis, value in components.items():
        vector[int(axis[1:])] = value
    return vector


@pytest_asyncio.fixture(scope="module")
async def postgres_container() -> AsyncIterator[PostgresContainer]:
    container = PostgresContainer(image="timescale/timescaledb-ha:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="module")
async def applied_db(postgres_container: PostgresContainer) -> AsyncIterator[str]:
    sync_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+psycopg"
    )
    async_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    backend_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    os.environ["DATABASE_URL"] = async_url
    os.environ["DATABASE_URL_SYNC"] = sync_url
    from bibliohack.shared.infrastructure.settings import get_settings

    get_settings.cache_clear()
    command.upgrade(alembic_cfg, "head")
    yield async_url


@pytest_asyncio.fixture
async def session(applied_db: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup, setup.begin():
        await setup.execute(
            text("TRUNCATE bibliographic_records, users, shelf_entries, recommendations CASCADE")
        )
    async with factory() as s, s.begin():
        yield s
    await engine.dispose()


async def _seed_record(
    session: AsyncSession, titn: int, title: str, embedding: list[float]
) -> UUID:
    await PostgresCatalogIngestRepository(session).persist_parsed_record(
        parsed=ParsedRecord(
            titn=titn,
            title=title,
            authors=(f"Autora {titn},",),
            isbns=(),
            record_type="a",
            bibliographic_level="m",
        ),
        copies=[],
        source_url=f"https://example.test/?TITN={titn}",
        source_hash=bytes([titn]) * 32,
    )
    record_id = (
        await session.execute(
            select(BibliographicRecordModel.id).where(BibliographicRecordModel.titn == titn)
        )
    ).scalar_one()
    await PostgresEmbeddingRepository(session).store_embedding(record_id, embedding)
    return record_id


async def _seed_reader_with_shelf(session: AsyncSession, anchor_ids: list[UUID]) -> str:
    user = User.register(
        email=Email("reader@example.com"), password_hash=PasswordHash("$argon2id$fake")
    )
    await PostgresUserRepository(session).add(user)
    shelf = PostgresShelfRepository(session)
    for index, record_id in enumerate(anchor_ids):
        await shelf.upsert_entry(
            ShelfEntryData(
                user_id=str(user.id),
                source="goodreads",
                source_book_id=f"g{index}",
                title=f"Libro {index}",
                author=None,
                isbn_13=None,
                shelf=Shelf.READ,
                rating=5,
                review=None,
                date_read=date(2026, 1, 1),
                date_added=None,
                matched_record_id=str(record_id),
                matched_via=MatchVia.ISBN,
            )
        )
    return str(user.id)


async def test_retriever_ranks_by_taste_and_never_recommends_the_shelf(
    session: AsyncSession,
) -> None:
    anchor = await _seed_record(session, 1, "El anclado", _vector(a0=1.0))
    near = await _seed_record(session, 2, "El cercano", _vector(a0=0.9, a1=0.1))
    far = await _seed_record(session, 3, "El lejano", _vector(a5=1.0))
    owned_near = await _seed_record(session, 4, "Ya leído", _vector(a0=0.95, a1=0.05))
    user_id = await _seed_reader_with_shelf(session, [anchor, owned_near])

    batch = await PostgresCandidateRetriever(session).retrieve(user_id, limit=10)

    returned = [candidate.record_id for candidate in batch.candidates]
    assert returned == [str(near), str(far)]  # nearest first; shelf books excluded
    assert str(anchor) not in returned
    assert str(owned_near) not in returned
    assert batch.candidates[0].score > batch.candidates[1].score
    assert any("El anclado" in liked for liked in batch.liked_books)


async def test_fingerprint_exists_only_with_matches_and_tracks_changes(
    session: AsyncSession,
) -> None:
    anchor = await _seed_record(session, 1, "El anclado", _vector(a0=1.0))
    reader = PostgresShelfTasteReader(session)

    user = User.register(email=Email("a@example.com"), password_hash=PasswordHash("h"))
    await PostgresUserRepository(session).add(user)
    assert await reader.fingerprint(str(user.id)) is None  # empty shelf

    shelf = PostgresShelfRepository(session)
    entry = ShelfEntryData(
        user_id=str(user.id),
        source="goodreads",
        source_book_id="g1",
        title="Libro",
        author=None,
        isbn_13=None,
        shelf=Shelf.READ,
        rating=3,
        review=None,
        date_read=None,
        date_added=None,
        matched_record_id=str(anchor),
        matched_via=MatchVia.ISBN,
    )
    await shelf.upsert_entry(entry)
    first = await reader.fingerprint(str(user.id))
    assert first is not None

    # A rating change must change the fingerprint (cache invalidation).
    from dataclasses import replace

    await shelf.upsert_entry(replace(entry, rating=5))
    second = await reader.fingerprint(str(user.id))
    assert second is not None
    assert second != first


async def test_repository_cache_round_trip_is_keyed_and_per_user(session: AsyncSession) -> None:
    anchor = await _seed_record(session, 1, "El anclado", _vector(a0=1.0))
    near = await _seed_record(session, 2, "El cercano", _vector(a0=0.9))
    user_id = await _seed_reader_with_shelf(session, [anchor])
    repo = PostgresRecommendationRepository(session)

    batch = (Recommendation(record_id=str(near), score=0.91, rationale="Te irá bien."),)
    await repo.replace(user_id, "fp-1", batch)

    assert await repo.get_cached(user_id, "fp-1") == batch
    assert await repo.get_cached(user_id, "fp-STALE") is None

    other = User.register(email=Email("other@example.com"), password_hash=PasswordHash("h"))
    await PostgresUserRepository(session).add(other)
    assert await repo.get_cached(str(other.id), "fp-1") is None  # never another user's batch

    # replace drops the old batch wholesale.
    await repo.replace(user_id, "fp-2", ())
    assert await repo.get_cached(user_id, "fp-1") is None
