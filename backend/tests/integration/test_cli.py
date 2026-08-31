from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from typer.testing import CliRunner

import germandubi.cli.main as cli
from germandubi.composition import Application, build_application
from germandubi.config import Settings
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.piper import PiperTTSProvider
from tests.fixtures.media import make_narration_video

runner = CliRunner()


@pytest.fixture(scope="module")
def cli_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required")
    return make_narration_video(tmp_path_factory.mktemp("cli") / "clip.mp4", seconds=10)


@pytest.fixture
def settings(tmp_path: Path, cli_clip: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        transcription_provider="fake",
        translation_provider="fake",
        tts_provider="fake",
        separation_provider="fake",
        fake_media_fixture=cli_clip,
    )


@pytest.fixture
def application(settings: Settings) -> Iterator[Application]:
    wired = build_application(settings)
    yield wired
    wired.dispose()


def bind_application(monkeypatch: pytest.MonkeyPatch, application: Application) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: application.settings)
    monkeypatch.setattr(cli, "build_application", lambda *args, **kwargs: application)


def test_version_reports_the_vcs_build() -> None:
    result = runner.invoke(cli.app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.startswith("GermanDubI ")


def test_doctor_reports_tools_and_provider_privacy(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    bind_application(monkeypatch, application)
    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: True)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: True)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "External tools" in result.stdout
    assert "Providers" in result.stdout
    assert "Ready to dub" in result.stdout


def test_doctor_refuses_to_report_readiness_without_a_translator_or_voice(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    """The one command a user runs to check their setup must not bless a broken one.

    It previously printed "Ready to dub" whenever FFmpeg was present, so a machine with no
    translation and no German voice was declared fine and produced quiet tones over
    English narration.
    """
    bind_application(monkeypatch, application)
    monkeypatch.setattr(ArgosTranslationProvider, "is_available", lambda _self: False)
    monkeypatch.setattr(PiperTTSProvider, "is_available", lambda _self: False)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "Ready to dub" not in result.stdout
    assert "make install-providers" in result.output


def test_list_and_inspect_projects(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    project = application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")
    bind_application(monkeypatch, application)

    listed = runner.invoke(cli.app, ["list"])
    inspected = runner.invoke(cli.app, ["inspect", str(project.id)])

    assert listed.exit_code == 0
    assert str(project.id) in listed.stdout
    assert inspected.exit_code == 0
    assert "state:" in inspected.stdout
    assert "this project has never been processed" in inspected.stdout


def test_list_explains_when_there_are_no_projects(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    bind_application(monkeypatch, application)

    result = runner.invoke(cli.app, ["list"])

    assert result.exit_code == 0
    assert "no projects yet" in result.stdout


def test_inspect_rejects_a_malformed_identifier(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    bind_application(monkeypatch, application)

    result = runner.invoke(cli.app, ["inspect", "not-an-id"])

    assert result.exit_code == 1
    assert "not a valid project identifier" in result.stderr


def test_worker_once_drains_an_empty_queue(
    monkeypatch: pytest.MonkeyPatch, application: Application
) -> None:
    bind_application(monkeypatch, application)

    result = runner.invoke(cli.app, ["worker", "--once"])

    assert result.exit_code == 0
    assert "processed 0 job(s)" in result.stdout


def test_serve_passes_runtime_settings_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    called: dict[str, Any] = {}
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: called.update(kwargs))

    result = runner.invoke(cli.app, ["serve", "--host", "127.0.0.2", "--port", "9876"])

    assert result.exit_code == 0
    assert called["host"] == "127.0.0.2"
    assert called["port"] == 9876
    assert called["factory"] is True


def test_dub_runs_the_fake_pipeline_and_prints_the_export(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, cli_clip: Path
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    result = runner.invoke(cli.app, ["dub", str(cli_clip)])

    assert result.exit_code == 0, result.output
    assert "Fake narration clip" in result.stdout
    assert "exported:" in result.stdout
    assert "german_dub.mkv" in result.stdout
