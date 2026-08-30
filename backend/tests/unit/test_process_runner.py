"""The process runner: the only place allowed to spawn external programs."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from germandubi.domain.errors import CancelledError, ConfigurationError, ResourceError
from germandubi.infrastructure.processes.runner import (
    MAX_STRUCTURED_OUTPUT_BYTES,
    ProcessError,
    ProcessRunner,
    redact,
)


@pytest.fixture
def runner() -> ProcessRunner:
    return ProcessRunner(default_timeout_s=10)


class TestExecution:
    def test_runs_a_command_and_captures_stdout(self, runner: ProcessRunner) -> None:
        result = runner.run(["echo", "hello"])
        assert result.succeeded
        assert result.stdout.strip() == "hello"

    def test_captures_stderr(self, runner: ProcessRunner) -> None:
        result = runner.run(["sh", "-c", "echo oops >&2"], check=False)
        assert "oops" in result.stderr

    def test_reports_the_exit_code(self, runner: ProcessRunner) -> None:
        assert runner.run(["sh", "-c", "exit 3"], check=False).returncode == 3

    def test_raises_on_a_non_zero_exit_when_checking(self, runner: ProcessRunner) -> None:
        with pytest.raises(ProcessError, match="exit code 3"):
            runner.run(["sh", "-c", "echo the reason >&2; exit 3"])

    def test_the_error_includes_the_tail_of_stderr(self, runner: ProcessRunner) -> None:
        with pytest.raises(ProcessError, match="the real reason"):
            runner.run(["sh", "-c", "echo the real reason >&2; exit 1"])

    def test_passes_stdin(self, runner: ProcessRunner) -> None:
        assert runner.run(["cat"], stdin_text="piped").stdout == "piped"

    def test_honours_the_working_directory(self, runner: ProcessRunner, tmp_path: Path) -> None:
        assert runner.run(["pwd"], cwd=tmp_path).stdout.strip() == str(tmp_path)

    def test_merges_extra_environment_variables(self, runner: ProcessRunner) -> None:
        result = runner.run(["sh", "-c", "echo $GERMANDUBI_TEST"], env={"GERMANDUBI_TEST": "set"})
        assert result.stdout.strip() == "set"

    def test_measures_the_runtime(self, runner: ProcessRunner) -> None:
        assert runner.run(["sh", "-c", "sleep 0.2"]).duration_s >= 0.15


class TestShellSafety:
    def test_arguments_are_never_interpreted_as_shell_syntax(self, runner: ProcessRunner) -> None:
        """A video title containing shell metacharacters must stay a literal argument."""
        hostile = "; rm -rf /tmp/should-not-happen; echo pwned"
        assert runner.run(["echo", hostile]).stdout.strip() == hostile

    def test_a_hostile_filename_is_passed_through_verbatim(self, runner: ProcessRunner) -> None:
        assert runner.run(["echo", "$(whoami)"]).stdout.strip() == "$(whoami)"

    def test_refuses_an_empty_command(self, runner: ProcessRunner) -> None:
        with pytest.raises(ProcessError, match="empty command"):
            runner.run([])


class TestResolution:
    def test_resolves_a_program_on_the_path(self, runner: ProcessRunner) -> None:
        assert Path(runner.resolve("sh")).is_absolute()

    def test_reports_a_missing_program_clearly(self, runner: ProcessRunner) -> None:
        with pytest.raises(ConfigurationError, match="germandubi doctor"):
            runner.resolve("definitely-not-a-real-program-xyz")

    def test_is_installed_does_not_raise(self, runner: ProcessRunner) -> None:
        assert runner.is_installed("sh")
        assert not runner.is_installed("definitely-not-a-real-program-xyz")

    def test_rejects_an_absolute_path_that_is_not_executable(
        self, runner: ProcessRunner, tmp_path: Path
    ) -> None:
        plain = tmp_path / "not-executable"
        plain.write_text("data")
        with pytest.raises(ConfigurationError, match="not an executable"):
            runner.resolve(str(plain))

    def test_a_missing_program_is_reported_before_the_process_starts(
        self, runner: ProcessRunner
    ) -> None:
        with pytest.raises(ConfigurationError):
            runner.run(["definitely-not-a-real-program-xyz", "--version"])


class TestTimeoutAndCancellation:
    def test_a_slow_process_is_killed_at_the_timeout(self) -> None:
        runner = ProcessRunner(default_timeout_s=1)
        started = time.monotonic()
        with pytest.raises(ProcessError, match="time limit"):
            runner.run(["sleep", "30"])
        assert time.monotonic() - started < 10

    def test_cancellation_before_starting_is_immediate(self) -> None:
        runner = ProcessRunner(cancelled=lambda: True)
        with pytest.raises(CancelledError, match="before starting"):
            runner.run(["echo", "never"])

    def test_cancellation_during_a_run_terminates_the_process(self) -> None:
        deadline = time.monotonic() + 0.3
        runner = ProcessRunner(default_timeout_s=30, cancelled=lambda: time.monotonic() > deadline)
        started = time.monotonic()
        with pytest.raises(CancelledError, match="cancelled"):
            runner.run(["sleep", "30"])
        assert time.monotonic() - started < 10

    def test_cancelling_kills_the_whole_process_tree(self, tmp_path: Path) -> None:
        """A killed parent must not leave children holding a GPU or a file handle."""
        marker = tmp_path / "child-survived"
        script = f"sh -c 'sleep 4; touch {marker}' & sleep 30"
        deadline = time.monotonic() + 0.3
        runner = ProcessRunner(default_timeout_s=30, cancelled=lambda: time.monotonic() > deadline)
        with pytest.raises(CancelledError):
            runner.run(["sh", "-c", script])
        time.sleep(1.5)
        assert not marker.exists()


class TestOutputHandling:
    def test_captured_output_is_bounded(self, runner: ProcessRunner) -> None:
        """A chatty tool on a long job must not be able to exhaust memory."""
        result = runner.run(["sh", "-c", "yes abcdefgh | head -c 2000000"], timeout_s=30)
        assert len(result.stdout) <= 256 * 1024

    def test_truncation_is_reported_rather_than_silent(self, runner: ProcessRunner) -> None:
        """Silent truncation once made a probe blame the source site for a local limit."""
        result = runner.run(["sh", "-c", "yes abcdefgh | head -c 2000000"], timeout_s=30)
        assert result.stdout_truncated

    def test_output_within_the_limit_is_not_flagged(self, runner: ProcessRunner) -> None:
        result = runner.run(["echo", "small"])
        assert not result.stdout_truncated
        assert not result.stderr_truncated

    def test_a_caller_may_raise_the_limit_for_structured_output(
        self, runner: ProcessRunner
    ) -> None:
        """Metadata parsed as JSON must arrive whole; 256 KB is not enough for yt-dlp."""
        size = 700_000
        result = runner.run(
            ["sh", "-c", f"yes abcdefgh | head -c {size}"],
            timeout_s=30,
            max_output_bytes=MAX_STRUCTURED_OUTPUT_BYTES,
        )
        assert not result.stdout_truncated
        assert len(result.stdout) == size

    def test_stderr_truncation_is_reported(self, runner: ProcessRunner) -> None:
        result = runner.run(
            ["sh", "-c", "yes abcdefgh | head -c 2000000 >&2"], timeout_s=30, check=False
        )
        assert result.stderr_truncated

    def test_failure_summary_returns_the_tail_of_stderr(self, runner: ProcessRunner) -> None:
        result = runner.run(
            ["sh", "-c", "for i in $(seq 1 40); do echo line$i >&2; done; exit 1"], check=False
        )
        summary = result.failure_summary(lines=3)
        assert summary.splitlines() == ["line38", "line39", "line40"]


class TestRedaction:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("yt-dlp --password hunter2", "yt-dlp --password ***"),
            ("tool --api-key=abc123", "tool --api-key=***"),
            ("https://user:secret@example.com/x", "https://***@example.com/x"),
            ("nothing to hide", "nothing to hide"),
        ],
    )
    def test_removes_credentials_before_logging(self, raw: str, expected: str) -> None:
        assert redact(raw) == expected

    def test_the_rendered_command_line_is_redacted(self, runner: ProcessRunner) -> None:
        result = runner.run(["echo", "--password", "hunter2"])
        assert "hunter2" not in result.command_line


def test_resource_error_is_raised_when_a_process_cannot_be_spawned(
    runner: ProcessRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no resources")

    monkeypatch.setattr("germandubi.infrastructure.processes.runner.subprocess.Popen", boom)
    with pytest.raises(ResourceError, match="could not start"):
        runner.run(["echo", "hi"])
