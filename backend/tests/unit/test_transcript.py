"""Caption canonicalization - the messiest input the pipeline receives."""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from germandubi.domain.errors import CaptionError
from germandubi.domain.transcript import (
    Transcript,
    TranscriptCue,
    TranscriptSource,
    canonicalize_cues,
    strip_caption_markup,
)
from germandubi.domain.value_objects.timeline import TimeInterval


def cue(start: int, end: int, text: str) -> TranscriptCue:
    return TranscriptCue(interval=TimeInterval(start, end), text=text)


@st.composite
def messy_cues(draw: st.DrawFn) -> list[TranscriptCue]:
    """Generate unordered, overlapping cues of the kind automatic captions produce."""
    count = draw(st.integers(min_value=1, max_value=12))
    cues: list[TranscriptCue] = []
    for index in range(count):
        start = draw(st.integers(min_value=0, max_value=20_000))
        length = draw(st.integers(min_value=1, max_value=5_000))
        cues.append(cue(start, start + length, f"line {index}"))
    return cues


class TestMarkupStripping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("<c.colorE5E5E5>Hello</c>", "Hello"),
            ("<00:00:01.000><c>word</c>", "word"),
            ("[Music]", ""),
            ("[APPLAUSE] Thank you.", "Thank you."),
            ("(laughs) Right then", "Right then"),
            ("Hello    there", "Hello there"),
            ("Plain text", "Plain text"),
        ],
    )
    def test_removes_styling_and_annotations(self, raw: str, expected: str) -> None:
        assert strip_caption_markup(raw) == expected


class TestCanonicalization:
    def test_orders_cues_by_start_time(self) -> None:
        result = canonicalize_cues([cue(2000, 3000, "second"), cue(0, 1000, "first")])
        assert [c.text for c in result] == ["first", "second"]

    def test_drops_cues_that_contain_only_annotations(self) -> None:
        result = canonicalize_cues([cue(0, 1000, "[Music]"), cue(1000, 2000, "Real speech")])
        assert [c.text for c in result] == ["Real speech"]

    def test_clips_an_overlapping_earlier_cue(self) -> None:
        result = canonicalize_cues([cue(0, 3000, "first"), cue(2000, 4000, "second")])
        assert result[0].end_ms == 2000
        assert result[1].start_ms == 2000

    def test_removes_the_repeated_tail_of_scrolling_automatic_captions(self) -> None:
        """YouTube auto-captions restate the previous line so the text appears to scroll."""
        result = canonicalize_cues(
            [
                cue(0, 2000, "the important thing"),
                cue(1500, 3500, "the important thing"),
                cue(3000, 5000, "is the timing"),
            ]
        )
        assert [c.text for c in result] == ["the important thing", "is the timing"]

    def test_keeps_the_longer_variant_of_a_restated_cue(self) -> None:
        result = canonicalize_cues([cue(0, 2000, "hello there my"), cue(1000, 3000, "hello there")])
        assert result[0].text == "hello there my"

    def test_refuses_captions_that_contain_no_speech(self) -> None:
        with pytest.raises(CaptionError, match="no speech text"):
            canonicalize_cues([cue(0, 1000, "[Music]"), cue(1000, 2000, "  ")])

    def test_refuses_an_empty_input(self) -> None:
        with pytest.raises(CaptionError, match="no speech text"):
            canonicalize_cues([])


class TestCanonicalProperties:
    @given(messy_cues())
    def test_output_is_ordered_and_never_overlaps(self, cues: list[TranscriptCue]) -> None:
        result = canonicalize_cues(cues)
        for earlier, later in pairwise(result):
            assert earlier.end_ms <= later.start_ms
            assert earlier.start_ms < later.start_ms

    @given(messy_cues())
    def test_every_output_cue_has_positive_duration_and_text(
        self, cues: list[TranscriptCue]
    ) -> None:
        for result in canonicalize_cues(cues):
            assert result.interval.duration_ms > 0
            assert result.text.strip()

    @given(messy_cues())
    def test_canonicalization_is_idempotent(self, cues: list[TranscriptCue]) -> None:
        once = canonicalize_cues(cues)
        assert canonicalize_cues(list(once)) == once


class TestTranscript:
    def test_from_raw_canonicalizes_its_input(self) -> None:
        transcript = Transcript.from_raw(
            [cue(2000, 4000, "second"), cue(0, 3000, "first")],
            source=TranscriptSource.AUTOMATIC_CAPTIONS,
            provider_id="test",
        )
        assert [c.text for c in transcript.cues] == ["first", "second"]

    def test_rejects_cues_that_were_never_canonicalized(self) -> None:
        with pytest.raises(CaptionError, match="canonicalize_cues was not applied"):
            Transcript(
                source=TranscriptSource.ASR,
                cues=(cue(0, 3000, "a"), cue(2000, 4000, "b")),
                provider_id="test",
            )

    def test_rejects_an_empty_transcript(self) -> None:
        with pytest.raises(CaptionError, match="at least one cue"):
            Transcript(source=TranscriptSource.ASR, cues=(), provider_id="test")

    def test_reports_the_end_of_the_last_cue_as_its_duration(self) -> None:
        transcript = Transcript.from_raw(
            [cue(0, 1000, "a"), cue(2000, 5000, "b")],
            source=TranscriptSource.ASR,
            provider_id="test",
        )
        assert transcript.duration_ms == 5000
        assert transcript.text == "a b"

    @pytest.mark.parametrize(
        ("source", "punctuated"),
        [
            (TranscriptSource.MANUAL_CAPTIONS, True),
            (TranscriptSource.ASR, True),
            (TranscriptSource.AUTOMATIC_CAPTIONS, False),
        ],
    )
    def test_only_automatic_captions_lack_reliable_punctuation(
        self, source: TranscriptSource, punctuated: bool
    ) -> None:
        assert source.has_reliable_punctuation is punctuated


class TestRedundancyRequiresTimeOverlap:
    """Regression: substring containment alone was deleting genuine narration."""

    def test_a_later_unrelated_cue_is_not_swallowed_by_a_longer_earlier_one(self) -> None:
        result = canonicalize_cues([cue(0, 1000, "line 10"), cue(1000, 3000, "line 1")])
        assert [c.text for c in result] == ["line 10", "line 1"]

    def test_a_repeated_line_at_a_different_time_is_kept(self) -> None:
        """A narrator really can say the same sentence twice."""
        result = canonicalize_cues(
            [cue(0, 2000, "Let us begin."), cue(9000, 11000, "Let us begin.")]
        )
        assert len(result) == 2

    def test_an_overlapping_restatement_is_still_removed(self) -> None:
        result = canonicalize_cues([cue(0, 2000, "the same words"), cue(1000, 3000, "the same")])
        assert len(result) == 1


class TestScrollingCaptions:
    """YouTube's rolling captions, which repeat each finished line into the next cue."""

    def test_repeated_lines_are_removed_from_a_rolling_caption_run(self) -> None:
        """The real failure: every phrase reached the dub two or three times.

        YouTube keeps a finished line on screen while the next is spoken, so it emits the
        line alone, then a zero-length restatement, then the line again followed by the
        new one. These cues abut rather than overlap, so an overlap-only check let all of
        the repetition through and segments read "For many years, archaeologists puzzled
        For many years, archaeologists puzzled over how...".
        """
        cues = [
            TranscriptCue(TimeInterval(13520, 15470), "For many years, archaeologists puzzled"),
            TranscriptCue(TimeInterval(15470, 15480), "For many years, archaeologists puzzled"),
            TranscriptCue(
                TimeInterval(15480, 17350),
                "For many years, archaeologists puzzled over how a small city managed",
            ),
            TranscriptCue(TimeInterval(17350, 17360), "over how a small city managed"),
            TranscriptCue(
                TimeInterval(17360, 20150),
                "over how a small city managed half the known world.",
            ),
        ]

        result = canonicalize_cues(cues)

        spoken = " ".join(c.text for c in result)
        assert spoken == (
            "For many years, archaeologists puzzled over how a small city managed "
            "half the known world."
        )

    def test_a_genuine_repeat_after_a_pause_is_kept(self) -> None:
        """Only a scrolling run carries text over; a real pause means real repetition."""
        cues = [
            TranscriptCue(TimeInterval(0, 2000), "we attacked at dawn"),
            TranscriptCue(TimeInterval(9000, 11000), "we attacked at dawn"),
        ]

        result = canonicalize_cues(cues)

        assert [c.text for c in result] == ["we attacked at dawn", "we attacked at dawn"]

    def test_a_cue_that_adds_nothing_is_dropped_entirely(self) -> None:
        cues = [
            TranscriptCue(TimeInterval(0, 1000), "the legion marched north"),
            TranscriptCue(TimeInterval(1000, 1010), "the legion marched north"),
            TranscriptCue(TimeInterval(1010, 3000), "the legion marched north and camped"),
        ]

        result = canonicalize_cues(cues)

        assert [c.text for c in result] == ["the legion marched north", "and camped"]
