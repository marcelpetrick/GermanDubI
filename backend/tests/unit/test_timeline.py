"""Timeline arithmetic: the invariants everything downstream relies on."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from germandubi.domain.errors import DomainError
from germandubi.domain.value_objects.timeline import (
    TimeInterval,
    format_timestamp,
    ms_to_seconds,
    seconds_to_ms,
)

positions = st.integers(min_value=0, max_value=6 * 60 * 60 * 1000)


@st.composite
def intervals(draw: st.DrawFn) -> TimeInterval:
    start = draw(positions)
    length = draw(st.integers(min_value=1, max_value=600_000))
    return TimeInterval(start, start + length)


class TestConstruction:
    def test_rejects_a_negative_start(self) -> None:
        with pytest.raises(DomainError, match="before the media"):
            TimeInterval(-1, 100)

    @pytest.mark.parametrize(("start", "end"), [(100, 100), (200, 100)])
    def test_rejects_an_empty_or_reversed_interval(self, start: int, end: int) -> None:
        with pytest.raises(DomainError, match="positive duration"):
            TimeInterval(start, end)

    def test_from_seconds_rounds_to_the_nearest_millisecond(self) -> None:
        assert TimeInterval.from_seconds(1.2345, 2.9999) == TimeInterval(1235, 3000)


class TestSecondsConversion:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0.0, 0), (1.0, 1000), (0.0005, 1), (0.0004, 0), (1.2345, 1235), (-1.5, -1500)],
    )
    def test_rounds_half_away_from_zero(self, seconds: float, expected: int) -> None:
        assert seconds_to_ms(seconds) == expected

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite_input(self, bad: float) -> None:
        with pytest.raises(DomainError, match="finite"):
            seconds_to_ms(bad)

    @given(st.integers(min_value=0, max_value=10**9))
    def test_round_trips_through_seconds(self, milliseconds: int) -> None:
        assert seconds_to_ms(ms_to_seconds(milliseconds)) == milliseconds


class TestFormatting:
    @pytest.mark.parametrize(
        ("milliseconds", "expected"),
        [
            (0, "00:00:00,000"),
            (1, "00:00:00,001"),
            (61_001, "00:01:01,001"),
            (3_723_456, "01:02:03,456"),
        ],
    )
    def test_formats_a_subtitle_timestamp(self, milliseconds: int, expected: str) -> None:
        assert format_timestamp(milliseconds) == expected

    def test_uses_a_dot_for_webvtt(self) -> None:
        assert format_timestamp(1500, separator=".") == "00:00:01.500"

    def test_refuses_a_negative_position(self) -> None:
        with pytest.raises(DomainError, match="negative"):
            format_timestamp(-1)


class TestOperations:
    def test_duration_is_the_half_open_length(self) -> None:
        assert TimeInterval(1000, 2500).duration_ms == 1500

    @pytest.mark.parametrize(
        ("other", "overlaps"),
        [((1500, 2500), True), ((2000, 3000), False), ((0, 1000), False), ((1999, 2001), True)],
    )
    def test_overlap_treats_the_end_as_exclusive(
        self, other: tuple[int, int], overlaps: bool
    ) -> None:
        assert TimeInterval(1000, 2000).overlaps(TimeInterval(*other)) is overlaps

    def test_contains_excludes_the_end_position(self) -> None:
        interval = TimeInterval(1000, 2000)
        assert interval.contains(1000)
        assert interval.contains(1999)
        assert not interval.contains(2000)

    def test_gap_is_zero_for_touching_intervals(self) -> None:
        assert TimeInterval(0, 1000).gap_to(TimeInterval(1000, 2000)) == 0
        assert TimeInterval(0, 1000).gap_to(TimeInterval(1500, 2000)) == 500

    def test_clipping_returns_none_when_disjoint(self) -> None:
        assert TimeInterval(0, 1000).clipped_to(TimeInterval(2000, 3000)) is None

    def test_clipping_truncates_to_the_limit(self) -> None:
        assert TimeInterval(0, 5000).clipped_to(TimeInterval(1000, 3000)) == TimeInterval(
            1000, 3000
        )

    def test_split_produces_adjacent_intervals(self) -> None:
        left, right = TimeInterval(0, 1000).split_at(400)
        assert (left, right) == (TimeInterval(0, 400), TimeInterval(400, 1000))

    @pytest.mark.parametrize("position", [0, 1000, 1500, -5])
    def test_split_rejects_a_point_outside_the_interval(self, position: int) -> None:
        with pytest.raises(DomainError, match="not strictly inside"):
            TimeInterval(0, 1000).split_at(position)

    def test_merge_covers_the_gap_between_intervals(self) -> None:
        merged = TimeInterval(0, 100).merged_with(TimeInterval(500, 600))
        assert merged == TimeInterval(0, 600)


class TestProperties:
    @given(intervals())
    def test_duration_is_always_positive(self, interval: TimeInterval) -> None:
        assert interval.duration_ms > 0

    @given(intervals(), st.integers(min_value=1, max_value=1000))
    def test_split_preserves_total_duration(self, interval: TimeInterval, offset: int) -> None:
        if interval.duration_ms <= offset:
            return
        left, right = interval.split_at(interval.start_ms + offset)
        assert left.duration_ms + right.duration_ms == interval.duration_ms
        assert left.end_ms == right.start_ms

    @given(intervals(), intervals())
    def test_merge_covers_both_operands(self, a: TimeInterval, b: TimeInterval) -> None:
        merged = a.merged_with(b)
        assert merged.start_ms <= min(a.start_ms, b.start_ms)
        assert merged.end_ms >= max(a.end_ms, b.end_ms)

    @given(intervals(), st.integers(min_value=0, max_value=100_000))
    def test_shifting_preserves_duration(self, interval: TimeInterval, delta: int) -> None:
        assert interval.shifted(delta).duration_ms == interval.duration_ms

    @given(intervals(), intervals())
    def test_clipping_never_grows_an_interval(
        self, interval: TimeInterval, limit: TimeInterval
    ) -> None:
        clipped = interval.clipped_to(limit)
        if clipped is not None:
            assert clipped.duration_ms <= interval.duration_ms
            assert clipped.start_ms >= interval.start_ms
            assert clipped.end_ms <= interval.end_ms
