import contextlib
from pathlib import Path

import pytest

from germandubi.application.ports.providers import AcquisitionRequest
from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.domain.errors import SourceAcquisitionError
from germandubi.infrastructure.processes.runner import CommandResult
from germandubi.infrastructure.providers.ytdlp import (
    JS_RUNTIMES,
    YtDlpAcquisitionProvider,
    YtDlpProbeProvider,
    _explain,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("removed", "removed"),
        ("age-restricted", "age-restricted"),
        ("confirm your age", "age-restricted"),
        ("sign in", "signing in"),
        ("not available in your country", "blocked"),
        ("unable to download webpage", "could not be reached"),
        # Says both things it can mean, because the words alone do not distinguish them.
        ("ERROR: [youtube] abc: This video is not available", "germandubi doctor"),
    ],
)
def test_ytdlp_errors_are_classified_without_substring_collisions(
    message: str, expected: str
) -> None:
    assert expected in _explain(message)


class TestJavaScriptRuntimeIsNamed:
    """yt-dlp enables only deno by default, so an installed Node is not enough.

    A container shipping Node failed to probe a video YouTube served happily -- yt-dlp
    fell back to a player API and reported "This video is not available" -- while
    `germandubi doctor` reported a JavaScript runtime present. The check was right and
    nothing passed the answer on to the downloader.
    """

    class Runner:
        default_timeout_s = 60

        def __init__(self) -> None:
            self.argv: list[str] = []

        def is_installed(self, _name: str) -> bool:
            return True

        def run(self, argv: list[str], **_kwargs: object) -> CommandResult:
            self.argv = list(argv)
            return CommandResult(tuple(argv), 0, "{}", "", 0.1)

    @staticmethod
    def _runtimes_in(argv: list[str]) -> list[str]:
        return [argv[i + 1] for i, item in enumerate(argv) if item == "--js-runtimes"]

    def test_the_probe_names_every_runtime(self) -> None:
        runner = self.Runner()
        provider = YtDlpProbeProvider(runner)  # type: ignore[arg-type]
        source = SourceRef(
            kind=SourceKind.YOUTUBE, locator="https://www.youtube.com/watch?v=abcdefghijk"
        )

        with contextlib.suppress(SourceAcquisitionError):
            provider.probe(source)

        assert self._runtimes_in(runner.argv) == list(JS_RUNTIMES)

    def test_the_download_names_every_runtime(self, tmp_path: Path) -> None:
        runner = self.Runner()
        provider = YtDlpAcquisitionProvider(runner)  # type: ignore[arg-type]
        source = SourceRef(
            kind=SourceKind.YOUTUBE, locator="https://www.youtube.com/watch?v=abcdefghijk"
        )

        with contextlib.suppress(Exception):
            provider.acquire(AcquisitionRequest(source=source, destination=tmp_path / "out"))

        assert self._runtimes_in(runner.argv) == list(JS_RUNTIMES)

    def test_each_runtime_gets_its_own_flag(self) -> None:
        """`--js-runtimes deno,node` is accepted and silently solves nothing."""
        runner = self.Runner()
        provider = YtDlpProbeProvider(runner)  # type: ignore[arg-type]
        source = SourceRef(
            kind=SourceKind.YOUTUBE, locator="https://www.youtube.com/watch?v=abcdefghijk"
        )

        with contextlib.suppress(SourceAcquisitionError):
            provider.probe(source)

        assert runner.argv.count("--js-runtimes") == len(JS_RUNTIMES)
        assert not any("," in runtime for runtime in self._runtimes_in(runner.argv))
