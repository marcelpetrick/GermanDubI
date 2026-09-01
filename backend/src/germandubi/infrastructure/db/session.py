"""Database engine and session management.

SQLite is the right choice for a single-user workstation, but it needs three pragmas set
explicitly on every connection or it behaves badly under a concurrent API process and
worker. They are applied here, once, rather than hoped for.
"""

from __future__ import annotations

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from germandubi.infrastructure.db.models import Base

#: The first migration. A database that predates Alembic is stamped here before upgrading.
_BASE_REVISION: Final = "11505ca091a8"
_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_MIGRATIONS: Final = _PACKAGE_ROOT / "db" / "migrations"
_ALEMBIC_INI: Final = _PACKAGE_ROOT / "db" / "alembic.ini"

__all__ = ["Database", "create_database"]

logger = logging.getLogger(__name__)


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    """Apply the pragmas SQLite needs for a concurrent reader and writer.

    - ``journal_mode=WAL`` lets the API read while the worker writes. Without it the API
      blocks for the duration of every worker transaction.
    - ``foreign_keys=ON`` is off by default in SQLite, so cascades would silently not
      happen and deleting a project would orphan its segments.
    - ``busy_timeout`` makes a contended write wait rather than immediately raising
      "database is locked", which is the single most common SQLite failure mode.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


class Database:
    """Owns the engine and hands out sessions.

    Attributes:
        engine: The SQLAlchemy engine.
    """

    def __init__(self, engine: Engine) -> None:
        """Initialise with an engine.

        Args:
            engine: A configured SQLAlchemy engine.
        """
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session inside a transaction, committing on success.

        Yields:
            An open :class:`~sqlalchemy.orm.Session`.

        Raises:
            Exception: Anything raised by the body, after rolling back.
        """
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def migrate(self) -> None:
        """Bring the database to the current schema.

        Migrations are the only thing that creates or changes the schema. The alternative
        -- ``metadata.create_all`` for new databases and Alembic for existing ones -- gives
        the schema two owners: a fresh database is never stamped, so the first migration
        against it fails with "table already exists", and an existing one never receives a
        new column at all. That is not hypothetical; it is what happened when ``voice`` was
        added to projects.

        A database this application created before migrations owned the schema has tables
        but no version. It is stamped at the base revision and then upgraded, which is safe
        because each migration checks whether its change is already present.

        Migrating is serialized across processes. The API and the worker start together and
        both migrate, and on a database that does not exist yet neither finds an
        ``alembic_version`` table to contend on -- so both ran the first migration and the
        loser failed with "table events already exists". SQLite gives Alembic nothing to
        coordinate with here; an advisory lock beside the database file is the coordination.
        """
        with self._migration_lock():
            config = self._alembic_config()
            if self._needs_stamping():
                command.stamp(config, _BASE_REVISION)
            command.upgrade(config, "head")

    @contextmanager
    def _migration_lock(self) -> Iterator[None]:
        """Hold the right to migrate this database, waiting for whoever else has it.

        Blocking, unlike the worker slot: the second process must not give up, it must wait
        and then find the schema already at head, which ``upgrade`` treats as a no-op.

        Only file-backed SQLite needs this. An in-memory database is private to its process,
        and a real server has its own transactional DDL.
        """
        path = self._lock_path()
        if path is None:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _lock_path(self) -> Path | None:
        """Return the lock file beside the database, or ``None`` when locking is pointless."""
        url = self.engine.url
        if not url.drivername.startswith("sqlite") or not url.database:
            return None
        if url.database == ":memory:":
            return None
        return Path(url.database).with_suffix(".migrate.lock")

    def _alembic_config(self) -> Config:
        """Return an Alembic config pointed at this database."""
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("script_location", str(_MIGRATIONS))
        config.set_main_option(
            "sqlalchemy.url", self.engine.url.render_as_string(hide_password=False)
        )
        # Leave the application's logging alone; see the note in the migration environment.
        config.attributes["configure_logger"] = False
        return config

    def _needs_stamping(self) -> bool:
        """Return whether this is a pre-Alembic database that already has tables."""
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        return bool(tables) and "alembic_version" not in tables

    def create_all(self) -> None:
        """Create every table directly from the models, without migrations.

        For tests that want a schema in microseconds rather than a migration run. Anything
        that ships uses :meth:`migrate`; a test asserts the two agree, so this staying fast
        cannot let the two definitions drift apart.
        """
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        """Close all pooled connections."""
        self.engine.dispose()


def create_database(url: str, *, echo: bool = False) -> Database:
    """Build a :class:`Database` for a SQLAlchemy URL.

    Args:
        url: The SQLAlchemy URL. A SQLite file URL has its parent directory created.
        echo: Whether to log every statement.

    Returns:
        The configured database.
    """
    is_sqlite = url.startswith("sqlite")
    if is_sqlite and ":memory:" not in url:
        path = Path(url.split("///", 1)[-1])
        path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        echo=echo,
        future=True,
        # The API process serves requests on a thread pool; SQLite's default thread check
        # would reject those connections.
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )
    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite)
    return Database(engine)
