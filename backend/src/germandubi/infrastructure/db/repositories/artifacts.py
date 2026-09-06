"""The artifact repository, and the mapping between an artifact row and an artifact."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from germandubi.domain.entities.artifact import Artifact, ArtifactKind, Provenance
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import (
    ArtifactId,
    ProjectId,
    Ulid,
)
from germandubi.infrastructure.db.models import (
    ArtifactRow,
)

__all__ = ["ArtifactRepository"]


class ArtifactRepository:
    """Reads and writes artifact records."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def add(self, artifact: Artifact) -> Artifact:
        """Insert an artifact record.

        Args:
            artifact: The artifact to persist.

        Returns:
            The persisted artifact.
        """
        self.session.add(
            ArtifactRow(
                id=str(artifact.id),
                project_id=str(artifact.project_id),
                segment_id=artifact.segment_id,
                kind=artifact.kind.value,
                relative_path=artifact.relative_path,
                content_hash=artifact.content_hash,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                superseded=artifact.superseded,
                provenance=_provenance_to_json(artifact.provenance),
            )
        )
        return artifact

    def get(self, artifact_id: ArtifactId) -> Artifact:
        """Return one artifact.

        Args:
            artifact_id: The artifact to load.

        Returns:
            The artifact.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(ArtifactRow, str(artifact_id))
        if row is None:
            msg = f"no artifact with id {artifact_id}"
            raise NotFoundError(msg, artifact_id=str(artifact_id))
        return _row_to_artifact(row)

    def latest(
        self,
        project_id: ProjectId,
        kind: ArtifactKind,
        *,
        segment_id: str | None = None,
    ) -> Artifact | None:
        """Return the most recent non-superseded artifact of a kind.

        Args:
            project_id: The owning project.
            kind: The artifact kind.
            segment_id: Restrict to one segment, for per-segment artifacts.

        Returns:
            The artifact, or ``None`` when the stage has not produced one yet.
        """
        query = (
            select(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.kind == kind.value,
                ArtifactRow.superseded.is_(False),
            )
            .order_by(ArtifactRow.created_at.desc(), ArtifactRow.id.desc())
        )
        if segment_id is not None:
            query = query.where(ArtifactRow.segment_id == segment_id)
        row = self.session.scalars(query.limit(1)).first()
        return _row_to_artifact(row) if row else None

    def list_for_project(self, project_id: ProjectId) -> list[Artifact]:
        """Return every current artifact of a project.

        Args:
            project_id: The owning project.

        Returns:
            The artifacts, newest first.
        """
        rows = self.session.scalars(
            select(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.superseded.is_(False),
            )
            .order_by(ArtifactRow.created_at.desc())
        ).all()
        return [_row_to_artifact(row) for row in rows]

    def supersede(
        self, project_id: ProjectId, kind: ArtifactKind, *, segment_id: str | None = None
    ) -> None:
        """Mark existing artifacts of a kind as superseded.

        The files stay on disk: processing here is non-destructive, so a previous result
        remains available for comparison and rollback.

        Args:
            project_id: The owning project.
            kind: The artifact kind to supersede.
            segment_id: Restrict to one segment.
        """
        statement = (
            update(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.kind == kind.value,
                ArtifactRow.superseded.is_(False),
            )
            .values(superseded=True)
        )
        if segment_id is not None:
            statement = statement.where(ArtifactRow.segment_id == segment_id)
        self.session.execute(statement)


def _provenance_to_json(provenance: Provenance | None) -> dict[str, Any] | None:
    """Serialize provenance for storage."""
    if provenance is None:
        return None
    return {
        "app_version": provenance.app_version,
        "provider_id": provenance.provider_id,
        "model_id": provenance.model_id,
        "input_hash": provenance.input_hash,
        "parameters": provenance.parameters,
        "created_at": provenance.created_at.isoformat(),
    }


def _row_to_artifact(row: ArtifactRow) -> Artifact:
    """Rebuild an artifact from its row."""
    provenance = None
    if row.provenance:
        payload = dict(row.provenance)
        provenance = Provenance(
            app_version=payload["app_version"],
            provider_id=payload["provider_id"],
            input_hash=payload["input_hash"],
            model_id=payload.get("model_id"),
            parameters=payload.get("parameters", {}),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )
    return Artifact(
        id=ArtifactId(Ulid(row.id)),
        project_id=ProjectId(Ulid(row.project_id)),
        kind=ArtifactKind(row.kind),
        relative_path=row.relative_path,
        content_hash=row.content_hash,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        provenance=provenance,
        segment_id=row.segment_id,
        superseded=row.superseded,
    )
