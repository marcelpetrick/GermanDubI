from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from germandubi.application.ports.providers import ProviderInfo
from germandubi.config import Settings
from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.domain.errors import ProviderUnavailableError
from germandubi.infrastructure.providers.alignment import ProportionalAlignmentProvider
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.captions import CaptionTranscriptProvider
from germandubi.infrastructure.providers.demucs import DemucsSeparationProvider
from germandubi.infrastructure.providers.fakes import (
    FakeAcquisitionProvider,
    FakeProbeProvider,
    FakeProsodyProvider,
    FakeSeparationProvider,
    FakeTranscriptionProvider,
    FakeTranslationProvider,
    FakeTTSProvider,
)
from germandubi.infrastructure.providers.localfile import LocalFileProbeProvider
from germandubi.infrastructure.providers.piper import PiperTTSProvider
from germandubi.infrastructure.providers.prosody import TimingProsodyProvider
from germandubi.infrastructure.providers.registry import DependencyReport, ProviderRegistry
from germandubi.infrastructure.providers.whisper import WhisperTranscriptionProvider
from germandubi.infrastructure.providers.ytdlp import YtDlpAcquisitionProvider, YtDlpProbeProvider


class RegistryRunner:
    def __init__(self, installed: bool = True) -> None:
        self.installed = installed

    def is_installed(self, _name: str) -> bool:
        return self.installed

    def run(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no process should run during provider selection")


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(data_dir=tmp_path / "data", **overrides)


def _info(provider_id: str) -> ProviderInfo:
    return ProviderInfo(id=provider_id, name=provider_id)


def test_dependency_report_required_tools(tmp_path: Path) -> None:
    equipped = [(_info("argos"), True), (_info("piper"), True)]
    report = DependencyReport(
        tools={"ffmpeg": True, "ffprobe": True},
        providers=equipped,
        data_dir=tmp_path,
        writable=True,
    )
    assert report.can_dub and report.missing_required == []

    missing = DependencyReport(
        tools={"ffmpeg": False}, providers=equipped, data_dir=tmp_path, writable=False
    )
    assert not missing.can_dub and missing.missing_required == ["ffmpeg", "ffprobe"]

    # The tools are all there; the providers that turn English into German are not.
    unequipped = DependencyReport(
        tools={"ffmpeg": True, "ffprobe": True},
        providers=[],
        data_dir=tmp_path,
        writable=True,
    )
    assert not unequipped.can_dub
    assert unequipped.missing_required == []


def youtube_source() -> SourceRef:
    return SourceRef(kind=SourceKind.YOUTUBE, locator="https://www.youtube.com/watch?v=abcdefghijk")


def test_fake_selection_and_cached_media(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.mp4"
    fixture.touch()
    registry = ProviderRegistry(
        settings(
            tmp_path,
            transcription_provider="fake",
            translation_provider="fake",
            tts_provider="fake",
            separation_provider="fake",
        ),
        runner=RegistryRunner(),  # type: ignore[arg-type]
        fixture=fixture,
    )
    assert isinstance(registry.probe(youtube_source()), FakeProbeProvider)
    assert isinstance(registry.acquisition(), FakeAcquisitionProvider)
    assert isinstance(registry.transcription(), FakeTranscriptionProvider)
    assert isinstance(registry.alignment(), ProportionalAlignmentProvider)
    assert isinstance(registry.translation(), FakeTranslationProvider)
    assert isinstance(registry.tts(), FakeTTSProvider)
    assert isinstance(registry.prosody(), FakeProsodyProvider)
    assert isinstance(registry.separation(), FakeSeparationProvider)
    assert registry.media() is registry.media()


def test_real_source_and_provider_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = RegistryRunner(installed=False)
    registry = ProviderRegistry(settings(tmp_path), runner=runner)  # type: ignore[arg-type]

    # Force every optional provider to look absent rather than assuming it is. Without
    # this the fallback assertions below silently depend on whether the developer happens
    # to have run `make install-providers`: they pass in CI, which never installs the
    # extras, and fail on a machine set up to produce a real dub.
    for absent in (
        ArgosTranslationProvider,
        PiperTTSProvider,
        DemucsSeparationProvider,
        WhisperTranscriptionProvider,
    ):
        monkeypatch.setattr(absent, "is_available", lambda _self: False)

    assert isinstance(registry.probe(youtube_source()), FakeProbeProvider)
    assert isinstance(registry.acquisition(), YtDlpAcquisitionProvider)
    assert isinstance(registry.prosody(), TimingProsodyProvider)

    # Translation and speech have no acceptable substitute: the placeholders do not
    # translate and do not speak. Falling back to them silently produced a dub that looked
    # finished and contained no German, so their absence is now fatal and says what to run.
    with pytest.raises(ProviderUnavailableError, match="uv sync --extra translate"):
        registry.translation()
    with pytest.raises(ProviderUnavailableError, match="uv sync --extra tts"):
        registry.tts()

    # Separation is different: without it the mix ducks the original instead of removing
    # it, which is a worse dub but still a real one. That fallback stays.
    assert registry.separation() is None

    monkeypatch.setattr(YtDlpProbeProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(DemucsSeparationProvider, "is_available", lambda _self: True)
    assert isinstance(registry.probe(youtube_source()), YtDlpProbeProvider)
    assert isinstance(registry.translation(), ArgosTranslationProvider)
    assert isinstance(registry.tts(), PiperTTSProvider)
    assert isinstance(registry.separation(), DemucsSeparationProvider)

    # A downloader cannot inspect a file that is already on disk. Selecting one for a
    # local source failed every local-file project at the very first stage.
    local = SourceRef.from_local_file("/media/clip.mp4")
    monkeypatch.setattr(LocalFileProbeProvider, "is_available", lambda _self: True)
    assert isinstance(registry.probe(local), LocalFileProbeProvider)
    monkeypatch.setattr(LocalFileProbeProvider, "is_available", lambda _self: False)
    assert isinstance(registry.probe(local), FakeProbeProvider)

    none = ProviderRegistry(settings(tmp_path, separation_provider="none"), runner=runner)  # type: ignore[arg-type]
    assert none.separation() is None


def test_caption_selection_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manual_path = tmp_path / "manual.vtt"
    manual_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n")
    auto_path = tmp_path / "auto.vtt"
    auto_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")
    registry = ProviderRegistry(settings(tmp_path), runner=RegistryRunner())  # type: ignore[arg-type]

    assert isinstance(registry.transcription(caption_path=manual_path), CaptionTranscriptProvider)
    monkeypatch.setattr(WhisperTranscriptionProvider, "is_available", lambda _self: True)
    assert isinstance(
        registry.transcription(caption_path=auto_path, caption_is_automatic=True),
        WhisperTranscriptionProvider,
    )
    monkeypatch.setattr(WhisperTranscriptionProvider, "is_available", lambda _self: False)
    assert isinstance(
        registry.transcription(caption_path=auto_path, caption_is_automatic=True),
        CaptionTranscriptProvider,
    )
    # No recognition and no usable captions means there is no transcript to dub from.
    auto_path.write_text("")
    with pytest.raises(ProviderUnavailableError, match="uv sync --extra asr"):
        registry.transcription(caption_path=auto_path, caption_is_automatic=True)


def test_report_covers_available_and_unwritable_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(YtDlpProbeProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(WhisperTranscriptionProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(DemucsSeparationProvider, "is_available", lambda _self: False)
    registry = ProviderRegistry(settings(tmp_path), runner=RegistryRunner())  # type: ignore[arg-type]
    report = registry.report()
    # Every selectable provider is reported, not only the optional extras: a report that
    # omits one is a report a user cannot use to work out what will actually run.
    assert report.writable
    assert {info.id for info, _ in report.providers} == {
        "yt_dlp_probe",
        "local_file_probe",
        "faster_whisper",
        "argos",
        "piper",
        "demucs",
        "timing_prosody",
        "proportional_align",
    }

    def fail_directories(_self: Settings) -> None:
        raise OSError("read only")

    monkeypatch.setattr(Settings, "ensure_directories", fail_directories)
    assert registry.report().writable is False


def test_readiness_requires_a_real_translator_and_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`doctor` said "Ready to dub" on a machine that could only produce placeholders.

    FFmpeg alone was treated as sufficient, so the one command a user runs to check their
    setup confirmed it was fine, and the dub came out as quiet tones over English.
    """
    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(DemucsSeparationProvider, "is_available", lambda _self: False)
    registry = ProviderRegistry(settings(tmp_path), runner=RegistryRunner())  # type: ignore[arg-type]

    report = registry.report()

    assert not report.can_dub
    assert not report.missing_required  # the external tools are all present
    assert len(report.missing_for_a_real_dub) == 2

    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: True)
    ready = ProviderRegistry(settings(tmp_path), runner=RegistryRunner()).report()  # type: ignore[arg-type]

    # Separation stays absent, and that is still a real dub: the mix ducks instead.
    assert ready.can_dub and not ready.missing_for_a_real_dub
