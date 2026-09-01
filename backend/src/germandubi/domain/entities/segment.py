"""The speech segment - the central object of the dubbing workflow.

A segment is a time-bounded stretch of narration. It is the unit of review, retry, caching,
translation, synthesis, timing correction and quality assurance. Almost every feature in
this application is answerable as "what does this mean for one segment?"

Segments are immutable: every change returns a new instance. Human edits and regenerations
therefore never destroy a previous result, which is what makes the workflow
non-destructive (``docs/product/vision.md`` section 3.2).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self

from germandubi.domain.errors import DomainError
from germandubi.domain.value_objects.identifiers import ProjectId, SegmentId, new_id
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = [
    "DurationFit",
    "ProsodyProfile",
    "ReviewState",
    "SegmentStatus",
    "SpeechSegment",
    "TextOrigin",
    "Word",
]


class TextOrigin(StrEnum):
    """Where a piece of text came from.

    Distinguishing machine output from a human edit matters: regeneration may overwrite the
    former and must never silently overwrite the latter.
    """

    MANUAL_CAPTIONS = "manual_captions"
    AUTOMATIC_CAPTIONS = "automatic_captions"
    ASR = "asr"
    MACHINE_TRANSLATION = "machine_translation"
    DURATION_ADJUSTED = "duration_adjusted"
    USER_EDIT = "user_edit"

    @property
    def is_human(self) -> bool:
        """Return whether this text was written or corrected by a person."""
        return self is TextOrigin.USER_EDIT


class SegmentStatus(StrEnum):
    """How far a segment has progressed through the pipeline."""

    PENDING = "pending"
    TRANSLATED = "translated"
    SYNTHESIZED = "synthesized"
    FITTED = "fitted"
    FAILED = "failed"


class ReviewState(StrEnum):
    """The reviewer's verdict on a segment."""

    UNREVIEWED = "unreviewed"
    NEEDS_ATTENTION = "needs_attention"
    APPROVED = "approved"


@dataclass(frozen=True, slots=True, order=True)
class Word:
    """One word with its timing, as produced by alignment or ASR.

    Word timing is what makes accurate re-segmentation and precise pause reconstruction
    possible later, so it is persisted even though it is not shown in the UI.

    Attributes:
        text: The word itself.
        start_ms: Start position on the media timeline.
        end_ms: End position on the media timeline.
        confidence: Recognizer confidence in ``[0, 1]``, when the provider reports one.
    """

    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        """Validate word timing and confidence.

        Raises:
            DomainError: If the timing is not a positive-length interval, or the confidence
                is outside ``[0, 1]``.
        """
        TimeInterval(self.start_ms, self.end_ms)  # raises if the timing is not sane
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            msg = f"word confidence must be within [0, 1], got {self.confidence}"
            raise DomainError(msg, text=self.text, confidence=self.confidence)

    @property
    def interval(self) -> TimeInterval:
        """Return the word's timing as an interval."""
        return TimeInterval(self.start_ms, self.end_ms)


@dataclass(frozen=True, slots=True)
class ProsodyProfile:
    """How the original narrator delivered this segment.

    Applied to a generic German voice, this reproduces delivery - pace and pauses - without
    reproducing the speaker's identity. The two are deliberately separate concerns; see
    ``docs/product/vision.md`` section 6.

    Attributes:
        speech_rate_wps: Source speaking rate in words per second.
        pause_before_ms: Silence immediately before the segment.
        pause_after_ms: Silence immediately after the segment.
        energy_rms: Mean loudness of the source speech, normalised to ``[0, 1]``.
    """

    speech_rate_wps: float
    pause_before_ms: int
    pause_after_ms: int
    energy_rms: float | None = None


@dataclass(frozen=True, slots=True)
class DurationFit:
    """How well the synthesized German speech fits its timeline slot.

    German is typically 10-30 % longer than the equivalent English, so this is the number
    that decides whether a segment is usable, needs shortening, or must be flagged for the
    user (see docs/project/questions.md Q-C6).

    Attributes:
        target_ms: The interval available on the timeline.
        generated_ms: The duration of the synthesized speech before any fitting.
        applied_rate: The time-scaling factor actually applied, ``1.0`` meaning untouched.
    """

    target_ms: int
    generated_ms: int
    applied_rate: float = 1.0

    def __post_init__(self) -> None:
        """Validate the durations.

        Raises:
            DomainError: If either duration is not positive.
        """
        if self.target_ms <= 0 or self.generated_ms <= 0:
            msg = (
                f"durations must be positive: target={self.target_ms} generated={self.generated_ms}"
            )
            raise DomainError(msg)

    @property
    def ratio(self) -> float:
        """Return generated duration divided by target duration; ``1.0`` is a perfect fit."""
        return self.generated_ms / self.target_ms

    @property
    def overrun_ms(self) -> int:
        """Return how much longer than its slot the speech is; ``0`` when it fits."""
        return max(0, self.generated_ms - self.target_ms)

    @property
    def deviation(self) -> float:
        """Return the signed relative deviation, e.g. ``0.14`` for 14 % too long."""
        return self.ratio - 1.0


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """A time-bounded stretch of narration, in English and in German.

    Attributes:
        id: Identity of the segment.
        project_id: Owning project.
        ordinal: Position in the timeline order, starting at zero. Kept explicit so the UI
            can show stable row numbers.
        interval: The segment's slot on the media timeline.
        source_text: The English text.
        source_origin: Where the English text came from.
        translation: The German text, or ``None`` before translation.
        translation_origin: Where the German text came from.
        words: Word-level timing for the English text, when available.
        prosody: The original delivery profile, when analysed.
        fit: The duration fit of the current German speech, when synthesized.
        status: Pipeline progress for this segment.
        review_state: The reviewer's verdict.
        flags: Machine-detected quality findings, e.g. ``duration_overrun``.
        confidence: Transcription confidence for the whole segment, when reported.
    """

    id: SegmentId
    project_id: ProjectId
    ordinal: int
    interval: TimeInterval
    source_text: str
    source_origin: TextOrigin
    translation: str | None = None
    translation_origin: TextOrigin | None = None
    words: tuple[Word, ...] = ()
    prosody: ProsodyProfile | None = None
    fit: DurationFit | None = None
    status: SegmentStatus = SegmentStatus.PENDING
    review_state: ReviewState = ReviewState.UNREVIEWED
    flags: frozenset[str] = frozenset()
    confidence: float | None = None

    def __post_init__(self) -> None:
        """Validate segment invariants.

        Raises:
            DomainError: If the ordinal is negative, the English text is blank, or the words
                fall outside the segment's interval or are not in order.
        """
        if self.ordinal < 0:
            msg = f"segment ordinal must not be negative, got {self.ordinal}"
            raise DomainError(msg)
        if not self.source_text.strip():
            msg = f"segment {self.ordinal} has no English text"
            raise DomainError(msg, ordinal=self.ordinal)
        # Words must be in timeline order. They are deliberately allowed to overlap:
        # recognizers routinely emit a word starting a millisecond or two before the
        # previous one ends, especially in connected speech, and that is a property of
        # real speech rather than a broken transcript. Requiring strict separation
        # rejected long real sources outright, and no consumer of `words` depends on it --
        # prosody sums durations, and reloading a segment only ever sorts by start.
        previous_start = -1
        for word in self.words:
            if word.start_ms < previous_start:
                msg = f"segment {self.ordinal} has words that are not in timeline order"
                raise DomainError(msg, ordinal=self.ordinal, word=word.text)
            previous_start = word.start_ms

    # --- construction -------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        project_id: ProjectId,
        ordinal: int,
        interval: TimeInterval,
        source_text: str,
        source_origin: TextOrigin,
        words: tuple[Word, ...] = (),
        confidence: float | None = None,
    ) -> Self:
        """Create a new, untranslated segment.

        Args:
            project_id: Owning project.
            ordinal: Timeline position, starting at zero.
            interval: The segment's slot on the timeline.
            source_text: The English text.
            source_origin: Where the English text came from.
            words: Word-level timing, when available.
            confidence: Transcription confidence for the segment.

        Returns:
            The new segment.
        """
        return cls(
            id=SegmentId(new_id()),
            project_id=project_id,
            ordinal=ordinal,
            interval=interval,
            source_text=source_text.strip(),
            source_origin=source_origin,
            words=words,
            confidence=confidence,
        )

    # --- derived properties -------------------------------------------------------------

    @property
    def duration_ms(self) -> int:
        """Return the length of the segment's timeline slot."""
        return self.interval.duration_ms

    @property
    def is_translated(self) -> bool:
        """Return whether the segment has German text."""
        return bool(self.translation and self.translation.strip())

    @property
    def has_human_translation(self) -> bool:
        """Return whether the German text was written or corrected by a person.

        Regeneration must not silently discard such a translation.
        """
        return self.translation_origin is not None and self.translation_origin.is_human

    @property
    def word_count(self) -> int:
        """Return the number of English words, from timing when available."""
        return len(self.words) if self.words else len(self.source_text.split())

    @property
    def source_speech_rate_wps(self) -> float:
        """Return the source speaking rate in words per second."""
        return self.word_count / (self.duration_ms / 1000.0)

    # --- edits --------------------------------------------------------------------------

    def with_source_text(self, text: str, *, origin: TextOrigin = TextOrigin.USER_EDIT) -> Self:
        """Return a copy with new English text.

        Changing the English text invalidates the translation and the speech downstream, so
        both are cleared here and the segment returns to ``PENDING``. Word timing is dropped
        because it no longer describes this text.

        Args:
            text: The corrected English text.
            origin: Where the new text came from.

        Returns:
            The updated segment.

        Raises:
            DomainError: If ``text`` is blank.
        """
        if not text.strip():
            msg = "English text cannot be empty"
            raise DomainError(msg, segment_id=str(self.id))
        return replace(
            self,
            source_text=text.strip(),
            source_origin=origin,
            words=(),
            translation=None,
            translation_origin=None,
            fit=None,
            status=SegmentStatus.PENDING,
            review_state=ReviewState.UNREVIEWED,
            flags=frozenset(),
        )

    def with_translation(self, text: str, *, origin: TextOrigin) -> Self:
        """Return a copy with new German text.

        Changing the German text invalidates the synthesized speech, so the fit is cleared
        and the segment falls back to ``TRANSLATED``.

        Args:
            text: The German text.
            origin: Where it came from.

        Returns:
            The updated segment.

        Raises:
            DomainError: If ``text`` is blank.
        """
        if not text.strip():
            msg = "German text cannot be empty"
            raise DomainError(msg, segment_id=str(self.id))
        return replace(
            self,
            translation=text.strip(),
            translation_origin=origin,
            fit=None,
            status=SegmentStatus.TRANSLATED,
            review_state=ReviewState.UNREVIEWED,
        )

    def with_prosody(self, prosody: ProsodyProfile) -> Self:
        """Return a copy carrying the analysed source delivery profile."""
        return replace(self, prosody=prosody)

    def with_fit(self, fit: DurationFit, *, flags: frozenset[str] = frozenset()) -> Self:
        """Return a copy recording the synthesized speech and its duration fit.

        Args:
            fit: The measured duration fit.
            flags: Quality findings raised while fitting.

        Returns:
            The updated segment, moved to ``FITTED``.
        """
        return replace(self, fit=fit, status=SegmentStatus.FITTED, flags=flags)

    def synthesized(self) -> Self:
        """Return a copy marked as having German speech, before duration fitting."""
        return replace(self, status=SegmentStatus.SYNTHESIZED)

    def failed(self, reason: str) -> Self:
        """Return a copy marked as failed.

        Args:
            reason: A short machine-readable flag naming what went wrong.

        Returns:
            The updated segment.
        """
        return replace(
            self,
            status=SegmentStatus.FAILED,
            review_state=ReviewState.NEEDS_ATTENTION,
            flags=self.flags | {reason},
        )

    def approved(self) -> Self:
        """Return a copy marked as approved by the reviewer.

        Raises:
            DomainError: If the segment has no German text to approve.
        """
        if not self.is_translated:
            msg = "cannot approve a segment that has no German text"
            raise DomainError(msg, segment_id=str(self.id), ordinal=self.ordinal)
        return replace(self, review_state=ReviewState.APPROVED)

    def reset(self) -> Self:
        """Return a copy with all generated German output discarded.

        The English text is kept, including a human correction to it; only downstream
        machine output is cleared.
        """
        return replace(
            self,
            translation=None,
            translation_origin=None,
            fit=None,
            prosody=None,
            status=SegmentStatus.PENDING,
            review_state=ReviewState.UNREVIEWED,
            flags=frozenset(),
        )

    def renumbered(self, ordinal: int) -> Self:
        """Return a copy with a new timeline position.

        Args:
            ordinal: The new zero-based position.

        Returns:
            The renumbered segment.
        """
        return replace(self, ordinal=ordinal)
