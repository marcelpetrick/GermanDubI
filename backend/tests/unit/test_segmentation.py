"""Segmentation: turning a transcript into reviewable, dubbable units."""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from germandubi.domain.entities.segment import SpeechSegment, TextOrigin, Word
from germandubi.domain.errors import DomainError
from germandubi.domain.segmentation import (
    SegmentationOptions,
    _absorb_short_drafts,
    _Draft,
    _group_cues,
    _interval_for,
    _merge,
    _split_draft,
    _split_long_text,
    build_segments,
    split_into_sentences,
)
from germandubi.domain.transcript import Transcript, TranscriptCue, TranscriptSource
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.domain.value_objects.timeline import TimeInterval


@pytest.fixture
def project_id() -> ProjectId:
    return ProjectId(new_id())


def cue(start: int, end: int, text: str) -> TranscriptCue:
    return TranscriptCue(interval=TimeInterval(start, end), text=text)


def transcript(*cues: TranscriptCue, source: TranscriptSource = TranscriptSource.ASR) -> Transcript:
    return Transcript.from_raw(list(cues), source=source, provider_id="test")


@st.composite
def transcripts(draw: st.DrawFn) -> Transcript:
    """Generate transcripts with arbitrary but canonical timing."""
    count = draw(st.integers(min_value=1, max_value=15))
    words = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=8),
            min_size=1,
            max_size=8,
        )
    )
    cues: list[TranscriptCue] = []
    cursor = 0
    for index in range(count):
        cursor += draw(st.integers(min_value=0, max_value=2000))
        length = draw(st.integers(min_value=200, max_value=6000))
        text = " ".join(words) or f"word{index}"
        cues.append(cue(cursor, cursor + length, f"{text} {index}"))
        cursor += length
    return Transcript.from_raw(cues, source=TranscriptSource.ASR, provider_id="test")


class TestSentenceSplitting:
    def test_splits_on_terminal_punctuation(self) -> None:
        assert split_into_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]

    @pytest.mark.parametrize(
        "text",
        ["Dr. Smith arrived late.", "It cost approx. ten euros.", "See fig. 3 for details."],
    )
    def test_does_not_split_after_a_common_abbreviation(self, text: str) -> None:
        assert split_into_sentences(text) == [text]

    def test_unpunctuated_text_stays_one_sentence(self) -> None:
        """This is what automatic captions look like."""
        assert split_into_sentences("no punctuation at all here") == ["no punctuation at all here"]

    def test_one_letter_initial_is_treated_as_an_abbreviation(self) -> None:
        assert split_into_sentences("J. Smith arrived. Then left.") == [
            "J. Smith arrived.",
            "Then left.",
        ]

    def test_long_unpunctuated_text_falls_back_to_word_boundaries(self) -> None:
        pieces = _split_long_text("one two three four five six", 10)
        assert pieces == ["one two", "three four", "five six"]
        assert all(len(piece) <= 10 for piece in pieces)

    def test_short_text_is_unchanged(self) -> None:
        assert _split_long_text("short", 10) == ["short"]

    def test_handles_quotes_after_the_full_stop(self) -> None:
        assert split_into_sentences('He said "stop." Then he left.') == [
            'He said "stop."',
            "Then he left.",
        ]


class TestGrouping:
    def test_joins_cues_that_split_one_sentence(self, project_id: ProjectId) -> None:
        """A caption cue is cut to fit a screen; translating half a clause produces bad German."""
        segments = build_segments(
            transcript(
                cue(0, 2000, "The important thing about this"),
                cue(2000, 4000, "is that the timing must match."),
            ),
            project_id=project_id,
        )
        assert len(segments) == 1
        assert segments[0].source_text == (
            "The important thing about this is that the timing must match."
        )

    def test_starts_a_new_segment_after_a_completed_sentence(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 2000, "First sentence."), cue(2000, 4000, "Second sentence.")),
            project_id=project_id,
        )
        assert [s.source_text for s in segments] == ["First sentence.", "Second sentence."]

    def test_a_long_pause_ends_a_segment(self, project_id: ProjectId) -> None:
        """A deliberate pause is a boundary the narrator chose; keep it."""
        segments = build_segments(
            transcript(cue(0, 2000, "before the pause"), cue(9000, 11000, "after the pause")),
            project_id=project_id,
            options=SegmentationOptions(max_gap_ms=800),
        )
        assert len(segments) == 2

    def test_a_short_gap_is_absorbed(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 2000, "before the gap"), cue(2200, 4000, "after the gap")),
            project_id=project_id,
            options=SegmentationOptions(max_gap_ms=800),
        )
        assert len(segments) == 1


class TestBounds:
    def test_splits_a_segment_that_exceeds_the_duration_bound(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(
                cue(0, 4000, "First part of it,"),
                cue(4000, 8000, "and the second part,"),
                cue(8000, 12000, "and finally the third part"),
            ),
            project_id=project_id,
            options=SegmentationOptions(max_duration_ms=5000),
        )
        assert len(segments) > 1
        assert all(s.duration_ms <= 5000 for s in segments)

    def test_merges_a_fragment_that_is_too_short_to_synthesize(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 3000, "A full sentence here."), cue(3000, 3200, "Yes.")),
            project_id=project_id,
            options=SegmentationOptions(min_duration_ms=700),
        )
        assert len(segments) == 1
        assert "Yes." in segments[0].source_text

    def test_a_leading_fragment_is_folded_into_its_successor(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 200, "Hi."), cue(200, 4000, "Now for the real content.")),
            project_id=project_id,
            options=SegmentationOptions(min_duration_ms=700),
        )
        assert len(segments) == 1
        assert segments[0].source_text.startswith("Hi.")

    def test_a_single_short_cue_is_kept_rather_than_discarded(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 300, "Short.")),
            project_id=project_id,
            options=SegmentationOptions(min_duration_ms=700),
        )
        assert len(segments) == 1

    def test_rejects_contradictory_bounds(self) -> None:
        with pytest.raises(DomainError, match="must be below"):
            SegmentationOptions(min_duration_ms=5000, max_duration_ms=1000)

    def test_rejects_non_positive_bounds(self) -> None:
        with pytest.raises(DomainError, match="positive"):
            SegmentationOptions(min_duration_ms=0)


class TestSegmentationHelpers:
    def test_interval_uses_words_and_falls_back_without_them(self) -> None:
        fallback = TimeInterval(0, 1000)
        words = (Word(100, 300, "one"), Word(400, 800, "two"))
        assert _interval_for(words, fallback) == TimeInterval(100, 800)
        assert _interval_for((), fallback) == fallback

    def test_merge_averages_present_confidences(self) -> None:
        left = _Draft(TimeInterval(0, 500), "one", (), 0.8)
        right = _Draft(TimeInterval(500, 1000), "two", (), None)
        merged = _merge(left, right)
        assert merged.text == "one two" and merged.confidence == 0.8

    def test_grouping_starts_new_drafts_for_character_limit(self) -> None:
        cues = (cue(0, 1000, "abcdefgh"), cue(1000, 2000, "ijklmnop"))
        assert len(_group_cues(cues, SegmentationOptions(max_characters=10))) == 2

    def test_split_draft_distributes_words_and_timing(self) -> None:
        words = (Word(0, 300, "First"), Word(1000, 1400, "Second"))
        draft = _Draft(TimeInterval(0, 2000), "First. Second.", words, 0.9)
        pieces = _split_draft(draft, SegmentationOptions())
        assert [piece.text for piece in pieces] == ["First.", "Second."]
        assert pieces[0].words and pieces[1].words

    def test_absorbing_with_no_or_one_draft_is_a_noop(self) -> None:
        options = SegmentationOptions()
        draft = _Draft(TimeInterval(0, 100), "short", (), None)
        assert _absorb_short_drafts([], options) == []
        assert _absorb_short_drafts([draft], options) == [draft]


class TestResultInvariants:
    @pytest.fixture
    def many_segments(self, project_id: ProjectId) -> tuple[SpeechSegment, ...]:
        cues = [
            cue(i * 2000, i * 2000 + 1800, f"Sentence number {i} of the narration.")
            for i in range(20)
        ]
        return build_segments(transcript(*cues), project_id=project_id)

    def test_ordinals_are_dense_and_start_at_zero(
        self, many_segments: tuple[SpeechSegment, ...]
    ) -> None:
        assert [s.ordinal for s in many_segments] == list(range(len(many_segments)))

    def test_segments_are_in_timeline_order_and_never_overlap(
        self, many_segments: tuple[SpeechSegment, ...]
    ) -> None:
        for earlier, later in pairwise(many_segments):
            assert earlier.interval.end_ms <= later.interval.start_ms

    def test_every_segment_carries_the_transcript_origin(
        self, many_segments: tuple[SpeechSegment, ...]
    ) -> None:
        assert all(s.source_origin is TextOrigin.ASR for s in many_segments)

    def test_automatic_captions_are_marked_as_such(self, project_id: ProjectId) -> None:
        segments = build_segments(
            transcript(cue(0, 3000, "some auto text"), source=TranscriptSource.AUTOMATIC_CAPTIONS),
            project_id=project_id,
        )
        assert segments[0].source_origin is TextOrigin.AUTOMATIC_CAPTIONS


class TestProperties:
    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    @given(transcripts())
    def test_segments_never_overlap_and_are_ordered(self, source: Transcript) -> None:
        segments = build_segments(source, project_id=ProjectId(new_id()))
        for earlier, later in pairwise(segments):
            assert earlier.interval.end_ms <= later.interval.start_ms

    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    @given(transcripts())
    def test_every_segment_has_positive_duration_and_text(self, source: Transcript) -> None:
        for segment in build_segments(source, project_id=ProjectId(new_id())):
            assert segment.duration_ms > 0
            assert segment.source_text.strip()

    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    @given(transcripts())
    def test_segmentation_always_produces_at_least_one_segment(self, source: Transcript) -> None:
        assert build_segments(source, project_id=ProjectId(new_id()))

    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    @given(transcripts())
    def test_segments_stay_within_the_transcript_span(self, source: Transcript) -> None:
        segments = build_segments(source, project_id=ProjectId(new_id()))
        assert segments[0].interval.start_ms >= source.cues[0].start_ms
        assert segments[-1].interval.end_ms <= source.duration_ms
