"""The progress event repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from germandubi.domain.value_objects.identifiers import (
    ProjectId,
    RunId,
)
from germandubi.infrastructure.db.models import (
    EventRow,
)

__all__ = ["EventRepository"]


class EventRepository:
    """Appends and replays progress events."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def append(
        self,
        project_id: ProjectId,
        kind: str,
        payload: dict[str, Any],
        *,
        run_id: RunId | None = None,
    ) -> int:
        """Append an event and return its sequence number.

        Args:
            project_id: The project the event concerns.
            kind: The event type, e.g. ``stage_started``.
            payload: Event data, serialized as JSON.
            run_id: The run the event belongs to, when applicable.

        Returns:
            The assigned monotonic sequence number.
        """
        row = EventRow(
            project_id=str(project_id),
            run_id=str(run_id) if run_id else None,
            kind=kind,
            payload=payload,
        )
        self.session.add(row)
        self.session.flush()
        return row.sequence

    def since(
        self, project_id: ProjectId, after: int = 0, *, limit: int = 500
    ) -> list[tuple[int, str, dict[str, Any]]]:
        """Return events after a sequence number.

        This is what makes SSE reconnection lossless: the browser sends the last event id
        it saw and receives exactly what it missed.

        Args:
            project_id: The project.
            after: Return events with a sequence number strictly greater than this.
            limit: Maximum number of events to return.

        Returns:
            ``(sequence, kind, payload)`` tuples, oldest first.
        """
        rows = self.session.scalars(
            select(EventRow)
            .where(EventRow.project_id == str(project_id), EventRow.sequence > after)
            .order_by(EventRow.sequence)
            .limit(limit)
        ).all()
        return [(row.sequence, row.kind, dict(row.payload)) for row in rows]

    def latest_sequence(self, project_id: ProjectId) -> int:
        """Return the highest sequence number recorded for a project.

        Args:
            project_id: The project.

        Returns:
            The highest sequence number, or ``0`` when there are no events.
        """
        value = self.session.scalar(
            select(EventRow.sequence)
            .where(EventRow.project_id == str(project_id))
            .order_by(EventRow.sequence.desc())
            .limit(1)
        )
        return int(value) if value else 0
