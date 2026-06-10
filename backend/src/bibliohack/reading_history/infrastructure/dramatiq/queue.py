"""`ImportJobQueue` adapter that sends to the Dramatiq actor."""

from __future__ import annotations


class DramatiqImportJobQueue:
    """Concrete `ImportJobQueue` over the Redis broker.

    The actor import happens inside `enqueue` so that merely constructing
    the adapter (e.g. while building FastAPI dependencies in unit tests)
    never configures a broker or touches Redis.

    The send is delayed a couple of seconds: the API enqueues from inside a
    request transaction that only commits when the response is sent, and a
    worker grabbing the message before that commit would find the job row
    missing/unclaimable and drop it. The delay comfortably outlives the
    commit window.
    """

    _SEND_DELAY_MS = 2_000

    def enqueue(self, job_id: str) -> None:
        from bibliohack.reading_history.infrastructure.dramatiq.actors import (
            process_shelf_import,
        )

        process_shelf_import.send_with_options(args=(job_id,), delay=self._SEND_DELAY_MS)
