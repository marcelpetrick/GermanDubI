"""Narrator delivery analysis.

The MVP reproduces *delivery* - speaking rate and pause structure - rather than voice
identity. Those are deliberately separate concerns: matching pace and pauses needs no
authorization and applies to any stock German voice, while reproducing a recognizable voice
does need authorization and is an optional capability (``vision.md`` section 6).

Rate and pauses are measured from word timing, which the pipeline already has, so this
stage costs nothing and needs no model. Loudness is measured with FFmpeg when available.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

from germandubi.application.ports.providers import ProviderInfo, ProviderKind
from germandubi.domain.entities.segment import ProsodyProfile, Word
from germandubi.domain.value_objects.timeline import TimeInterval, ms_to_seconds
from germandubi.infrastructure.processes.runner import ProcessError, ProcessRunner

__all__ = ["TimingProsodyProvider"]

logger = logging.getLogger(__name__)

_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
#: Below this the segment is effectively silent; above it, effectively full scale.
_QUIET_DB: Final = -60.0
_LOUD_DB: Final = 0.0


class TimingProsodyProvider:
    """Derives a delivery profile from word timing, and loudness from the audio."""

    def __init__(self, runner: ProcessRunner | None = None, *, ffmpeg: str = "ffmpeg") -> None:
        """Initialise the provider.

        Args:
            runner: Process runner used for the loudness measurement. When ``None``,
                loudness is not measured and the rest still works.
            ffmpeg: Name or path of the ``ffmpeg`` executable.
        """
        self.runner = runner
        self.ffmpeg = ffmpeg

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="timing_prosody",
            name="Timing-based prosody analysis",
            kind=ProviderKind.LOCAL,
            deterministic=True,
            notes="Matches speaking rate and pauses. Does not reproduce voice identity.",
        )

    def is_available(self) -> bool:
        """Return that this provider needs no model and is always available."""
        return True

    def analyse(
        self, audio: Path, interval: TimeInterval, *, words: tuple[Word, ...] = ()
    ) -> ProsodyProfile:
        """Measure how the narrator delivered one segment.

        Args:
            audio: The master audio file.
            interval: The segment's slot on the timeline.
            words: Word timing for the segment, when available.

        Returns:
            The measured delivery profile. Falls back to timing-only values when the audio
            cannot be measured, because a missing loudness figure must not fail a stage.
        """
        speaking_ms = _speaking_time_ms(words) or interval.duration_ms
        rate = (len(words) / (speaking_ms / 1000.0)) if words else 0.0
        return ProsodyProfile(
            speech_rate_wps=rate,
            pause_before_ms=_leading_silence_ms(words, interval),
            pause_after_ms=_trailing_silence_ms(words, interval),
            energy_rms=self._loudness(audio, interval),
        )

    def _loudness(self, audio: Path, interval: TimeInterval) -> float | None:
        """Return the segment's mean loudness normalised into ``[0, 1]``, or ``None``."""
        if self.runner is None or not audio.exists():
            return None
        try:
            result = self.runner.run(
                [
                    self.ffmpeg,
                    "-nostdin",
                    "-ss",
                    f"{ms_to_seconds(interval.start_ms):.3f}",
                    "-t",
                    f"{ms_to_seconds(interval.duration_ms):.3f}",
                    "-i",
                    str(audio),
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                timeout_s=60,
                check=False,
            )
        except (ProcessError, OSError):
            return None

        match = _MEAN_VOLUME.search(result.stderr)
        if match is None:
            return None
        decibels = float(match.group(1))
        span = _LOUD_DB - _QUIET_DB
        return round(min(1.0, max(0.0, (decibels - _QUIET_DB) / span)), 4)


def _speaking_time_ms(words: tuple[Word, ...]) -> int:
    """Return the time actually spent speaking, excluding pauses between words."""
    return sum(word.end_ms - word.start_ms for word in words)


def _leading_silence_ms(words: tuple[Word, ...], interval: TimeInterval) -> int:
    """Return the silence between the segment's start and its first word."""
    return max(0, words[0].start_ms - interval.start_ms) if words else 0


def _trailing_silence_ms(words: tuple[Word, ...], interval: TimeInterval) -> int:
    """Return the silence between the last word and the segment's end."""
    return max(0, interval.end_ms - words[-1].end_ms) if words else 0
