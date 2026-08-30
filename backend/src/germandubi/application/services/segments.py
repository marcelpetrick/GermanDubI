"""Segment review and correction.

This is the workflow the product is actually for: automation gets the dub most of the way,
a person fixes what it got wrong, and only the affected work is redone.

Every edit here does two things. It records the change non-destructively - the previous
German text is kept as a revision - and it declares exactly what became stale, so the
regeneration that follows is minimal and correct.
"""

from __future__ import annotations

import logging

from germandubi.application.services.unit_of_work import UnitOfWorkFactory
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.pipeline import Stage
from germandubi.domain.entities.segment import (
    ReviewState,
    SegmentStatus,
    SpeechSegment,
    TextOrigin,
)
from germandubi.domain.errors import DomainError, NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId, SegmentId

__all__ = ["SegmentService", "SegmentSummary"]

logger = logging.getLogger(__name__)


class SegmentSummary:
    """Aggregate counts shown above the segment table.

    Attributes:
        total: Number of segments.
        translated: How many have German text.
        synthesized: How many have German speech.
        approved: How many the reviewer approved.
        flagged: How many carry a quality flag.
    """

    def __init__(self, segments: list[SpeechSegment]) -> None:
        """Compute the summary.

        Args:
            segments: The project's segments.
        """
        self.total = len(segments)
        self.translated = sum(1 for s in segments if s.is_translated)
        self.synthesized = sum(
            1 for s in segments if s.status in {SegmentStatus.SYNTHESIZED, SegmentStatus.FITTED}
        )
        self.approved = sum(1 for s in segments if s.review_state is ReviewState.APPROVED)
        self.flagged = sum(1 for s in segments if s.flags)
        self.failed = sum(1 for s in segments if s.status is SegmentStatus.FAILED)


class SegmentService:
    """Reading and correcting segments."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        """Initialise the service.

        Args:
            unit_of_work: Factory producing a transaction per operation.
        """
        self.unit_of_work = unit_of_work

    def list_for_project(self, project_id: ProjectId) -> list[SpeechSegment]:
        """Return a project's segments in timeline order.

        Args:
            project_id: The project.

        Returns:
            The segments.
        """
        with self.unit_of_work() as uow:
            return uow.segments.list_for_project(project_id)

    def summary(self, project_id: ProjectId) -> SegmentSummary:
        """Return aggregate counts for a project's segments.

        Args:
            project_id: The project.

        Returns:
            The summary.
        """
        return SegmentSummary(self.list_for_project(project_id))

    def get(self, segment_id: SegmentId) -> SpeechSegment:
        """Return one segment.

        Args:
            segment_id: The segment.

        Returns:
            The segment.

        Raises:
            NotFoundError: If it does not exist.
        """
        with self.unit_of_work() as uow:
            return uow.segments.get(segment_id)

    def edit_source_text(self, segment_id: SegmentId, text: str) -> tuple[SpeechSegment, Stage]:
        """Correct a segment's English text.

        Correcting the English invalidates its German translation, its speech and its word
        timing, which is why the returned stage is ``TRANSLATE``: everything from there on
        must be redone for this segment, and nothing before it.

        Args:
            segment_id: The segment.
            text: The corrected English text.

        Returns:
            The updated segment and the earliest stage that must be re-run.

        Raises:
            NotFoundError: If the segment does not exist.
            DomainError: If the text is empty.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id)
            updated = segment.with_source_text(text, origin=TextOrigin.USER_EDIT)
            uow.segments.save(updated)
            uow.segments.set_speech_artifact(segment_id, None)
            uow.artifacts.supersede(
                updated.project_id, ArtifactKind.SEGMENT_SPEECH, segment_id=str(segment_id)
            )
            uow.events.append(
                updated.project_id,
                "segment_edited",
                {"segment_id": str(segment_id), "field": "source_text"},
            )
            logger.info("English text corrected for segment %s", segment_id)
            return updated, Stage.TRANSLATE

    def edit_translation(self, segment_id: SegmentId, text: str) -> tuple[SpeechSegment, Stage]:
        """Correct a segment's German text.

        The previous German is kept as a revision, so a human correction can be compared
        with what the machine produced and is never silently lost. Only the speech becomes
        stale, so re-running starts at ``SYNTHESIZE``.

        Args:
            segment_id: The segment.
            text: The corrected German text.

        Returns:
            The updated segment and the earliest stage that must be re-run.

        Raises:
            NotFoundError: If the segment does not exist.
            DomainError: If the text is empty.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id)
            if segment.translation:
                uow.segments.add_translation_revision(
                    segment_id,
                    text=segment.translation,
                    origin=segment.translation_origin or TextOrigin.MACHINE_TRANSLATION,
                )
            updated = segment.with_translation(text, origin=TextOrigin.USER_EDIT)
            uow.segments.save(updated)
            uow.segments.add_translation_revision(
                segment_id, text=text, origin=TextOrigin.USER_EDIT
            )
            uow.segments.set_speech_artifact(segment_id, None)
            uow.artifacts.supersede(
                updated.project_id, ArtifactKind.SEGMENT_SPEECH, segment_id=str(segment_id)
            )
            uow.events.append(
                updated.project_id,
                "segment_edited",
                {"segment_id": str(segment_id), "field": "translation"},
            )
            logger.info("German text corrected for segment %s", segment_id)
            return updated, Stage.SYNTHESIZE

    def approve(self, segment_id: SegmentId) -> SpeechSegment:
        """Mark a segment as approved by the reviewer.

        Args:
            segment_id: The segment.

        Returns:
            The updated segment.

        Raises:
            NotFoundError: If the segment does not exist.
            DomainError: If the segment has no German text to approve.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id).approved()
            uow.segments.save(segment)
            return segment

    def reset(self, segment_id: SegmentId) -> tuple[SpeechSegment, Stage]:
        """Discard a segment's generated German output, keeping its English text.

        Args:
            segment_id: The segment.

        Returns:
            The updated segment and the stage to re-run from.

        Raises:
            NotFoundError: If the segment does not exist.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id).reset()
            uow.segments.save(segment)
            uow.segments.set_speech_artifact(segment_id, None)
            uow.artifacts.supersede(
                segment.project_id, ArtifactKind.SEGMENT_SPEECH, segment_id=str(segment_id)
            )
            return segment, Stage.TRANSLATE

    def mark_for_retranslation(self, segment_id: SegmentId) -> tuple[SpeechSegment, Stage]:
        """Clear a machine translation so the next run produces a new one.

        A human correction is deliberately protected here: retranslating would throw away
        the reviewer's work, so it is refused rather than silently overwritten.

        Args:
            segment_id: The segment.

        Returns:
            The updated segment and the stage to re-run from.

        Raises:
            NotFoundError: If the segment does not exist.
            DomainError: If the segment carries a human translation.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id)
            if segment.has_human_translation:
                msg = (
                    "this segment's German text was written by hand. Reset the segment "
                    "first if you really want to discard that edit."
                )
                raise DomainError(msg, segment_id=str(segment_id))
            updated = segment.reset()
            uow.segments.save(updated)
            return updated, Stage.TRANSLATE

    def mark_for_resynthesis(self, segment_id: SegmentId) -> tuple[SpeechSegment, Stage]:
        """Discard a segment's German speech, keeping its German text.

        Args:
            segment_id: The segment.

        Returns:
            The updated segment and the stage to re-run from.

        Raises:
            NotFoundError: If the segment does not exist.
            DomainError: If the segment has no German text yet.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id)
            if not segment.is_translated:
                msg = "this segment has no German text yet, so there is nothing to synthesize"
                raise DomainError(msg, segment_id=str(segment_id))
            updated = segment.with_translation(
                segment.translation or "",
                origin=segment.translation_origin or TextOrigin.MACHINE_TRANSLATION,
            )
            uow.segments.save(updated)
            uow.segments.set_speech_artifact(segment_id, None)
            uow.artifacts.supersede(
                updated.project_id, ArtifactKind.SEGMENT_SPEECH, segment_id=str(segment_id)
            )
            return updated, Stage.SYNTHESIZE

    def translation_history(self, segment_id: SegmentId) -> list[tuple[int, str, str]]:
        """Return every German rendering this segment has had.

        Args:
            segment_id: The segment.

        Returns:
            ``(revision, text, origin)`` tuples, oldest first.
        """
        with self.unit_of_work() as uow:
            return uow.segments.translation_revisions(segment_id)

    def speech_path(self, segment_id: SegmentId) -> tuple[SpeechSegment, str] | None:
        """Return a segment and the relative path of its current German speech.

        Args:
            segment_id: The segment.

        Returns:
            The segment and its speech path, or ``None`` when nothing is synthesized yet.

        Raises:
            NotFoundError: If the segment does not exist.
        """
        with self.unit_of_work() as uow:
            segment = uow.segments.get(segment_id)
            artifact_id = uow.segments.speech_artifact_id(segment_id)
            if artifact_id is None:
                return None
            try:
                artifact = uow.artifacts.get(artifact_id)
            except NotFoundError:
                return None
            return segment, artifact.relative_path
