"""Import-job lifecycle — the states an uploaded CSV moves through.

`ImportJob` is the aggregate ARCHITECTURE.md §4 names for tracking a
background shelf import. Its state machine is simple enough that the enum IS
the domain: queued → running → done | failed. Transitions are enforced by
the repository's conditional UPDATEs (a job can only be claimed while
queued), not by in-memory objects.
"""

from __future__ import annotations

from enum import StrEnum


class ImportJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
