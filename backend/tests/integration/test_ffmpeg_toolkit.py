"""FFmpeg toolkit against the real ffmpeg binary.

These are integration tests on purpose: the value of this adapter is entirely in whether
the filter graphs it builds are accepted and produce media of the right shape, which a
mock cannot tell us.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from germandubi.application.ports.providers import MixRequest
from germandubi.domain.errors import MediaProcessingError
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import ProcessRunner

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


@pytest.fixture
def toolkit() -> FFmpegToolkit:
    return FFmpegToolkit(ProcessRunner(default_timeout_s=120))


@pytest.fixture
def tone(toolkit: FFmpegToolkit, tmp_path: Path) -> Path:
    """A one-second 440 Hz tone, used as a stand-in for a speech clip."""
    destination = tmp_path / "tone.wav"
    toolkit.runner.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    return destination


@pytest.fixture
def clip(toolkit: FFmpegToolkit, tmp_path: Path) -> Path:
    """A five-second video with a tone, standing in for a downloaded source."""
    destination = tmp_path / "clip.mp4"
    toolkit.runner.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=15:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=5",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(destination),
        ]
    )
    return destination


class TestProbe:
    def test_reports_duration_and_streams(self, toolkit: FFmpegToolkit, clip: Path) -> None:
        info = toolkit.probe(clip)
        assert info.has_video
        assert info.duration_ms == pytest.approx(5000, abs=200)
        assert info.width == 320
        assert info.audio_codec == "aac"

    def test_a_missing_file_is_reported_clearly(
        self, toolkit: FFmpegToolkit, tmp_path: Path
    ) -> None:
        with pytest.raises(MediaProcessingError, match="does not exist"):
            toolkit.probe(tmp_path / "nope.mp4")

    def test_a_file_that_is_not_media_is_rejected(
        self, toolkit: FFmpegToolkit, tmp_path: Path
    ) -> None:
        junk = tmp_path / "junk.mp4"
        junk.write_text("this is not a video")
        with pytest.raises(MediaProcessingError):
            toolkit.probe(junk)


class TestExtraction:
    def test_extracts_mono_audio_at_the_asr_sample_rate(
        self, toolkit: FFmpegToolkit, clip: Path, tmp_path: Path
    ) -> None:
        out = toolkit.extract_audio(clip, tmp_path / "asr.wav", sample_rate=16000, mono=True)
        info = toolkit.probe(out)
        assert info.channels == 1
        assert info.sample_rate == 16000
        assert not info.has_video

    def test_extracts_stereo_master_audio(
        self, toolkit: FFmpegToolkit, clip: Path, tmp_path: Path
    ) -> None:
        out = toolkit.extract_audio(clip, tmp_path / "master.wav", sample_rate=48000, mono=False)
        assert toolkit.probe(out).channels == 2

    def test_loudness_normalization_still_produces_valid_audio(
        self, toolkit: FFmpegToolkit, clip: Path, tmp_path: Path
    ) -> None:
        out = toolkit.extract_audio(
            clip, tmp_path / "loud.wav", sample_rate=48000, mono=False, normalize_loudness=True
        )
        assert toolkit.probe(out).duration_ms > 0


class TestNarrationAssembly:
    def test_places_each_clip_at_its_own_timeline_position(
        self, toolkit: FFmpegToolkit, tone: Path, tmp_path: Path
    ) -> None:
        out = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone), (TimeInterval(3000, 4000), tone)],
            tmp_path / "narration.wav",
            total_ms=6000,
        )
        assert toolkit.probe(out).duration_ms == pytest.approx(6000, abs=100)

    def test_the_track_length_is_pinned_to_the_media_duration(
        self, toolkit: FFmpegToolkit, tone: Path, tmp_path: Path
    ) -> None:
        """A clip overrunning the end must not lengthen the track and desync the video."""
        out = toolkit.concatenate_speech(
            [(TimeInterval(4500, 5500), tone)], tmp_path / "narration.wav", total_ms=5000
        )
        assert toolkit.probe(out).duration_ms == pytest.approx(5000, abs=100)

    def test_no_segments_produces_silence_of_the_right_length(
        self, toolkit: FFmpegToolkit, tmp_path: Path
    ) -> None:
        out = toolkit.concatenate_speech([], tmp_path / "silent.wav", total_ms=3000)
        assert toolkit.probe(out).duration_ms == pytest.approx(3000, abs=100)


class TestMixing:
    def test_mixes_narration_onto_a_background_stem(
        self, toolkit: FFmpegToolkit, tone: Path, clip: Path, tmp_path: Path
    ) -> None:
        background = toolkit.extract_audio(clip, tmp_path / "bg.wav")
        narration = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone)], tmp_path / "nar.wav", total_ms=5000
        )
        out = toolkit.mix(
            MixRequest(
                narration_path=narration,
                background_path=background,
                destination=tmp_path / "mixed.wav",
            )
        )
        assert toolkit.probe(out).duration_ms > 0

    def test_ducks_the_original_audio_when_there_is_no_stem(
        self, toolkit: FFmpegToolkit, tone: Path, clip: Path, tmp_path: Path
    ) -> None:
        original = toolkit.extract_audio(clip, tmp_path / "orig.wav")
        narration = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone)], tmp_path / "nar.wav", total_ms=5000
        )
        out = toolkit.mix(
            MixRequest(
                narration_path=narration,
                original_path=original,
                destination=tmp_path / "ducked.wav",
                speech_intervals=(TimeInterval(1000, 2000),),
            )
        )
        assert toolkit.probe(out).duration_ms > 0

    def test_adjacent_speech_intervals_are_merged(
        self, toolkit: FFmpegToolkit, tone: Path, clip: Path, tmp_path: Path
    ) -> None:
        """Intervals separated by less than the merge gap collapse into one."""
        original = toolkit.extract_audio(clip, tmp_path / "orig.wav")
        narration = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone)], tmp_path / "nar.wav", total_ms=5000
        )
        intervals = tuple(TimeInterval(i * 100, i * 100 + 90) for i in range(1, 40))
        out = toolkit.mix(
            MixRequest(
                narration_path=narration,
                original_path=original,
                destination=tmp_path / "many.wav",
                speech_intervals=intervals,
            )
        )
        assert out.exists()

    def test_hundreds_of_separated_speech_intervals_still_mix(
        self, toolkit: FFmpegToolkit, tone: Path, clip: Path, tmp_path: Path
    ) -> None:
        """A 40-minute dub has hundreds of speech runs that merging cannot collapse.

        The previous version of this test spaced its intervals 10 ms apart, so all of them
        merged into a single range and the many-intervals case was never exercised. A real
        source has real pauses: 936 segments stayed separate, the enable expression grew to
        tens of kilobytes, and FFmpeg refused it with "Cannot allocate memory", failing the
        mix stage for the whole project.
        """
        original = toolkit.extract_audio(clip, tmp_path / "orig.wav")
        narration = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone)], tmp_path / "nar.wav", total_ms=5000
        )
        # Gaps far wider than the merge tolerance, so every interval survives merging.
        intervals = tuple(TimeInterval(i * 2_500, i * 2_500 + 1_800) for i in range(1, 900))

        out = toolkit.mix(
            MixRequest(
                narration_path=narration,
                original_path=original,
                destination=tmp_path / "hundreds.wav",
                speech_intervals=intervals,
            )
        )

        assert toolkit.probe(out).duration_ms > 0


class TestTimeStretch:
    @pytest.mark.parametrize("factor", [1.1, 0.9])
    def test_changes_duration_in_the_expected_direction(
        self, toolkit: FFmpegToolkit, tone: Path, tmp_path: Path, factor: float
    ) -> None:
        out = toolkit.time_stretch(tone, tmp_path / f"s{factor}.wav", factor=factor)
        assert toolkit.probe(out).duration_ms == pytest.approx(1000 / factor, rel=0.1)

    def test_chains_atempo_for_a_factor_outside_ffmpegs_range(
        self, toolkit: FFmpegToolkit, tone: Path, tmp_path: Path
    ) -> None:
        out = toolkit.time_stretch(tone, tmp_path / "fast.wav", factor=3.0)
        assert toolkit.probe(out).duration_ms == pytest.approx(333, rel=0.15)

    def test_rejects_a_non_positive_factor(
        self, toolkit: FFmpegToolkit, tone: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(MediaProcessingError, match="must be positive"):
            toolkit.time_stretch(tone, tmp_path / "bad.wav", factor=0)


class TestMux:
    def test_produces_an_mkv_with_both_audio_tracks_and_subtitles(
        self, toolkit: FFmpegToolkit, clip: Path, tone: Path, tmp_path: Path
    ) -> None:
        german = toolkit.concatenate_speech(
            [(TimeInterval(1000, 2000), tone)], tmp_path / "de.wav", total_ms=5000
        )
        original = toolkit.extract_audio(clip, tmp_path / "en.wav")
        srt = tmp_path / "de.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHallo\n", encoding="utf-8")

        out = toolkit.mux(
            video_source=clip,
            german_audio=german,
            destination=tmp_path / "out.mkv",
            original_audio=original,
            subtitles={"de": srt},
        )
        result = toolkit.runner.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv", str(out)]
        )
        assert result.stdout.count("audio") == 2
        assert "subtitle" in result.stdout
        assert "video" in result.stdout

    def test_the_video_stream_is_copied_not_re_encoded(
        self, toolkit: FFmpegToolkit, clip: Path, tone: Path, tmp_path: Path
    ) -> None:
        german = toolkit.concatenate_speech(
            [(TimeInterval(0, 1000), tone)], tmp_path / "de.wav", total_ms=5000
        )
        out = toolkit.mux(video_source=clip, german_audio=german, destination=tmp_path / "out.mkv")
        assert toolkit.probe(out).video_codec == toolkit.probe(clip).video_codec

    def test_produces_a_playable_mp4(
        self, toolkit: FFmpegToolkit, clip: Path, tone: Path, tmp_path: Path
    ) -> None:
        german = toolkit.concatenate_speech(
            [(TimeInterval(0, 1000), tone)], tmp_path / "de.wav", total_ms=5000
        )
        srt = tmp_path / "de.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHallo\n", encoding="utf-8")
        out = toolkit.mux(
            video_source=clip,
            german_audio=german,
            destination=tmp_path / "out.mp4",
            subtitles={"de": srt},
        )
        assert toolkit.probe(out).has_video
