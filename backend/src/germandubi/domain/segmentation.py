"""Turning a transcript into dubbing segments.

A caption cue is not a good dubbing unit. Cues are cut to fit a screen, so they split
sentences mid-clause; translating those fragments independently produces German that is
grammatically wrong, because German word order depends on the whole sentence.

Segmentation therefore regroups cues into sentence-shaped units, subject to two practical
bounds: a segment must be long enough to be worth synthesizing separately, and short enough
that a duration mismatch stays correctable. Over-long sentences are split at clause
boundaries - commas, semicolons, conjunctions - which is where German tolerates a break.

The strategy is deliberately simple and is question Q-B1 in ``questions.md``: it is meant to
be measured against alternatives, not argued about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from germandubi.domain.entities.segment import SpeechSegment, Word
from germandubi.domain.errors import DomainError
from germandubi.domain.transcript import Transcript, TranscriptCue
from germandubi.domain.value_objects.identifiers import ProjectId
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = ["SegmentationOptions", "build_segments"]

#: A sentence ends at ``.``, ``!`` or ``?`` followed by whitespace, but not after a common
#: abbreviation or an initial, which would otherwise cut "Dr. Smith" in half. Any closing
#: quote or bracket belongs to the sentence that ends, so the alternation of fixed-width
#: lookbehinds keeps it there instead of consuming it as a separator.
_SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?]\")|(?<=[.!?]')|(?<=[.!?]\))|(?<=[.!?]\]))\s+")
_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "vs.", "etc.", "e.g.", "i.e.",
        "fig.", "no.", "approx.", "inc.", "ltd.", "jr.", "sr.",
    }
)  # fmt: skip
#: Where an over-long sentence may be broken without wrecking German word order.
_CLAUSE_BREAK = re.compile(r",\s+|;\s+|\s+-\s+|\s+(?:and|but|because|which|while|so)\s+")


@dataclass(frozen=True, slots=True)
class SegmentationOptions:
    """Bounds on the size of a dubbing segment.

    Attributes:
        max_duration_ms: Longest segment before it is split at a clause boundary. Long
            segments accumulate timing error and are tedious to review.
        min_duration_ms: Shortest standalone segment. Shorter fragments are merged into
            their neighbour, because a 300 ms utterance cannot be synthesized naturally.
        max_gap_ms: Longest silence that may be absorbed when merging two cues. A longer
            pause is a deliberate one and is preserved as a segment boundary.
        max_characters: Character ceiling, as a proxy for how much German text can fit.
    """

    max_duration_ms: int = 12_000
    min_duration_ms: int = 700
    max_gap_ms: int = 800
    max_characters: int = 240

    def __post_init__(self) -> None:
        """Validate the bounds.

        Raises:
            DomainError: If the bounds are not positive or are mutually contradictory.
        """
        if self.min_duration_ms <= 0 or self.max_duration_ms <= 0:
            msg = "segment duration bounds must be positive"
            raise DomainError(msg)
        if self.min_duration_ms >= self.max_duration_ms:
            msg = (
                f"min_duration_ms ({self.min_duration_ms}) must be below "
                f"max_duration_ms ({self.max_duration_ms})"
            )
            raise DomainError(msg)


def _ends_with_abbreviation(text: str) -> bool:
    """Return whether ``text`` ends in an abbreviation rather than a sentence."""
    tail = text.rsplit(None, 1)[-1].lower() if text.split() else ""
    return tail in _ABBREVIATIONS or bool(re.fullmatch(r"[a-z]\.", tail))


def split_into_sentences(text: str) -> list[str]:
    """Split English prose into sentences.

    Args:
        text: The text to split.

    Returns:
        The sentences, with surrounding whitespace removed. Text with no terminal
        punctuation - which is what automatic captions look like - is returned as one item.

    Example:
        >>> split_into_sentences("Dr. Smith arrived. It was late.")
        ['Dr. Smith arrived.', 'It was late.']
    """
    pieces = _SENTENCE_END.split(text.strip())
    sentences: list[str] = []
    for piece in pieces:
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        elif piece.strip():
            sentences.append(piece.strip())
    return sentences


def _split_long_text(text: str, limit: int) -> list[str]:
    """Break text longer than ``limit`` characters at clause boundaries.

    Falls back to splitting on whitespace when the text has no clause boundary at all, so
    the function always terminates with pieces within the limit where possible.
    """
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for token in re.split(f"({_CLAUSE_BREAK.pattern})", text):
        if not token:
            continue
        if len(current) + len(token) > limit and current.strip():
            parts.append(current.strip())
            current = token.lstrip()
        else:
            current += token
    if current.strip():
        parts.append(current.strip())
    return parts or [text]


def _interval_for(words: tuple[Word, ...], fallback: TimeInterval) -> TimeInterval:
    """Return the interval spanned by ``words``, or ``fallback`` when there is no timing."""
    if not words:
        return fallback
    return TimeInterval(words[0].start_ms, words[-1].end_ms)


@dataclass(frozen=True, slots=True)
class _Draft:
    """A segment being accumulated, before it is given identity and an ordinal."""

    interval: TimeInterval
    text: str
    words: tuple[Word, ...]
    confidence: float | None


def _merge(left: _Draft, right: _Draft) -> _Draft:
    """Merge two adjacent drafts into one covering both."""
    confidences = [c for c in (left.confidence, right.confidence) if c is not None]
    return _Draft(
        interval=left.interval.merged_with(right.interval),
        text=f"{left.text} {right.text}".strip(),
        words=left.words + right.words,
        confidence=sum(confidences) / len(confidences) if confidences else None,
    )


def _group_cues(cues: tuple[TranscriptCue, ...], options: SegmentationOptions) -> list[_Draft]:
    """Group cues into sentence-shaped drafts.

    A new draft starts when the previous cue ended a sentence, when the silence between cues
    exceeds ``max_gap_ms``, or when adding the cue would exceed the size bounds.
    """
    drafts: list[_Draft] = []
    for cue in cues:
        candidate = _Draft(cue.interval, cue.text, cue.words, cue.confidence)
        if not drafts:
            drafts.append(candidate)
            continue

        previous = drafts[-1]
        merged = _merge(previous, candidate)
        starts_new_sentence = previous.text.rstrip().endswith((".", "!", "?")) and (
            not _ends_with_abbreviation(previous.text)
        )
        too_long = (
            merged.interval.duration_ms > options.max_duration_ms
            or len(merged.text) > options.max_characters
        )
        long_pause = previous.interval.gap_to(cue.interval) > options.max_gap_ms

        if starts_new_sentence or too_long or long_pause:
            drafts.append(candidate)
        else:
            drafts[-1] = merged
    return drafts


def _split_draft(draft: _Draft, options: SegmentationOptions) -> list[_Draft]:
    """Split a draft that spans several sentences or is over the size bounds."""
    pieces = split_into_sentences(draft.text)
    if len(pieces) == 1:
        pieces = _split_long_text(draft.text, options.max_characters)
    if len(pieces) == 1:
        return [draft]

    # Distribute the draft's timing across the pieces in proportion to their length, which
    # is the best estimate available when word timing is absent.
    total = sum(len(p) for p in pieces) or 1
    results: list[_Draft] = []
    cursor = draft.interval.start_ms
    words = list(draft.words)
    for index, piece in enumerate(pieces):
        is_last = index == len(pieces) - 1
        share = round(draft.interval.duration_ms * len(piece) / total)
        end = (
            draft.interval.end_ms if is_last else min(cursor + max(share, 1), draft.interval.end_ms)
        )
        if end <= cursor:
            end = min(cursor + 1, draft.interval.end_ms)
        piece_words = tuple(w for w in words if cursor <= w.start_ms < end)
        interval = TimeInterval(cursor, end)
        results.append(
            _Draft(
                interval=_interval_for(piece_words, interval).clipped_to(interval) or interval,
                text=piece,
                words=piece_words,
                confidence=draft.confidence,
            )
        )
        cursor = end
        if cursor >= draft.interval.end_ms and not is_last:
            break
    return results or [draft]


def _absorb_short_drafts(drafts: list[_Draft], options: SegmentationOptions) -> list[_Draft]:
    """Merge drafts shorter than ``min_duration_ms`` into an adjacent one."""
    if len(drafts) <= 1:
        return drafts
    result: list[_Draft] = []
    for draft in drafts:
        if draft.interval.duration_ms < options.min_duration_ms and result:
            result[-1] = _merge(result[-1], draft)
        else:
            result.append(draft)
    # A leading short draft has no predecessor to merge into; fold it into its successor.
    if len(result) > 1 and result[0].interval.duration_ms < options.min_duration_ms:
        result[1] = _merge(result[0], result[1])
        result.pop(0)
    return result


def build_segments(
    transcript: Transcript,
    *,
    project_id: ProjectId,
    options: SegmentationOptions | None = None,
) -> tuple[SpeechSegment, ...]:
    """Build dubbing segments from a canonical transcript.

    Args:
        transcript: The canonical English transcript.
        project_id: The owning project.
        options: Size bounds for a segment. Defaults to :class:`SegmentationOptions`.

    Returns:
        Segments in timeline order, numbered from zero, with no overlaps.

    Raises:
        DomainError: If the transcript yields no usable segment.
    """
    opts = options or SegmentationOptions()

    grouped = _group_cues(transcript.cues, opts)
    split = [piece for draft in grouped for piece in _split_draft(draft, opts)]
    drafts = _absorb_short_drafts(split, opts)

    # Splitting redistributes timing by character count, which can leave a one-millisecond
    # overlap at a boundary; clip so the sequence stays strictly ordered.
    ordered: list[_Draft] = []
    for draft in drafts:
        if ordered and draft.interval.start_ms < ordered[-1].interval.end_ms:
            trimmed = ordered[-1].interval.clipped_to(
                TimeInterval(
                    ordered[-1].interval.start_ms,
                    max(draft.interval.start_ms, ordered[-1].interval.start_ms + 1),
                )
            )
            if trimmed is not None and trimmed.end_ms <= draft.interval.start_ms:
                ordered[-1] = _Draft(
                    trimmed, ordered[-1].text, ordered[-1].words, ordered[-1].confidence
                )
            else:
                ordered[-1] = _merge(ordered[-1], draft)
                continue
        ordered.append(draft)

    if not ordered:
        msg = "segmentation produced no segments from a non-empty transcript"
        raise DomainError(msg, project_id=str(project_id))

    origin = transcript.source.text_origin
    return tuple(
        SpeechSegment.create(
            project_id=project_id,
            ordinal=index,
            interval=draft.interval,
            source_text=draft.text,
            source_origin=origin,
            words=draft.words,
            confidence=draft.confidence,
        )
        for index, draft in enumerate(ordered)
    )
