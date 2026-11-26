"""CheckSchemaRevision: the guard run-job.sh calls before every crawler job."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from bibliohack.ops.application.use_cases.check_schema_revision import CheckSchemaRevision

if TYPE_CHECKING:
    from bibliohack.ops.application.ports import SchemaRevisionReader


class _Reader:
    def __init__(self, revision: str | None) -> None:
        self._revision = revision

    async def schema_revision(self) -> str | None:
        return self._revision


def _check(revision: str | None) -> CheckSchemaRevision:
    return CheckSchemaRevision(
        reader=cast("SchemaRevisionReader", _Reader(revision)), expected="20260930_0024"
    )


async def test_matching_revisions_pass() -> None:
    result = await _check("20260930_0024").execute()

    assert result.ok
    assert result.message == "schema OK: database and image both at 20260930_0024"


@pytest.mark.parametrize("database", ["20261201_0025", "20260716_0023"])
async def test_any_other_revision_is_drift_and_says_how_to_fix_it(database: str) -> None:
    # 2026-09-30: the database moved to 0024 while the crawler image still
    # expected 0023, and every write failed for 57 days. Ahead or behind, a
    # mismatch means this image and this database don't agree on the schema.
    result = await _check(database).execute()

    assert not result.ok
    assert database in result.message
    assert "20260930_0024" in result.message
    assert "docker compose -f docker-compose.crawler.yml up -d --build" in result.message


async def test_a_database_without_a_revision_is_drift() -> None:
    result = await _check(None).execute()

    assert not result.ok
    assert "no Alembic revision" in result.message
