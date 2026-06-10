"""HTTP tests for the shelf-import endpoints — fakes behind the providers.

No database, no Redis, no Dramatiq: the job repository and queue providers
are overridden, and auth is short-circuited at `get_current_user`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_rate_limiter
from bibliohack.reading_history.application.ports import ImportJobView
from bibliohack.reading_history.domain.import_job import ImportJobStatus
from bibliohack.reading_history.interfaces.http.dependencies import (
    get_import_job_queue,
    get_import_job_repository,
)
from bibliohack.shared.infrastructure.settings import Settings, get_settings
from tests.shared.fakes import AllowAllRateLimiter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

GOODREADS_CSV = (
    "Book Id,Title,Author,ISBN13,My Rating,Exclusive Shelf,My Review,Date Read,Date Added\n"
    '1,"Cien años de soledad","Gabriel García Márquez","=""9788497592208""",5,read,,2024/01/02,2023/12/01\n'
    '2,"Nada","Carmen Laforet",,0,to-read,,,\n'
)


class FakeImportJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self._counter = 0

    async def create(self, *, user_id: str, filename: str | None, csv_content: str) -> str:
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.jobs[job_id] = {
            "user_id": user_id,
            "filename": filename,
            "csv_content": csv_content,
            "status": ImportJobStatus.QUEUED,
        }
        return job_id

    async def get_view(self, job_id: str, *, user_id: str) -> ImportJobView | None:
        job = self.jobs.get(job_id)
        if job is None or job["user_id"] != user_id:
            return None
        return ImportJobView(
            id=job_id,
            status=job["status"],  # type: ignore[arg-type]
            filename=job["filename"],  # type: ignore[arg-type]
            total=None,
            inserted=None,
            updated=None,
            matched_isbn=None,
            matched_title_author=None,
            unmatched=None,
            error=None,
            created_at=datetime.now(UTC),
            finished_at=None,
        )


class RecordingQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


@pytest.fixture
def reader() -> User:
    return User.register(email=Email("reader@example.com"), password_hash=PasswordHash("h"))


@pytest.fixture
def jobs() -> FakeImportJobRepository:
    return FakeImportJobRepository()


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def app(reader: User, jobs: FakeImportJobRepository, queue: RecordingQueue) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_current_user] = lambda: reader
    application.dependency_overrides[get_import_job_repository] = lambda: jobs
    application.dependency_overrides[get_import_job_queue] = lambda: queue
    application.dependency_overrides[get_rate_limiter] = AllowAllRateLimiter
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _upload(client: TestClient, content: bytes, filename: str = "library.csv") -> object:
    return client.post("/api/shelf/import", files={"file": (filename, content, "text/csv")})


def test_valid_csv_is_accepted_queued_and_pollable(
    client: TestClient, jobs: FakeImportJobRepository, queue: RecordingQueue, reader: User
) -> None:
    response = _upload(client, GOODREADS_CSV.encode())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["filename"] == "library.csv"

    job_id = body["id"]
    assert queue.enqueued == [job_id]
    assert jobs.jobs[job_id]["user_id"] == str(reader.id)
    assert "Cien años" in str(jobs.jobs[job_id]["csv_content"])

    poll = client.get(f"/api/shelf/import/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["id"] == job_id


def test_other_users_jobs_are_invisible(client: TestClient, jobs: FakeImportJobRepository) -> None:
    response = _upload(client, GOODREADS_CSV.encode())
    job_id = response.json()["id"]
    jobs.jobs[job_id]["user_id"] = "someone-else"  # simulate another owner

    assert client.get(f"/api/shelf/import/{job_id}").status_code == 404
    assert client.get("/api/shelf/import/no-such-job").status_code == 404


def test_non_goodreads_content_is_rejected(client: TestClient, queue: RecordingQueue) -> None:
    not_csv = _upload(client, b"\xff\xfe\x00\x01 binary junk")
    assert not_csv.status_code == 422

    wrong_columns = _upload(client, b"a,b,c\n1,2,3\n")
    assert wrong_columns.status_code == 422

    assert queue.enqueued == []


def test_size_and_row_caps(app: FastAPI, queue: RecordingQueue) -> None:
    settings = Settings(import_max_upload_bytes=64, import_max_rows=1)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        too_big = _upload(client, b"x" * 65)
        assert too_big.status_code == 413

        two_rows = "Book Id,Title\n1,A\n2,B\n"  # 2 rows > max_rows=1, but under the byte cap
        too_many = _upload(client, two_rows.encode())
        assert too_many.status_code == 413
    assert queue.enqueued == []


def test_import_requires_authentication() -> None:
    app = create_app()
    app.dependency_overrides[get_rate_limiter] = AllowAllRateLimiter
    with TestClient(app) as client:
        upload = _upload(client, GOODREADS_CSV.encode())
        poll = client.get("/api/shelf/import/some-id")
    assert upload.status_code == 401
    assert poll.status_code == 401
