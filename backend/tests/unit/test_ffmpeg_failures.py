from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from germandubi.application.ports.providers import MixRequest
from germandubi.domain.errors import ExportError, MediaProcessingError, MixError
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import CommandResult, ProcessError


class Runner:
    default_timeout_s = 10

    def __init__(self, *, stdout: str = "", fail: bool = False, installed: bool = True) -> None:
        self.stdout = stdout
        self.fail = fail
        self.installed = installed
        self.argv: list[str] = []

    def is_installed(self, _name: str) -> bool:
        return self.installed

    def run(self, argv: list[str], **_kwargs: Any) -> CommandResult:
        self.argv = argv
        if self.fail:
            raise ProcessError("tool failed")
        return CommandResult(tuple(argv), 0, self.stdout, "", 0.1)


def toolkit(runner: Runner) -> FFmpegToolkit:
    return FFmpegToolkit(runner)  # type: ignore[arg-type]


def test_availability_and_probe_error_mapping(tmp_path: Path) -> None:
    assert toolkit(Runner()).is_available()
    assert not toolkit(Runner(installed=False)).is_available()
    media = tmp_path / "media.bin"
    media.touch()

    with pytest.raises(MediaProcessingError, match="could not inspect"):
        toolkit(Runner(fail=True)).probe(media)
    with pytest.raises(MediaProcessingError, match="not JSON"):
        toolkit(Runner(stdout="invalid")).probe(media)
    with pytest.raises(MediaProcessingError, match="no usable duration"):
        toolkit(Runner(stdout=json.dumps({"format": {"duration": "bad"}}))).probe(media)

    payload = {
        "format": {},
        "streams": [
            {"codec_type": "audio", "duration": "1.5", "sample_rate": "16000", "channels": 1}
        ],
    }
    info = toolkit(Runner(stdout=json.dumps(payload))).probe(media)
    assert info.duration_ms == 1500 and info.sample_rate == 16000 and not info.has_video


def test_output_and_command_failures_are_domain_errors(tmp_path: Path) -> None:
    failed = toolkit(Runner(fail=True))
    with pytest.raises(MediaProcessingError, match="operation failed"):
        failed._run_media(["ffmpeg"], failure="operation failed")
    with pytest.raises(MediaProcessingError, match="produced no output"):
        failed._require_output(tmp_path / "missing", "operation")
    empty = tmp_path / "empty"
    empty.touch()
    with pytest.raises(MediaProcessingError, match="produced no output"):
        failed._require_output(empty, "operation")

    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")
    with pytest.raises(MixError, match="assemble"):
        failed.concatenate_speech(
            [(TimeInterval(0, 1000), clip)], tmp_path / "narration.wav", total_ms=1000
        )
    with pytest.raises(MixError, match="could not mix"):
        failed.mix(
            MixRequest(
                narration_path=clip,
                background_path=clip,
                destination=tmp_path / "mix.wav",
            )
        )
    with pytest.raises(ExportError, match="could not write"):
        failed.mux(video_source=clip, german_audio=clip, destination=tmp_path / "export.mkv")


def test_mix_without_a_bed_copies_narration(tmp_path: Path) -> None:
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"narration")
    destination = tmp_path / "mixed.wav"
    assert toolkit(Runner()).mix(MixRequest(narration, destination=destination)) == destination
    assert destination.read_bytes() == b"narration"


def test_ducking_filter_handles_empty_overlapping_and_separate_ranges() -> None:
    assert FFmpegToolkit._ducking_filter((), -18) == ""
    graph = FFmpegToolkit._ducking_filter(
        (TimeInterval(1000, 1500), TimeInterval(1600, 2000), TimeInterval(3000, 3500)), -20
    )
    assert "between(t,1.000,2.000)" in graph
    assert "between(t,3.000,3.500)" in graph
    # Few enough intervals to stay in one filter.
    assert graph.count("volume=enable") == 1


def test_ducking_filter_splits_many_intervals_across_several_filters() -> None:
    """One enable expression naming hundreds of ranges is one FFmpeg cannot evaluate.

    Chaining is only safe because merged intervals are disjoint, so at most one filter is
    enabled at a time and the attenuation never compounds.
    """
    intervals = tuple(TimeInterval(i * 2_500, i * 2_500 + 1_800) for i in range(1, 900))

    graph = FFmpegToolkit._ducking_filter(intervals, -10)

    stages = graph.count("volume=enable")
    assert stages > 1
    # Every interval is named exactly once across the chain.
    assert graph.count("between(t,") == len(intervals)
    assert max(len(stage) for stage in graph.split(",volume=enable")) < 4_000
