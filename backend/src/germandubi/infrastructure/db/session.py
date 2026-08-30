"""Database engine and session management.

SQLite is the right choice for a single-user workstation, but it needs three pragmas set
explicitly on every connection or it behaves badly under a concurrent API process and
worker. They are applied here, once, rather than hoped for.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from germandubi.infrastructure.db.models import Base

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

    def create_all(self) -> None:
        """Create every table.

        Used by tests and by first start. Production schema changes go through Alembic;
        see ``docs/development/migrations.md``.
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
