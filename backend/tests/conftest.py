"""Shared test fixtures.

Every test gets an isolated temporary database and artifact root, so tests never see each
other's state and never touch the developer's real project data.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from germandubi.domain.entities.project import Project, SourceRef
from germandubi.domain.value_objects.source_url import validate_source_url
from germandubi.infrastructure.artifacts.store import ArtifactStore
from germandubi.infrastructure.db.session import Database, create_database


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    """An empty SQLite database on disk, created from the current models."""
    db = create_database(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    yield db
    db.dispose()


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    """An open session in a transaction that is committed on success."""
    with database.session() as open_session:
        yield open_session


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    """An artifact store rooted in a temporary directory."""
    return ArtifactStore(tmp_path / "projects")


@pytest.fixture
def youtube_source() -> SourceRef:
    """A validated YouTube source reference."""
    return SourceRef.from_url(validate_source_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))


@pytest.fixture
def project(youtube_source: SourceRef) -> Project:
    """An unsaved project in the NEW state."""
    return Project.create(youtube_source)


@pytest.fixture
def immediate_retries(application: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the retry backoff, for tests about how many attempts happen rather than when.

    A failed stage waits before its next attempt, which is the point of the backoff and a
    nuisance for a test that drives three attempts in a row. Set on the application's own
    settings rather than on the default, so it cannot leak into a test that did not ask.
    Tests that care about the waiting itself do not use this.
    """
    monkeypatch.setattr(application.settings, "job_retry_backoff_seconds", ())
