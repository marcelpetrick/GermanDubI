"""Timeline arithmetic in integer milliseconds.

Timeline positions are **never** stored or compared as floating-point seconds. Binary
floating point cannot represent most frame and sample boundaries exactly, and the resulting
drift shows up as audible desynchronization once thousands of segments are concatenated.
Conversion from provider output happens once, at the boundary, in :func:`seconds_to_ms`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Self

from germandubi.domain.errors import DomainError

__all__ = ["TimeInterval", "format_timestamp", "ms_to_seconds", "seconds_to_ms"]


def seconds_to_ms(seconds: float) -> int:
    """Convert a provider's floating-point seconds to integer milliseconds.

    Rounds half away from zero, so that a boundary value converts identically regardless of
    the platform's banker's-rounding behaviour.

    Args:
        seconds: A time in seconds, as produced by FFmpeg or an ML provider.

    Returns:
        The equivalent whole number of milliseconds.

    Raises:
        DomainError: If ``seconds`` is not finite.
    """
    if not math.isfinite(seconds):
        msg = f"timeline position must be finite, got {seconds!r}"
        raise DomainError(msg)
    return math.floor(seconds * 1000 + 0.5) if seconds >= 0 else -math.floor(-seconds * 1000 + 0.5)


def ms_to_seconds(milliseconds: int) -> float:
    """Convert integer milliseconds back to seconds for an external tool.

    Args:
        milliseconds: A duration or position in milliseconds.

    Returns:
        The equivalent value in seconds.
    """
    return milliseconds / 1000.0


def format_timestamp(milliseconds: int, *, separator: str = ",") -> str:
    """Format a position as a subtitle timestamp, ``HH:MM:SS,mmm``.

    Args:
        milliseconds: Position on the timeline. Must not be negative.
        separator: ``","`` for SRT, ``"."`` for WebVTT.

    Returns:
        The formatted timestamp.

    Raises:
        DomainError: If ``milliseconds`` is negative.
    """
    if milliseconds < 0:
        msg = f"cannot format a negative timestamp: {milliseconds}"
        raise DomainError(msg)
    seconds, millis = divmod(milliseconds, 1000)
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}{separator}{millis:03d}"


@dataclass(frozen=True, slots=True, order=True)
class TimeInterval:
    """A half-open interval ``[start_ms, end_ms)`` on the media timeline.

    Half-open is what makes adjacent intervals composable: the end of one segment is the
    start of the next, with no shared millisecond and no gap.

    Attributes:
        start_ms: Inclusive start, in milliseconds from the beginning of the media.
        end_ms: Exclusive end, in milliseconds. Strictly greater than ``start_ms``.
    """

    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        """Enforce the interval invariants.

        Raises:
            DomainError: If the interval starts before zero or is empty or reversed.
        """
        if self.start_ms < 0:
            msg = f"interval starts before the media: start_ms={self.start_ms}"
            raise DomainError(msg, start_ms=self.start_ms)
        if self.end_ms <= self.start_ms:
            msg = f"interval must have positive duration: [{self.start_ms}, {self.end_ms})"
            raise DomainError(msg, start_ms=self.start_ms, end_ms=self.end_ms)

    @classmethod
    def from_seconds(cls, start: float, end: float) -> Self:
        """Build an interval from a provider's floating-point seconds.

        Args:
            start: Start position in seconds.
            end: End position in seconds.

        Returns:
            The equivalent millisecond interval.
        """
        return cls(seconds_to_ms(start), seconds_to_ms(end))

    @property
    def duration_ms(self) -> int:
        """Return the length of the interval in milliseconds."""
        return self.end_ms - self.start_ms

    def overlaps(self, other: TimeInterval) -> bool:
        """Return whether this interval shares at least one millisecond with ``other``."""
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms

    def contains(self, position_ms: int) -> bool:
        """Return whether ``position_ms`` falls inside the half-open interval."""
        return self.start_ms <= position_ms < self.end_ms

    def gap_to(self, other: TimeInterval) -> int:
        """Return the silence between this interval and a later one.

        Args:
            other: An interval that starts at or after this one ends.

        Returns:
            The gap in milliseconds; ``0`` when the intervals touch or overlap.
        """
        return max(0, other.start_ms - self.end_ms)

    def shifted(self, delta_ms: int) -> TimeInterval:
        """Return this interval moved along the timeline by ``delta_ms``.

        Args:
            delta_ms: Signed offset in milliseconds.

        Returns:
            The shifted interval.

        Raises:
            DomainError: If the shift would move the interval before zero.
        """
        return TimeInterval(self.start_ms + delta_ms, self.end_ms + delta_ms)

    def with_end(self, end_ms: int) -> TimeInterval:
        """Return a copy of this interval ending at ``end_ms``.

        Args:
            end_ms: The new exclusive end.

        Returns:
            The adjusted interval.

        Raises:
            DomainError: If the resulting interval would be empty or reversed.
        """
        return TimeInterval(self.start_ms, end_ms)

    def clipped_to(self, limit: TimeInterval) -> TimeInterval | None:
        """Return the part of this interval that lies within ``limit``.

        Args:
            limit: The bounding interval, typically the full media duration.

        Returns:
            The clipped interval, or ``None`` when the two do not overlap at all.
        """
        start = max(self.start_ms, limit.start_ms)
        end = min(self.end_ms, limit.end_ms)
        return TimeInterval(start, end) if end > start else None

    def split_at(self, position_ms: int) -> tuple[TimeInterval, TimeInterval]:
        """Split this interval into two adjacent intervals.

        Args:
            position_ms: The split point, strictly inside the interval.

        Returns:
            The interval before and the interval after the split point.

        Raises:
            DomainError: If ``position_ms`` is not strictly inside the interval.
        """
        if not (self.start_ms < position_ms < self.end_ms):
            msg = (
                f"split point {position_ms} is not strictly inside [{self.start_ms}, {self.end_ms})"
            )
            raise DomainError(msg)
        return TimeInterval(self.start_ms, position_ms), TimeInterval(position_ms, self.end_ms)

    def merged_with(self, other: TimeInterval) -> TimeInterval:
        """Return the smallest interval covering both this interval and ``other``.

        Args:
            other: The interval to merge with.

        Returns:
            The covering interval, including any gap between the two.
        """
        return TimeInterval(min(self.start_ms, other.start_ms), max(self.end_ms, other.end_ms))

    def __str__(self) -> str:
        """Return a compact human-readable form, e.g. ``00:02:14,500-00:02:17,000``."""
        return f"{format_timestamp(self.start_ms)}-{format_timestamp(self.end_ms)}"
