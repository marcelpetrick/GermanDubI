from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from germandubi.config import Settings
from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.captions import CaptionTranscriptProvider
from germandubi.infrastructure.providers.demucs import DemucsSeparationProvider
from germandubi.infrastructure.providers.fakes import (
    FakeAcquisitionProvider,
    FakeAlignmentProvider,
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


def test_dependency_report_required_tools(tmp_path: Path) -> None:
    report = DependencyReport(
        tools={"ffmpeg": True, "ffprobe": True}, providers=[], data_dir=tmp_path, writable=True
    )
    assert report.can_dub and report.missing_required == []
    missing = DependencyReport(
        tools={"ffmpeg": False}, providers=[], data_dir=tmp_path, writable=False
    )
    assert not missing.can_dub and missing.missing_required == ["ffmpeg", "ffprobe"]


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
    assert isinstance(registry.alignment(), FakeAlignmentProvider)
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
    assert isinstance(registry.translation(), FakeTranslationProvider)
    assert isinstance(registry.tts(), FakeTTSProvider)
    assert isinstance(registry.prosody(), TimingProsodyProvider)
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
    auto_path.write_text("")
    assert isinstance(
        registry.transcription(caption_path=auto_path, caption_is_automatic=True),
        FakeTranscriptionProvider,
    )


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
    assert report.writable and len(report.providers) == 6 and report.can_dub

    def fail_directories(_self: Settings) -> None:
        raise OSError("read only")

    monkeypatch.setattr(Settings, "ensure_directories", fail_directories)
    assert registry.report().writable is False
