"""Transaction boundary shared by the API, the CLI and the worker.

A use case either commits everything it did or nothing. That matters most in the worker:
writing an artifact record, updating a segment and marking a job succeeded must land
together, or a crash between them leaves a project claiming work it never did.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from germandubi.infrastructure.artifacts.store import ArtifactStore
from germandubi.infrastructure.db.repositories import (
    ArtifactRepository,
    EventRepository,
    JobRepository,
    ProjectRepository,
    SegmentRepository,
)
from germandubi.infrastructure.db.session import Database

__all__ = ["UnitOfWork", "UnitOfWorkFactory"]


@dataclass(frozen=True, slots=True)
class UnitOfWork:
    """The repositories and artifact store for one transaction.

    Attributes:
        session: The open session; committed when the context exits cleanly.
        projects: Project repository.
        segments: Segment repository.
        artifacts: Artifact repository.
        jobs: Job and run repository.
        events: Progress event repository.
        store: The filesystem artifact store.
    """

    session: Session
    projects: ProjectRepository
    segments: SegmentRepository
    artifacts: ArtifactRepository
    jobs: JobRepository
    events: EventRepository
    store: ArtifactStore

    def flush(self) -> None:
        """Push pending changes to the database without committing.

        Needed when a later step in the same transaction reads back something just written.
        """
        self.session.flush()


class UnitOfWorkFactory:
    """Creates a :class:`UnitOfWork` per transaction.

    Attributes:
        database: The database to open sessions on.
        store: The artifact store shared by every unit of work.
    """

    def __init__(self, database: Database, store: ArtifactStore) -> None:
        """Initialise the factory.

        Args:
            database: The database.
            store: The artifact store.
        """
        self.database = database
        self.store = store

    @contextmanager
    def __call__(self) -> Iterator[UnitOfWork]:
        """Open a transaction and yield its unit of work.

        Yields:
            A :class:`UnitOfWork` bound to an open session.
        """
        with self.database.session() as session:
            yield UnitOfWork(
                session=session,
                projects=ProjectRepository(session),
                segments=SegmentRepository(session),
                artifacts=ArtifactRepository(session),
                jobs=JobRepository(session),
                events=EventRepository(session),
                store=self.store,
            )
