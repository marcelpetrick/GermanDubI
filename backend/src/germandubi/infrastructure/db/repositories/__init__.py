"""Repositories: the mapping between persistence rows and domain objects.

Keeping the mapping in one place is what lets the domain stay free of SQLAlchemy and lets
the schema change without a domain refactor. Nothing outside this package constructs a
domain entity from a row, or a row from an entity.

One module per aggregate, with each aggregate's row/domain mapping next to the repository
that owns it. It was one file of 1,196 lines holding all four repositories and their dozen
mappers, which is where merge conflicts concentrate and where a reader stops being able to
hold the whole thing in their head. The names are re-exported here, so every import site is
unchanged: this is a move, not a migration.
"""

from __future__ import annotations

from germandubi.infrastructure.db.repositories.artifacts import ArtifactRepository
from germandubi.infrastructure.db.repositories.events import EventRepository
from germandubi.infrastructure.db.repositories.jobs import JobRepository
from germandubi.infrastructure.db.repositories.projects import ProjectRepository
from germandubi.infrastructure.db.repositories.segments import SegmentRepository

__all__ = [
    "ArtifactRepository",
    "EventRepository",
    "JobRepository",
    "ProjectRepository",
    "SegmentRepository",
]
