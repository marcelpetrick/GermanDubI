"""The speech segment: invariants, edits and the non-destructive edit rules."""

from __future__ import annotations

import pytest

from germandubi.domain.entities.segment import (
    DurationFit,
    ReviewState,
    SegmentStatus,
    SpeechSegment,
    TextOrigin,
    Word,
)
from germandubi.domain.errors import DomainError
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.domain.value_objects.timeline import TimeInterval


@pytest.fixture
def project_id() -> ProjectId:
    return ProjectId(new_id())


@pytest.fixture
def segment(project_id: ProjectId) -> SpeechSegment:
    return SpeechSegment.create(
        project_id=project_id,
        ordinal=0,
        interval=TimeInterval(1000, 4000),
        source_text="The important thing is the timing.",
        source_origin=TextOrigin.ASR,
        words=(Word(1000, 1400, "The"), Word(1400, 2000, "important")),
    )


class TestInvariants:
    def test_rejects_a_negative_ordinal(self, project_id: ProjectId) -> None:
        with pytest.raises(DomainError, match="ordinal"):
            SpeechSegment.create(
                project_id=project_id,
                ordinal=-1,
                interval=TimeInterval(0, 1000),
                source_text="text",
                source_origin=TextOrigin.ASR,
            )

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_rejects_blank_english_text(self, project_id: ProjectId, text: str) -> None:
        with pytest.raises(DomainError, match="no English text"):
            SpeechSegment.create(
                project_id=project_id,
                ordinal=0,
                interval=TimeInterval(0, 1000),
                source_text=text,
                source_origin=TextOrigin.ASR,
            )

    def test_rejects_words_that_are_out_of_timeline_order(self, project_id: ProjectId) -> None:
        with pytest.raises(DomainError, match="not in timeline order"):
            SpeechSegment.create(
                project_id=project_id,
                ordinal=0,
                interval=TimeInterval(0, 5000),
                source_text="two words",
                source_origin=TextOrigin.ASR,
                words=(Word(2000, 3000, "two"), Word(500, 900, "words")),
            )

    def test_accepts_words_that_overlap_slightly(self, project_id: ProjectId) -> None:
        """Recognizers emit overlapping word timings on connected speech.

        Dubbing a real 40-minute source failed permanently at segmentation with "segment
        11 has words that are not in timeline order" because one word began a millisecond
        before the previous one ended. That is ordinary ASR output, not a broken
        transcript, and rejecting it made long real sources undubbable.
        """
        segment = SpeechSegment.create(
            project_id=project_id,
            ordinal=11,
            interval=TimeInterval(0, 5000),
            source_text="overlapping words",
            source_origin=TextOrigin.ASR,
            words=(Word(1000, 1500, "overlapping"), Word(1498, 2000, "words")),
        )

        assert len(segment.words) == 2

    def test_strips_surrounding_whitespace_from_the_english_text(
        self, project_id: ProjectId
    ) -> None:
        created = SpeechSegment.create(
            project_id=project_id,
            ordinal=0,
            interval=TimeInterval(0, 1000),
            source_text="  spaced  ",
            source_origin=TextOrigin.ASR,
        )
        assert created.source_text == "spaced"


class TestDerivedValues:
    def test_word_count_prefers_aligned_words(self, segment: SpeechSegment) -> None:
        assert segment.word_count == 2

    def test_word_count_falls_back_to_splitting_the_text(self, project_id: ProjectId) -> None:
        created = SpeechSegment.create(
            project_id=project_id,
            ordinal=0,
            interval=TimeInterval(0, 1000),
            source_text="one two three",
            source_origin=TextOrigin.ASR,
        )
        assert created.word_count == 3

    def test_speech_rate_is_words_per_second(self, segment: SpeechSegment) -> None:
        assert segment.source_speech_rate_wps == pytest.approx(2 / 3.0)


class TestEditsAreNonDestructive:
    def test_editing_english_clears_the_german_output(self, segment: SpeechSegment) -> None:
        translated = segment.with_translation(
            "Entscheidend ist das Timing.", origin=TextOrigin.MACHINE_TRANSLATION
        )
        edited = translated.with_source_text("The important thing is timing.")
        assert edited.translation is None
        assert edited.status is SegmentStatus.PENDING
        assert edited.source_origin is TextOrigin.USER_EDIT

    def test_editing_english_drops_stale_word_timing(self, segment: SpeechSegment) -> None:
        assert segment.with_source_text("Completely different words.").words == ()

    def test_editing_german_clears_only_the_speech(self, segment: SpeechSegment) -> None:
        fitted = segment.with_translation("Alt", origin=TextOrigin.MACHINE_TRANSLATION).with_fit(
            DurationFit(target_ms=3000, generated_ms=3200)
        )
        edited = fitted.with_translation("Neu", origin=TextOrigin.USER_EDIT)
        assert edited.source_text == segment.source_text
        assert edited.fit is None
        assert edited.status is SegmentStatus.TRANSLATED

    def test_a_human_translation_is_marked_as_such(self, segment: SpeechSegment) -> None:
        machine = segment.with_translation("Maschine", origin=TextOrigin.MACHINE_TRANSLATION)
        human = segment.with_translation("Mensch", origin=TextOrigin.USER_EDIT)
        assert not machine.has_human_translation
        assert human.has_human_translation

    def test_reset_keeps_a_corrected_english_text(self, segment: SpeechSegment) -> None:
        corrected = segment.with_source_text("Corrected English.")
        reset = corrected.with_translation("Deutsch", origin=TextOrigin.MACHINE_TRANSLATION).reset()
        assert reset.source_text == "Corrected English."
        assert reset.translation is None

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_refuses_to_blank_out_text(self, segment: SpeechSegment, blank: str) -> None:
        with pytest.raises(DomainError, match="cannot be empty"):
            segment.with_source_text(blank)
        with pytest.raises(DomainError, match="cannot be empty"):
            segment.with_translation(blank, origin=TextOrigin.USER_EDIT)

    def test_every_edit_returns_a_new_instance(self, segment: SpeechSegment) -> None:
        assert segment.with_source_text("New text.") is not segment
        assert segment.source_text == "The important thing is the timing."


class TestReview:
    def test_approving_requires_german_text(self, segment: SpeechSegment) -> None:
        with pytest.raises(DomainError, match="no German text"):
            segment.approved()

    def test_approving_a_translated_segment_succeeds(self, segment: SpeechSegment) -> None:
        translated = segment.with_translation("Deutsch", origin=TextOrigin.MACHINE_TRANSLATION)
        assert translated.approved().review_state is ReviewState.APPROVED

    def test_failure_flags_the_segment_for_attention(self, segment: SpeechSegment) -> None:
        failed = segment.failed("synthesis_failed")
        assert failed.status is SegmentStatus.FAILED
        assert failed.review_state is ReviewState.NEEDS_ATTENTION
        assert "synthesis_failed" in failed.flags


class TestDurationFit:
    def test_ratio_and_deviation_describe_the_overrun(self) -> None:
        fit = DurationFit(target_ms=1000, generated_ms=1140)
        assert fit.ratio == pytest.approx(1.14)
        assert fit.deviation == pytest.approx(0.14)
        assert fit.overrun_ms == 140

    def test_speech_shorter_than_its_slot_has_no_overrun(self) -> None:
        assert DurationFit(target_ms=2000, generated_ms=1500).overrun_ms == 0

    @pytest.mark.parametrize(("target", "generated"), [(0, 100), (100, 0), (-1, 100)])
    def test_rejects_non_positive_durations(self, target: int, generated: int) -> None:
        with pytest.raises(DomainError, match="must be positive"):
            DurationFit(target_ms=target, generated_ms=generated)


class TestWord:
    def test_rejects_reversed_timing(self) -> None:
        with pytest.raises(DomainError, match="positive duration"):
            Word(2000, 1000, "backwards")

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_rejects_confidence_outside_the_unit_interval(self, confidence: float) -> None:
        with pytest.raises(DomainError, match="within"):
            Word(0, 100, "word", confidence=confidence)
