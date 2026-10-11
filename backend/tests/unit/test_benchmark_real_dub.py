"""The real-dub script's contract with the workflow that runs it.

The weekly real-provider workflow tells "the product is broken" from "YouTube refused this
runner" by exit status alone, so that status is tested here rather than discovered on the
next scheduled run.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "benchmark_real_dub.py"

_BOT_CHECK = (
    "ERROR: [youtube] f3r05guSo1w: Sign in to confirm you\u2019re not a bot. "
    "Use --cookies-from-browser or --cookies for the authentication."
)


@pytest.fixture(scope="module")
def script() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("benchmark_real_dub", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up by name, so it must be registered to load at all.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


def _failing(message: str) -> list[str]:
    return ["sh", "-c", 'printf "%s\\n" "$1" >&2; exit 1', "sh", message]


def test_a_bot_check_ends_the_run_with_its_own_status(script: ModuleType) -> None:
    with pytest.raises(SystemExit) as raised:
        script._run_or_fail(_failing(_BOT_CHECK), what="download the source")

    assert raised.value.code == script.EXIT_SOURCE_REFUSED


def test_a_bot_check_is_not_retried(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "_RETRY_PAUSE_S", 0)

    with pytest.raises(SystemExit):
        script._run_or_fail(_failing(_BOT_CHECK), what="download the source")

    assert "retrying" not in capsys.readouterr().out


def test_any_other_failure_is_a_plain_failure_after_retrying(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "_RETRY_PAUSE_S", 0)

    with pytest.raises(SystemExit) as raised:
        script._run_or_fail(
            _failing("ERROR: [youtube] abc: This video is not available"),
            what="download the source",
        )

    assert raised.value.code == 1
    assert "retrying 2/2" in capsys.readouterr().out


def test_on_github_actions_a_failure_is_annotated(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(SystemExit):
        script.fail("first line\nsecond line")
    with pytest.raises(SystemExit):
        script.fail("refused", status=script.EXIT_SOURCE_REFUSED, title="Refused")

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "::error title=Real dub failed::first line%0Asecond line",
        "::warning title=Refused::refused",
    ]


def test_off_github_actions_nothing_is_annotated(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    with pytest.raises(SystemExit):
        script.fail("plain")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: plain\n"
