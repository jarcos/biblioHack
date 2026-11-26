"""CheckSchemaRevision — does this image agree with the database on the schema?

`run-job.sh` calls it (`bibliohack ops check-schema`) before every crawler
job and refuses to run the job on a mismatch. The crawler doesn't ride CD:
on 2026-09-30 a migration dropped a column the 09-28 crawler image still
wrote, and every record write failed for 57 days. With this guard the first
job after such a deploy stops with a message that says what to do, and the
health metrics turn the stop into an alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.ops.application.ports import SchemaRevisionReader

_REBUILD = (
    "rebuild the crawler on the NAS: cd /volume1/docker/bibliohack && "
    "docker compose -f docker-compose.crawler.yml up -d --build"
)


@dataclass(frozen=True, slots=True)
class SchemaCheck:
    database: str | None
    expected: str

    @property
    def ok(self) -> bool:
        return self.database == self.expected

    @property
    def message(self) -> str:
        if self.ok:
            return f"schema OK: database and image both at {self.expected}"
        if self.database is None:
            return (
                f"schema drift: the database has no Alembic revision, this image expects "
                f"{self.expected}; {_REBUILD}"
            )
        return (
            f"schema drift: database at {self.database}, this image expects {self.expected}; "
            f"{_REBUILD}"
        )


class CheckSchemaRevision:
    def __init__(self, *, reader: SchemaRevisionReader, expected: str) -> None:
        self._reader = reader
        self._expected = expected

    async def execute(self) -> SchemaCheck:
        return SchemaCheck(database=await self._reader.schema_revision(), expected=self._expected)
