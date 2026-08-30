"""Word-level timing for a transcript that does not carry any.

Speech recognition emits word timestamps as a by-product, so nothing extra is needed there
(``questions.md`` Q-C2). A transcript built from captions has none: captions time a whole
cue, not the words inside it. This estimates the missing timing by spreading each cue's
duration across its words in proportion to their length.

The estimate is crude and deliberately so -- it exists to give segmentation and prosody
something better than nothing, not to replace forced alignment. But it runs on every
caption-sourced project, so it is production code and is named and tested as such.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from germandubi.application.ports.providers import ProviderInfo, ProviderKind
from germandubi.domain.entities.segment import Word
from germandubi.domain.transcript import Transcript
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = ["ProportionalAlignmentProvider", "distribute_words"]


def distribute_words(text: str, interval: TimeInterval) -> tuple[Word, ...]:
    """Spread a cue's duration across its words, in proportion to word length.

    Every word stays inside the cue. A cue can hold more words than it has milliseconds --
    captions over fast speech routinely do -- and in that case the trailing words share the
    cue's last millisecond. They must not be allowed to run past the cue's end instead: the
    next cue's first word would then start earlier than this cue's last one, making the
    transcript's words non-monotonic and failing segmentation for the whole project.

    Args:
        text: The cue text.
        interval: The cue's timing.

    Returns:
        Word timing covering the interval, in non-decreasing order of start.
    """
    words = text.split()
    if not words:
        return ()
    total = sum(len(w) for w in words)
    # Every word needs a positive length, so no word may begin at the cue's final
    # millisecond boundary.
    last_start = interval.end_ms - 1
    cursor = interval.start_ms
    result: list[Word] = []
    for index, word in enumerate(words):
        is_last = index == len(words) - 1
        start = min(cursor, last_start)
        if is_last:
            end = interval.end_ms
        else:
            share = max(1, round(interval.duration_ms * len(word) / total))
            end = min(start + share, last_start)
        if end <= start:
            end = start + 1
        result.append(Word(start, end, word, confidence=0.95))
        cursor = end
    return tuple(result)


class ProportionalAlignmentProvider:
    """Fills in word timing that a caption-based transcript does not carry."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="proportional_align",
            name="Proportional word alignment",
            kind=ProviderKind.LOCAL,
            requires=(),
            notes=(
                "Estimates word timing from caption cue timing. Used only when the "
                "transcript has no word timestamps of its own."
            ),
            deterministic=True,
        )

    def is_available(self) -> bool:
        """Return that this needs nothing installed."""
        return True

    def align(self, audio: Path, transcript: Transcript) -> Transcript:
        """Distribute each cue's duration across its words.

        Args:
            audio: Ignored; kept to satisfy the port.
            transcript: The transcript to annotate.

        Returns:
            The transcript with word timing filled in.
        """
        del audio
        return replace(
            transcript,
            cues=tuple(
                replace(cue, words=cue.words or distribute_words(cue.text, cue.interval))
                for cue in transcript.cues
            ),
        )
