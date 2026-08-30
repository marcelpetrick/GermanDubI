"""Probing a local media file against the real ffprobe binary.

An integration test on purpose: the whole value of this provider is whether ffprobe's
output maps onto the domain's ``SourceMedia``, which a mocked runner cannot show.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.domain.errors import SourceAcquisitionError
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import ProcessRunner
from germandubi.infrastructure.providers.localfile import LocalFileProbeProvider
from tests.fixtures.media import make_narration_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


@pytest.fixture
def provider() -> LocalFileProbeProvider:
    return LocalFileProbeProvider(FFmpegToolkit(ProcessRunner(default_timeout_s=120)))


def test_reads_duration_and_codecs_from_the_file(
    provider: LocalFileProbeProvider, tmp_path: Path
) -> None:
    clip = make_narration_video(tmp_path / "my clip.mp4", seconds=3)

    media = provider.probe(SourceRef.from_local_file(str(clip)))

    assert media.title == "my clip"
    assert 2_500 <= media.duration_ms <= 3_500
    assert media.video_codec is not None
    assert media.audio_codec is not None
    # A local file advertises no caption tracks; sidecar subtitles are a separate feature.
    assert media.captions == ()


def test_the_provider_is_local_and_needs_only_ffprobe(provider: LocalFileProbeProvider) -> None:
    assert provider.info.kind == "local"
    assert provider.is_available()


def test_a_missing_file_is_reported_clearly(
    provider: LocalFileProbeProvider, tmp_path: Path
) -> None:
    with pytest.raises(SourceAcquisitionError, match="no longer exists"):
        provider.probe(SourceRef.from_local_file(str(tmp_path / "gone.mp4")))


def test_a_file_that_is_not_media_is_reported_clearly(
    provider: LocalFileProbeProvider, tmp_path: Path
) -> None:
    text = tmp_path / "notes.mp4"
    text.write_text("this is not media")

    with pytest.raises(SourceAcquisitionError, match="could not read"):
        provider.probe(SourceRef.from_local_file(str(text)))


def test_it_refuses_a_source_it_cannot_inspect(provider: LocalFileProbeProvider) -> None:
    remote = SourceRef(
        kind=SourceKind.YOUTUBE, locator="https://www.youtube.com/watch?v=abcdefghijk"
    )

    with pytest.raises(SourceAcquisitionError, match="cannot inspect"):
        provider.probe(remote)
