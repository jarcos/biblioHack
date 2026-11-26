"""The Alembic revision this build of the code expects the database to be on.

The crawler checks it before every job (`bibliohack ops check-schema`) and
refuses to run against a database on any other revision: the crawler image
is rebuilt by hand, so after a deploy that migrates the database it can be
running older code against a newer schema — which is what kept every record
write failing from 2026-09-30 to 2026-11-26.

Move it with every migration. `tests/shared/test_schema_revision.py` fails
until it matches the Alembic head.
"""

EXPECTED_SCHEMA_REVISION = "20260930_0024"
