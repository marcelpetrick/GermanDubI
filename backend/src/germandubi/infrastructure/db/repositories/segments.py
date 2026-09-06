"""The segment repository: segments, their words and their translation history."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from germandubi.domain.entities.segment import (
    DurationFit,
    ProsodyProfile,
    ReviewState,
    SegmentStatus,
    SpeechSegment,
    TextOrigin,
    Word,
)
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import (
    ArtifactId,
    ProjectId,
    SegmentId,
    Ulid,
)
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.db.models import (
    SegmentRow,
    TranslationRevisionRow,
    WordRow,
)

__all__ = ["SegmentRepository"]


class SegmentRepository:
    """Reads and writes speech segments, their words and their translation history."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def replace_all(self, project_id: ProjectId, segments: list[SpeechSegment]) -> None:
        """Replace a project's segments wholesale.

        Used when re-segmentation produces a new set. Existing rows are removed first,
        because segment ordinals are unique per project and would otherwise collide.

        Args:
            project_id: The owning project.
            segments: The new segments, in timeline order.
        """
        existing = self.session.scalars(
            select(SegmentRow).where(SegmentRow.project_id == str(project_id))
        ).all()
        for row in existing:
            self.session.delete(row)
        self.session.flush()
        for segment in segments:
            self.session.add(_segment_to_row(segment))

    def list_for_project(self, project_id: ProjectId) -> list[SpeechSegment]:
        """Return a project's segments in timeline order.

        Args:
            project_id: The owning project.

        Returns:
            The segments.
        """
        rows = self.session.scalars(
            select(SegmentRow)
            .where(SegmentRow.project_id == str(project_id))
            .options(selectinload(SegmentRow.words))
            .order_by(SegmentRow.ordinal)
        ).all()
        return [_row_to_segment(row) for row in rows]

    def get(self, segment_id: SegmentId) -> SpeechSegment:
        """Return one segment.

        Args:
            segment_id: The segment to load.

        Returns:
            The segment.

        Raises:
            NotFoundError: If no such segment exists.
        """
        row = self.session.get(SegmentRow, str(segment_id))
        if row is None:
            msg = f"no segment with id {segment_id}"
            raise NotFoundError(msg, segment_id=str(segment_id))
        return _row_to_segment(row)

    def save(self, segment: SpeechSegment) -> SpeechSegment:
        """Update one segment, leaving its word timing untouched.

        Args:
            segment: The segment to write.

        Returns:
            The saved segment.

        Raises:
            NotFoundError: If the segment does not exist.
        """
        row = self.session.get(SegmentRow, str(segment.id))
        if row is None:
            msg = f"no segment with id {segment.id}"
            raise NotFoundError(msg, segment_id=str(segment.id))
        _apply_segment(row, segment)
        row.updated_at = datetime.now(UTC)
        return segment

    def save_many(self, segments: list[SpeechSegment]) -> None:
        """Update several segments.

        Args:
            segments: The segments to write.
        """
        for segment in segments:
            self.save(segment)

    def set_speech_artifact(self, segment_id: SegmentId, artifact_id: ArtifactId | None) -> None:
        """Point a segment at its current German speech artifact.

        Args:
            segment_id: The segment.
            artifact_id: The artifact, or ``None`` to clear the pointer.
        """
        self.session.execute(
            update(SegmentRow)
            .where(SegmentRow.id == str(segment_id))
            .values(speech_artifact_id=str(artifact_id) if artifact_id else None)
        )

    def speech_artifact_id(self, segment_id: SegmentId) -> ArtifactId | None:
        """Return the segment's current speech artifact identity, if any.

        Args:
            segment_id: The segment.

        Returns:
            The artifact id, or ``None``.
        """
        value = self.session.scalar(
            select(SegmentRow.speech_artifact_id).where(SegmentRow.id == str(segment_id))
        )
        return ArtifactId(Ulid(value)) if value else None

    def add_translation_revision(
        self,
        segment_id: SegmentId,
        *,
        text: str,
        origin: TextOrigin,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> int:
        """Append a translation revision.

        Human edits must never be lost, so every German rendering is kept and the current
        one is a pointer on the segment.

        Args:
            segment_id: The segment.
            text: The German text.
            origin: Where it came from.
            provider_id: The provider that produced it.
            model_id: The model used.

        Returns:
            The new revision number, starting at one.
        """
        existing = self.session.scalars(
            select(TranslationRevisionRow.revision).where(
                TranslationRevisionRow.segment_id == str(segment_id)
            )
        ).all()
        revision = (max(existing) if existing else 0) + 1
        self.session.add(
            TranslationRevisionRow(
                segment_id=str(segment_id),
                revision=revision,
                text=text,
                origin=origin.value,
                provider_id=provider_id,
                model_id=model_id,
            )
        )
        return revision

    def translation_revisions(self, segment_id: SegmentId) -> list[tuple[int, str, str]]:
        """Return a segment's translation history.

        Args:
            segment_id: The segment.

        Returns:
            ``(revision, text, origin)`` tuples, oldest first.
        """
        rows = self.session.scalars(
            select(TranslationRevisionRow)
            .where(TranslationRevisionRow.segment_id == str(segment_id))
            .order_by(TranslationRevisionRow.revision)
        ).all()
        return [(row.revision, row.text, row.origin) for row in rows]


def _segment_to_row(segment: SpeechSegment) -> SegmentRow:
    """Build a row, including word timing, from a segment."""
    row = SegmentRow(id=str(segment.id), project_id=str(segment.project_id))
    _apply_segment(row, segment)
    row.words = [
        WordRow(
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            text=word.text,
            confidence=word.confidence,
        )
        for word in segment.words
    ]
    return row


def _apply_segment(row: SegmentRow, segment: SpeechSegment) -> None:
    """Copy a segment's current values onto its row."""
    row.ordinal = segment.ordinal
    row.start_ms = segment.interval.start_ms
    row.end_ms = segment.interval.end_ms
    row.source_text = segment.source_text
    row.source_origin = segment.source_origin.value
    row.confidence = segment.confidence
    row.translation = segment.translation
    row.translation_origin = (
        segment.translation_origin.value if segment.translation_origin else None
    )
    row.prosody = (
        {
            "speech_rate_wps": segment.prosody.speech_rate_wps,
            "pause_before_ms": segment.prosody.pause_before_ms,
            "pause_after_ms": segment.prosody.pause_after_ms,
            "energy_rms": segment.prosody.energy_rms,
        }
        if segment.prosody
        else None
    )
    row.fit = (
        {
            "target_ms": segment.fit.target_ms,
            "generated_ms": segment.fit.generated_ms,
            "applied_rate": segment.fit.applied_rate,
        }
        if segment.fit
        else None
    )
    row.status = segment.status.value
    row.review_state = segment.review_state.value
    row.flags = sorted(segment.flags)


def _row_to_segment(row: SegmentRow) -> SpeechSegment:
    """Rebuild a segment from its row."""
    return SpeechSegment(
        id=SegmentId(Ulid(row.id)),
        project_id=ProjectId(Ulid(row.project_id)),
        ordinal=row.ordinal,
        interval=TimeInterval(row.start_ms, row.end_ms),
        source_text=row.source_text,
        source_origin=TextOrigin(row.source_origin),
        translation=row.translation,
        translation_origin=TextOrigin(row.translation_origin) if row.translation_origin else None,
        words=tuple(
            Word(w.start_ms, w.end_ms, w.text, confidence=w.confidence)
            for w in sorted(row.words, key=lambda w: w.start_ms)
        ),
        prosody=ProsodyProfile(**row.prosody) if row.prosody else None,
        fit=DurationFit(**row.fit) if row.fit else None,
        status=SegmentStatus(row.status),
        review_state=ReviewState(row.review_state),
        flags=frozenset(row.flags or ()),
        confidence=row.confidence,
    )
