"""Migrations own the schema, and nothing else is allowed to disagree with them.

The schema used to have two owners: `metadata.create_all` for new databases and Alembic for
existing ones. A fresh database was never stamped, so the first migration against it failed
with "table already exists", and an existing one never received a new column at all. Adding
`projects.voice` hit both halves of that.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import inspect

from germandubi.infrastructure.db.session import create_database


def _columns(database: object) -> dict[str, set[str]]:
    inspector = inspect(database.engine)  # type: ignore[attr-defined]
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def test_migrating_a_new_database_produces_the_schema_the_models_describe(
    tmp_path: Path,
) -> None:
    """The drift check. Two ways of building a schema must not disagree."""
    migrated = create_database(f"sqlite:///{tmp_path / 'migrated.db'}")
    migrated.migrate()

    declared = create_database(f"sqlite:///{tmp_path / 'declared.db'}")
    declared.create_all()

    assert _columns(migrated) == _columns(declared)
    migrated.dispose()
    declared.dispose()


def test_a_new_database_is_stamped_so_later_migrations_apply(tmp_path: Path) -> None:
    database = create_database(f"sqlite:///{tmp_path / 'fresh.db'}")
    database.migrate()

    tables = set(inspect(database.engine).get_table_names())

    assert "alembic_version" in tables, "an unstamped database cannot be upgraded later"
    database.dispose()


def test_migrating_twice_changes_nothing(tmp_path: Path) -> None:
    """Startup runs this every time; the second run must be a no-op rather than an error."""
    database = create_database(f"sqlite:///{tmp_path / 'twice.db'}")
    database.migrate()
    before = _columns(database)

    database.migrate()

    assert _columns(database) == before
    database.dispose()


def test_a_database_from_before_migrations_is_adopted(tmp_path: Path) -> None:
    """The upgrade path for anyone who ran this application before migrations owned it.

    Such a database has tables and no `alembic_version`. It is stamped at the base revision
    and upgraded, which only works because each migration checks whether its change is
    already present.
    """
    path = tmp_path / "legacy.db"
    legacy = create_database(f"sqlite:///{path}")
    legacy.create_all()  # exactly what an older build did
    assert "alembic_version" not in set(inspect(legacy.engine).get_table_names())
    legacy.dispose()

    adopted = create_database(f"sqlite:///{path}")
    adopted.migrate()

    tables = set(inspect(adopted.engine).get_table_names())
    assert "alembic_version" in tables
    assert "voice" in _columns(adopted)["projects"]
    adopted.dispose()


def test_the_schema_survives_a_downgrade_and_upgrade(tmp_path: Path) -> None:
    """A migration that cannot be reversed is a migration nobody dares run."""
    from alembic import command

    database = create_database(f"sqlite:///{tmp_path / 'roundtrip.db'}")
    database.migrate()
    config = database._alembic_config()

    command.downgrade(config, "-1")
    assert "voice" not in _columns(database)["projects"]

    command.upgrade(config, "head")
    assert "voice" in _columns(database)["projects"]
    database.dispose()


@pytest.mark.parametrize("table", ["projects", "segments", "artifacts", "jobs", "runs"])
def test_every_core_table_is_created_by_migrations(tmp_path: Path, table: str) -> None:
    database = create_database(f"sqlite:///{tmp_path / f'{table}.db'}")
    database.migrate()
    assert table in set(inspect(database.engine).get_table_names())
    database.dispose()


#: How many processes race for the first migration. Two reproduced the defect only
#: sometimes even behind a barrier; six makes the loser reliable.
_RACERS = 6


def test_two_processes_can_migrate_one_new_database_at_once(tmp_path: Path) -> None:
    """The API and the worker start together and both migrate.

    On a database that does not exist yet, neither finds an `alembic_version` table to
    contend on, so both ran the first migration and the loser died with "table events
    already exists". In CI that killed the API at startup and the browser suite failed with
    "the API did not become ready", which points nowhere near a migration.

    Real processes, not threads: the defect is between processes, and the fix is an advisory
    file lock that threads in one process would not exercise.

    They wait on a shared file before migrating, so the race is entered on purpose rather
    than hoped for. Without that barrier this reproduced about one run in three, which is
    a guard that would pass while broken more often than not.
    """
    url = f"sqlite+pysqlite:///{tmp_path / 'shared.db'}"
    barrier = tmp_path / "go"
    script = textwrap.dedent(
        f"""
        import time
        from pathlib import Path

        from germandubi.infrastructure.db.session import create_database

        # Import and connect first, then line up: the point of contention is the migration,
        # not the interpreter start-up that would otherwise stagger these by a second.
        database = create_database({url!r})
        while not Path({str(barrier)!r}).exists():
            time.sleep(0.01)
        database.migrate()
        database.engine.dispose()
        """
    )

    with ThreadPoolExecutor(max_workers=_RACERS) as pool:
        results = [
            pool.submit(
                subprocess.run,
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            for _ in range(_RACERS)
        ]
        time.sleep(2.0)  # let every process reach the barrier
        barrier.write_text("go", encoding="utf-8")
        finished = [future.result() for future in results]

    for outcome in finished:
        assert outcome.returncode == 0, outcome.stderr

    database = create_database(url)
    try:
        tables = set(inspect(database.engine).get_table_names())
    finally:
        database.engine.dispose()
    assert "events" in tables
    assert "alembic_version" in tables
