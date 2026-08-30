"""Subtitle parsing and rendering, including the round trip."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from germandubi.domain.errors import CaptionError
from germandubi.domain.subtitles import (
    parse_srt,
    parse_vtt,
    render_srt,
    render_vtt,
    wrap_subtitle_text,
)
from germandubi.domain.value_objects.timeline import TimeInterval

VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000
The important thing

00:00:04.500 --> 00:00:07.250
is the timing.
"""

SRT = """1
00:00:01,000 --> 00:00:04,000
The important thing

2
00:00:04,500 --> 00:00:07,250
is the timing.
"""


class TestParsing:
    def test_parses_webvtt(self) -> None:
        cues = parse_vtt(VTT)
        assert len(cues) == 2
        assert cues[0].interval == TimeInterval(1000, 4000)
        assert cues[1].text == "is the timing."

    def test_parses_srt(self) -> None:
        cues = parse_srt(SRT)
        assert [c.interval for c in cues] == [
            TimeInterval(1000, 4000),
            TimeInterval(4500, 7250),
        ]

    def test_ignores_the_webvtt_header_and_metadata(self) -> None:
        assert all("WEBVTT" not in c.text for c in parse_vtt(VTT))

    def test_joins_a_multi_line_cue_into_one_string(self) -> None:
        cues = parse_vtt("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nfirst line\nsecond line\n")
        assert cues[0].text == "first line second line"

    def test_accepts_the_short_mm_ss_timestamp_form(self) -> None:
        cues = parse_vtt("WEBVTT\n\n00:01.000 --> 00:04.000\ntext\n")
        assert cues[0].interval == TimeInterval(1000, 4000)

    def test_handles_windows_line_endings(self) -> None:
        assert len(parse_vtt(VTT.replace("\n", "\r\n"))) == 2

    def test_skips_a_single_malformed_cue_rather_than_failing(self) -> None:
        """One bad cue in a long automatic caption file must not fail the whole project."""
        content = (
            "WEBVTT\n\n"
            "00:00:04.000 --> 00:00:02.000\nreversed\n\n"
            "00:00:05.000 --> 00:00:06.000\nfine\n"
        )
        cues = parse_vtt(content)
        assert [c.text for c in cues] == ["fine"]

    @pytest.mark.parametrize("empty", ["", "WEBVTT\n", "not a subtitle file at all"])
    def test_refuses_a_document_with_no_cues(self, empty: str) -> None:
        with pytest.raises(CaptionError, match="no usable cues"):
            parse_vtt(empty)


class TestRendering:
    @pytest.fixture
    def cues(self) -> list[tuple[TimeInterval, str]]:
        return [
            (TimeInterval(1000, 4000), "Entscheidend ist"),
            (TimeInterval(4500, 7250), "das Timing."),
        ]

    def test_renders_srt_with_numbered_blocks(self, cues: list[tuple[TimeInterval, str]]) -> None:
        output = render_srt(cues)
        assert output.startswith("1\n00:00:01,000 --> 00:00:04,000\n")
        assert "\n2\n00:00:04,500 --> 00:00:07,250\n" in output

    def test_renders_webvtt_with_a_header_and_dots(
        self, cues: list[tuple[TimeInterval, str]]
    ) -> None:
        output = render_vtt(cues)
        assert output.startswith("WEBVTT\n")
        assert "00:00:01.000 --> 00:00:04.000" in output

    def test_refuses_to_render_nothing(self) -> None:
        with pytest.raises(CaptionError, match="empty subtitle file"):
            render_srt([])


class TestWrapping:
    def test_wraps_at_the_target_width(self) -> None:
        wrapped = wrap_subtitle_text(
            "one two three four five six seven eight nine", width=20, max_lines=5
        )
        assert len(wrapped.split("\n")) > 1
        assert all(len(line) <= 20 for line in wrapped.split("\n"))

    def test_never_breaks_a_long_german_compound(self) -> None:
        word = "Geschwindigkeitsbegrenzungsschild"
        assert word in wrap_subtitle_text(word, width=20)

    def test_respects_the_line_limit_by_overflowing_the_last_line(self) -> None:
        wrapped = wrap_subtitle_text("a " * 60, width=20, max_lines=2)
        assert len(wrapped.split("\n")) <= 2

    def test_short_text_is_left_alone(self) -> None:
        assert wrap_subtitle_text("short") == "short"


class TestRoundTrip:
    def test_srt_survives_a_render_parse_cycle(self) -> None:
        original = [(TimeInterval(1000, 4000), "Erster"), (TimeInterval(4500, 7250), "Zweiter")]
        reparsed = parse_srt(render_srt(original, wrap=False))
        assert [(c.interval, c.text) for c in reparsed] == original

    def test_vtt_survives_a_render_parse_cycle(self) -> None:
        original = [(TimeInterval(0, 2000), "Text"), (TimeInterval(3000, 5000), "Mehr")]
        reparsed = parse_vtt(render_vtt(original, wrap=False))
        assert [(c.interval, c.text) for c in reparsed] == original

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=10_000_000),
                st.integers(min_value=1, max_value=30_000),
                st.text(
                    alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
                    min_size=1,
                    max_size=40,
                ),
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_any_cue_sequence_round_trips_exactly(self, raw: list[tuple[int, int, str]]) -> None:
        cues = [(TimeInterval(start, start + length), text) for start, length, text in raw]
        reparsed = parse_srt(render_srt(cues, wrap=False))
        assert [(c.interval, c.text) for c in reparsed] == cues
