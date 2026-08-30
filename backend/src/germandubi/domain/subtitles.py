"""Subtitle serialization and parsing.

Both directions live here because they are pure text transformations over the timeline, and
because keeping them together makes the round trip - parse a WebVTT file, emit an SRT file -
testable as a single golden-file property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from germandubi.domain.errors import CaptionError
from germandubi.domain.transcript import TranscriptCue
from germandubi.domain.value_objects.timeline import TimeInterval, format_timestamp

__all__ = ["parse_srt", "parse_vtt", "render_srt", "render_vtt"]

# 00:00:01.000 --> 00:00:04.000  (WebVTT uses a dot, SRT a comma; accept either)
_TIMING = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)
_MAX_LINE_LENGTH: Final = 42
_MAX_LINES: Final = 2


def _parse_timestamp(value: str) -> int:
    """Parse ``HH:MM:SS,mmm`` or ``MM:SS.mmm`` into milliseconds.

    Args:
        value: The timestamp text.

    Returns:
        The position in milliseconds.

    Raises:
        CaptionError: If the timestamp cannot be parsed.
    """
    head, _, fraction = value.replace(",", ".").rpartition(".")
    parts = head.split(":")
    try:
        numbers = [int(p) for p in parts]
        millis = int(fraction.ljust(3, "0")[:3])
    except ValueError as exc:
        msg = f"malformed subtitle timestamp: {value!r}"
        raise CaptionError(msg) from exc
    if len(numbers) == 2:
        numbers.insert(0, 0)
    if len(numbers) != 3:
        msg = f"malformed subtitle timestamp: {value!r}"
        raise CaptionError(msg)
    hours, minutes, seconds = numbers
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


@dataclass(frozen=True, slots=True)
class _Block:
    """One raw cue block, before markup is stripped."""

    start_ms: int
    end_ms: int
    text: str


def _parse_blocks(content: str) -> list[_Block]:
    """Split a WebVTT or SRT document into timed blocks.

    Blocks whose timing is reversed or zero-length are skipped rather than raising, because
    a single bad cue in a long automatic caption file should not fail the whole project.
    """
    blocks: list[_Block] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        match = _TIMING.search(lines[index])
        if match is None:
            index += 1
            continue
        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            if _TIMING.search(lines[index]):
                break
            text_lines.append(lines[index].strip())
            index += 1
        text = " ".join(text_lines).strip()
        if text and end > start:
            blocks.append(_Block(start, end, text))
    return blocks


def parse_vtt(content: str) -> list[TranscriptCue]:
    """Parse a WebVTT document into raw transcript cues.

    The result is **not** canonical: automatic captions overlap and repeat. Pass the cues
    through :func:`germandubi.domain.transcript.canonicalize_cues` before use.

    Args:
        content: The WebVTT document.

    Returns:
        The raw cues, in file order.

    Raises:
        CaptionError: If the document contains no usable cue.
    """
    blocks = _parse_blocks(content)
    if not blocks:
        msg = "the WebVTT document contains no usable cues"
        raise CaptionError(msg)
    return [TranscriptCue(interval=TimeInterval(b.start_ms, b.end_ms), text=b.text) for b in blocks]


def parse_srt(content: str) -> list[TranscriptCue]:
    """Parse an SRT document into raw transcript cues.

    Args:
        content: The SRT document.

    Returns:
        The raw cues, in file order.

    Raises:
        CaptionError: If the document contains no usable cue.
    """
    blocks = _parse_blocks(content)
    if not blocks:
        msg = "the SRT document contains no usable cues"
        raise CaptionError(msg)
    return [TranscriptCue(interval=TimeInterval(b.start_ms, b.end_ms), text=b.text) for b in blocks]


def wrap_subtitle_text(
    text: str, *, width: int = _MAX_LINE_LENGTH, max_lines: int = _MAX_LINES
) -> str:
    """Wrap subtitle text to a readable width.

    German compounds are long, so a naive wrap produces a one-word second line. Words that
    exceed the width are kept on their own line rather than broken.

    Args:
        text: The subtitle text.
        width: Target maximum characters per line.
        max_lines: Maximum lines before the remainder is allowed to overflow.

    Returns:
        The text with newlines inserted.
    """
    words = text.split()
    if not words:
        return text
    lines: list[str] = [""]
    for word in words:
        candidate = f"{lines[-1]} {word}".strip()
        if len(candidate) <= width or not lines[-1]:
            lines[-1] = candidate
        elif len(lines) < max_lines:
            lines.append(word)
        else:
            lines[-1] = candidate
    return "\n".join(lines)


def render_srt(cues: list[tuple[TimeInterval, str]], *, wrap: bool = True) -> str:
    """Render cues as an SRT document.

    Args:
        cues: Interval and text pairs, in timeline order.
        wrap: Whether to wrap text to a readable line width.

    Returns:
        The SRT document, ending with a newline.

    Raises:
        CaptionError: If ``cues`` is empty.
    """
    if not cues:
        msg = "cannot render an empty subtitle file"
        raise CaptionError(msg)
    blocks = []
    for number, (interval, text) in enumerate(cues, start=1):
        body = wrap_subtitle_text(text) if wrap else text
        start = format_timestamp(interval.start_ms, separator=",")
        end = format_timestamp(interval.end_ms, separator=",")
        blocks.append(f"{number}\n{start} --> {end}\n{body}\n")
    return "\n".join(blocks)


def render_vtt(cues: list[tuple[TimeInterval, str]], *, wrap: bool = True) -> str:
    """Render cues as a WebVTT document.

    Args:
        cues: Interval and text pairs, in timeline order.
        wrap: Whether to wrap text to a readable line width.

    Returns:
        The WebVTT document, ending with a newline.

    Raises:
        CaptionError: If ``cues`` is empty.
    """
    if not cues:
        msg = "cannot render an empty subtitle file"
        raise CaptionError(msg)
    blocks = ["WEBVTT\n"]
    for interval, text in cues:
        body = wrap_subtitle_text(text) if wrap else text
        start = format_timestamp(interval.start_ms, separator=".")
        end = format_timestamp(interval.end_ms, separator=".")
        blocks.append(f"{start} --> {end}\n{body}\n")
    return "\n".join(blocks)
