"""The project repository, and the mapping between a project row and a project."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from germandubi.domain.entities.project import (
    CaptionTrack,
    Project,
    ProjectState,
    QualityProfile,
    SourceKind,
    SourceMedia,
    SourceRef,
)
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import (
    ProjectId,
    Ulid,
)
from germandubi.domain.value_objects.language import LanguageCode
from germandubi.infrastructure.db.models import (
    ProjectRow,
)

__all__ = ["ProjectRepository"]


class ProjectRepository:
    """Reads and writes projects."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def add(self, project: Project, *, created_with: str | None = None) -> Project:
        """Insert a new project.

        Args:
            project: The project to persist.
            created_with: The application version that created it, recorded for
                traceability of the on-disk project format.

        Returns:
            The persisted project.
        """
        self.session.add(_project_to_row(project, created_with=created_with))
        return project

    def get(self, project_id: ProjectId) -> Project:
        """Return a project by identity.

        Args:
            project_id: The project to load.

        Returns:
            The project.

        Raises:
            NotFoundError: If no such project exists.
        """
        row = self.session.get(ProjectRow, str(project_id))
        if row is None:
            msg = f"no project with id {project_id}"
            raise NotFoundError(msg, project_id=str(project_id))
        return _row_to_project(row)

    def find(self, project_id: ProjectId) -> Project | None:
        """Return a project, or ``None`` when it does not exist.

        Args:
            project_id: The project to load.

        Returns:
            The project or ``None``.
        """
        row = self.session.get(ProjectRow, str(project_id))
        return _row_to_project(row) if row else None

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Project]:
        """Return projects, newest first.

        Args:
            limit: Maximum number to return.
            offset: How many to skip.

        Returns:
            The projects.
        """
        rows = self.session.scalars(
            select(ProjectRow).order_by(ProjectRow.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return [_row_to_project(row) for row in rows]

    def count(self) -> int:
        """Return the total number of projects."""
        return len(self.session.scalars(select(ProjectRow.id)).all())

    def save(self, project: Project) -> Project:
        """Update an existing project.

        Args:
            project: The project to write.

        Returns:
            The saved project.

        Raises:
            NotFoundError: If the project does not exist.
        """
        row = self.session.get(ProjectRow, str(project.id))
        if row is None:
            msg = f"no project with id {project.id}"
            raise NotFoundError(msg, project_id=str(project.id))
        _apply_project(row, project)
        return project

    def delete(self, project_id: ProjectId) -> None:
        """Delete a project and, by cascade, everything belonging to it.

        Args:
            project_id: The project to delete.

        Raises:
            NotFoundError: If the project does not exist.
        """
        row = self.session.get(ProjectRow, str(project_id))
        if row is None:
            msg = f"no project with id {project_id}"
            raise NotFoundError(msg, project_id=str(project_id))
        self.session.delete(row)


def _project_to_row(project: Project, *, created_with: str | None = None) -> ProjectRow:
    """Build a new row from a project."""
    row = ProjectRow(id=str(project.id), created_with=created_with)
    _apply_project(row, project)
    return row


def _apply_project(row: ProjectRow, project: Project) -> None:
    """Copy a project's current values onto its row."""
    row.source_kind = project.source.kind.value
    row.source_locator = project.source.locator
    row.source_video_id = project.source.video_id
    row.source_language = project.source_language.value
    row.target_language = project.target_language.value
    row.quality = project.quality.value
    row.voice = project.voice
    row.state = project.state.value
    row.title = project.title
    row.error = project.error
    row.media = _media_to_json(project.media)
    row.created_at = project.created_at
    row.updated_at = project.updated_at


def _media_to_json(media: SourceMedia | None) -> dict[str, Any] | None:
    """Serialize probe results for storage."""
    if media is None:
        return None
    return {
        "title": media.title,
        "duration_ms": media.duration_ms,
        "uploader": media.uploader,
        "thumbnail_url": media.thumbnail_url,
        "video_codec": media.video_codec,
        "audio_codec": media.audio_codec,
        "width": media.width,
        "height": media.height,
        "captions": [
            {
                "language": c.language.value,
                "automatic": c.automatic,
                "name": c.name,
                "format": c.format,
            }
            for c in media.captions
        ],
    }


def _json_to_media(payload: dict[str, Any] | None) -> SourceMedia | None:
    """Rebuild probe results from storage."""
    if not payload:
        return None
    return SourceMedia(
        title=payload["title"],
        duration_ms=payload["duration_ms"],
        uploader=payload.get("uploader"),
        thumbnail_url=payload.get("thumbnail_url"),
        video_codec=payload.get("video_codec"),
        audio_codec=payload.get("audio_codec"),
        width=payload.get("width"),
        height=payload.get("height"),
        captions=tuple(
            CaptionTrack(
                language=LanguageCode(c["language"]),
                automatic=c["automatic"],
                name=c.get("name"),
                format=c.get("format"),
            )
            for c in payload.get("captions", [])
        ),
    )


def _row_to_project(row: ProjectRow) -> Project:
    """Rebuild a project from its row."""
    return Project(
        id=ProjectId(Ulid(row.id)),
        source=SourceRef(
            kind=SourceKind(row.source_kind),
            locator=row.source_locator,
            video_id=row.source_video_id,
        ),
        source_language=LanguageCode(row.source_language),
        target_language=LanguageCode(row.target_language),
        quality=QualityProfile(row.quality),
        voice=row.voice,
        state=ProjectState(row.state),
        title=row.title,
        media=_json_to_media(row.media),
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
