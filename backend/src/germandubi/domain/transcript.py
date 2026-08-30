"""The canonical English transcript and how raw caption input is normalised into it.

Caption input is messy in specific, predictable ways. YouTube's automatic captions overlap
heavily (each cue repeats the tail of the previous one so the on-screen text scrolls),
occasionally have zero length, and are not always ordered. Feeding that directly into
segmentation produces duplicated German sentences and overlapping speech.

Canonicalization happens once, here, and its invariants are property-tested: cues are
ordered, non-empty, and never overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from itertools import pairwise
from typing import Final, Self

from germandubi.domain.entities.segment import TextOrigin, Word
from germandubi.domain.errors import CaptionError
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = ["Transcript", "TranscriptCue", "canonicalize_cues", "strip_caption_markup"]

#: Speaker labels and sound descriptions that should not be dubbed, e.g. "[Music]".
_BRACKETED = re.compile(r"\[[^\]]*\]|\([^)]*\)")
#: WebVTT inline styling and karaoke timing tags, e.g. "<c.colorE5E5E5>" or "<00:00:01.000>".
_VTT_TAGS = re.compile(r"</?[^>]+>")
_WHITESPACE = re.compile(r"\s+")
#: Automatic captions repeat the previous cue's tail; a cue that adds nothing is dropped.
_MIN_CUE_MS: Final = 1


class TranscriptSource(StrEnum):
    """Where a whole transcript came from."""

    MANUAL_CAPTIONS = "manual_captions"
    AUTOMATIC_CAPTIONS = "automatic_captions"
    ASR = "asr"

    @property
    def text_origin(self) -> TextOrigin:
        """Return the per-segment text origin implied by this transcript source."""
        return {
            TranscriptSource.MANUAL_CAPTIONS: TextOrigin.MANUAL_CAPTIONS,
            TranscriptSource.AUTOMATIC_CAPTIONS: TextOrigin.AUTOMATIC_CAPTIONS,
            TranscriptSource.ASR: TextOrigin.ASR,
        }[self]

    @property
    def has_reliable_punctuation(self) -> bool:
        """Return whether this source punctuates, which sentence segmentation depends on."""
        return self is not TranscriptSource.AUTOMATIC_CAPTIONS


def strip_caption_markup(text: str) -> str:
    """Remove styling, karaoke tags and non-speech annotations from caption text.

    Args:
        text: Raw cue text as it appears in the caption file.

    Returns:
        Plain speech text with whitespace collapsed. May be empty if the cue contained only
        an annotation such as ``[Music]``.

    Example:
        >>> strip_caption_markup("<c.colorE5E5E5>[Music] Hello   there</c>")
        'Hello there'
    """
    without_tags = _VTT_TAGS.sub(" ", text)
    without_annotations = _BRACKETED.sub(" ", without_tags)
    return _WHITESPACE.sub(" ", without_annotations).strip()


@dataclass(frozen=True, slots=True, order=True)
class TranscriptCue:
    """One timed piece of English text.

    Attributes:
        interval: When the text is spoken.
        text: The spoken text, already stripped of caption markup.
        words: Word-level timing, when the source provides it.
        confidence: Recognizer confidence for this cue, when reported.
    """

    interval: TimeInterval
    text: str
    words: tuple[Word, ...] = ()
    confidence: float | None = None

    @property
    def start_ms(self) -> int:
        """Return the cue's start position."""
        return self.interval.start_ms

    @property
    def end_ms(self) -> int:
        """Return the cue's end position."""
        return self.interval.end_ms

    def clipped_to_end(self, end_ms: int) -> Self | None:
        """Return this cue shortened to end at ``end_ms``, or ``None`` if nothing remains.

        Args:
            end_ms: The new exclusive end.

        Returns:
            The shortened cue, or ``None`` when the cue would become empty.
        """
        if end_ms - self.interval.start_ms < _MIN_CUE_MS:
            return None
        kept = tuple(w for w in self.words if w.end_ms <= end_ms)
        return replace(self, interval=self.interval.with_end(end_ms), words=kept)


def canonicalize_cues(cues: list[TranscriptCue]) -> tuple[TranscriptCue, ...]:
    """Normalise raw cues into an ordered, non-overlapping sequence.

    Applies, in order: drop cues whose text is empty after markup removal; sort by start
    time; drop a cue whose text merely repeats what the previous cue already said, which is
    how scrolling automatic captions are encoded; and clip an earlier cue that runs into a
    later one.

    Args:
        cues: Raw cues, in any order.

    Returns:
        Canonical cues satisfying: strictly increasing start times, positive duration, and
        no overlap between consecutive cues.

    Raises:
        CaptionError: If no usable cue remains.
    """
    speech = [replace(c, text=strip_caption_markup(c.text)) for c in cues]
    speech = [c for c in speech if c.text]
    if not speech:
        msg = "the captions contain no speech text after removing markup and annotations"
        raise CaptionError(msg)

    speech.sort(key=lambda c: (c.interval.start_ms, c.interval.end_ms))

    deduplicated: list[TranscriptCue] = []
    for cue in speech:
        if deduplicated and _is_redundant(previous=deduplicated[-1], current=cue):
            # Scrolling automatic captions restate the previous line; keep the longer one.
            if len(cue.text) > len(deduplicated[-1].text):
                deduplicated[-1] = replace(cue, interval=deduplicated[-1].interval)
            continue
        deduplicated.append(cue)

    clipped: list[TranscriptCue] = []
    for cue in deduplicated:
        if clipped and clipped[-1].end_ms > cue.start_ms:
            shortened = clipped[-1].clipped_to_end(cue.start_ms)
            if shortened is None:
                clipped.pop()
            else:
                clipped[-1] = shortened
        if not clipped or cue.start_ms >= clipped[-1].end_ms:
            clipped.append(cue)

    if not clipped:
        msg = "the captions collapsed to nothing once overlaps were resolved"
        raise CaptionError(msg)
    return tuple(clipped)


def _is_redundant(*, previous: TranscriptCue, current: TranscriptCue) -> bool:
    """Return whether ``current`` restates ``previous`` rather than adding new speech.

    Time overlap is the discriminator, not text alone. Scrolling automatic captions always
    overlap: the same words stay on screen across consecutive cues with shifted timings.
    Two cues that do not overlap are different speech even when one text happens to contain
    the other - without this check, a cue reading "line 1" would be swallowed by an earlier
    unrelated "line 10", silently deleting narration.
    """
    if not previous.interval.overlaps(current.interval):
        return False
    a, b = previous.text.strip(), current.text.strip()
    return a == b or b in a


@dataclass(frozen=True, slots=True)
class Transcript:
    """The canonical timed English transcript for a project.

    Attributes:
        source: Where the transcript came from.
        cues: Canonical, ordered, non-overlapping cues.
        language: Always English in ``0.x``.
        provider_id: The provider that produced it, for provenance.
        model_id: The model used, when applicable.
    """

    source: TranscriptSource
    cues: tuple[TranscriptCue, ...]
    provider_id: str
    model_id: str | None = None
    language: str = "en"
    _words_cache: tuple[Word, ...] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate that the cues are canonical.

        Raises:
            CaptionError: If the transcript is empty or its cues overlap or are unordered.
        """
        if not self.cues:
            msg = "a transcript must contain at least one cue"
            raise CaptionError(msg)
        for earlier, later in pairwise(self.cues):
            if earlier.end_ms > later.start_ms:
                msg = (
                    f"transcript cues overlap or are unordered at "
                    f"{earlier.interval} and {later.interval}; canonicalize_cues was not applied"
                )
                raise CaptionError(msg)

    @classmethod
    def from_raw(
        cls,
        cues: list[TranscriptCue],
        *,
        source: TranscriptSource,
        provider_id: str,
        model_id: str | None = None,
    ) -> Self:
        """Build a canonical transcript from raw provider cues.

        Args:
            cues: Raw cues, in any order and possibly overlapping.
            source: Where the cues came from.
            provider_id: The provider that produced them.
            model_id: The model used, when applicable.

        Returns:
            The canonical transcript.

        Raises:
            CaptionError: If no usable cue remains after canonicalization.
        """
        return cls(
            source=source,
            cues=canonicalize_cues(cues),
            provider_id=provider_id,
            model_id=model_id,
        )

    @property
    def words(self) -> tuple[Word, ...]:
        """Return every word of the transcript in timeline order."""
        return tuple(word for cue in self.cues for word in cue.words)

    @property
    def text(self) -> str:
        """Return the whole transcript as a single string."""
        return " ".join(cue.text for cue in self.cues)

    @property
    def duration_ms(self) -> int:
        """Return the position at which the last cue ends."""
        return self.cues[-1].end_ms

    @property
    def has_word_timing(self) -> bool:
        """Return whether word-level timing is available for the whole transcript."""
        return all(cue.words for cue in self.cues)
