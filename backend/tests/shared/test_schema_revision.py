"""The crawler image's expected schema revision can't fall behind the migrations.

The crawler compares the database's Alembic revision with
EXPECTED_SCHEMA_REVISION before every job. If a migration lands without this
constant moving, every crawler job would refuse to run after the deploy; this
test makes that a red CI instead of an outage.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from bibliohack.shared.infrastructure.schema_revision import EXPECTED_SCHEMA_REVISION


def test_expected_revision_is_the_alembic_head() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert heads == [EXPECTED_SCHEMA_REVISION], (
        "A migration moved the Alembic head: set EXPECTED_SCHEMA_REVISION in "
        "shared/infrastructure/schema_revision.py to the new revision, and rebuild "
        "the crawler on the NAS after the deploy."
    )
