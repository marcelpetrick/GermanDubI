"""The one place in this application that spawns external processes.

Every invocation of ``ffmpeg``, ``ffprobe`` and ``yt-dlp`` goes through here. Centralizing
it is a security control, not a tidiness preference: it is what guarantees that no command
is ever built by concatenating user input into a shell string, that every process has a
timeout and can be cancelled, and that a killed process does not leave orphaned children
holding a GPU or a file handle.

An architecture test asserts that ``subprocess`` is imported nowhere else.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from germandubi.domain.errors import (
    CancelledError,
    ConfigurationError,
    GermanDubIError,
    ResourceError,
)

__all__ = ["CommandResult", "ProcessError", "ProcessRunner"]

logger = logging.getLogger(__name__)

#: Output beyond this is discarded, so a chatty tool cannot exhaust memory on a long job.
_MAX_CAPTURED_BYTES: Final = 256 * 1024
#: How long to wait for a terminated process group to exit before killing it.
_TERMINATE_GRACE_S: Final = 5.0
#: Values matching these are replaced before a command is logged.
_REDACTION_PATTERNS: Final = (
    re.compile(r"(--(?:password|cookies|api-key|token|secret)[= ])(\S+)", re.IGNORECASE),
    # Lookahead on the "@" so the separator survives the substitution.
    re.compile(r"(https?://)([^:/@\s]+:[^@\s]+)(?=@)"),
)


class ProcessError(GermanDubIError):
    """An external process failed, timed out, or could not be started."""

    code = "process_error"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of one external command.

    Attributes:
        argv: The argument array that was executed.
        returncode: The process exit code.
        stdout: Captured standard output, truncated to a bounded size.
        stderr: Captured standard error, truncated to a bounded size.
        duration_s: Wall-clock runtime.
    """

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def succeeded(self) -> bool:
        """Return whether the process exited cleanly."""
        return self.returncode == 0

    @property
    def command_line(self) -> str:
        """Return a redacted, human-readable rendering for logs and error messages."""
        return redact(" ".join(self.argv))

    def failure_summary(self, *, lines: int = 12) -> str:
        """Return the tail of stderr, which is where these tools put the real reason.

        Args:
            lines: How many trailing lines to include.

        Returns:
            The most informative part of the process output.
        """
        source = self.stderr.strip() or self.stdout.strip()
        return "\n".join(source.splitlines()[-lines:])


def redact(text: str) -> str:
    """Remove credentials and secrets from text before it is logged.

    Args:
        text: The text to redact.

    Returns:
        The text with credential-looking values replaced.

    Example:
        >>> redact("yt-dlp --password hunter2")
        'yt-dlp --password ***'
    """
    redacted = text
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}***", redacted)
    return redacted


@dataclass
class ProcessRunner:
    """Runs external programs safely.

    Attributes:
        default_timeout_s: Timeout applied when a caller does not specify one.
        cancelled: Consulted between and during runs. When it returns ``True`` the running
            process tree is terminated and :class:`CancelledError` is raised, which is how
            cooperative cancellation reaches a long FFmpeg run.
    """

    default_timeout_s: int = 3600
    cancelled: Callable[[], bool] = field(default=lambda: False)

    def resolve(self, program: str) -> str:
        """Resolve a program name to an absolute executable path.

        Resolving up front means a missing tool produces a clear, actionable error at the
        start of a stage rather than an opaque ``FileNotFoundError`` deep inside it.

        Args:
            program: A program name or an absolute path.

        Returns:
            The absolute path to the executable.

        Raises:
            ConfigurationError: If the program is not installed or not executable.
        """
        if Path(program).is_absolute():
            if os.access(program, os.X_OK):
                return program
            msg = f"{program} is not an executable file"
            raise ConfigurationError(msg, program=program)
        resolved = shutil.which(program)
        if resolved is None:
            msg = (
                f"{program!r} was not found on PATH. Install it and make sure it is "
                f"executable; run `germandubi doctor` to check the environment."
            )
            raise ConfigurationError(msg, program=program)
        return resolved

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_s: int | None = None,
        cwd: Path | None = None,
        check: bool = True,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run an external program and return its result.

        The command is always an argument array executed without a shell, so no value in
        ``argv`` - including a video title or a file name derived from one - can be
        interpreted as shell syntax.

        Args:
            argv: The program and its arguments. Must not be empty.
            timeout_s: Ceiling on runtime; defaults to :attr:`default_timeout_s`.
            cwd: Working directory for the process.
            check: Whether a non-zero exit code raises.
            stdin_text: Text to write to the process's standard input.
            env: Extra environment variables, merged over the current environment.

        Returns:
            The captured result.

        Raises:
            ProcessError: If the program cannot be started, times out, or - when ``check``
                is set - exits non-zero.
            ConfigurationError: If the program is not installed.
            CancelledError: If cancellation was requested before or during the run.
            ResourceError: If the system cannot spawn the process.
        """
        if not argv:
            msg = "cannot run an empty command"
            raise ProcessError(msg)
        if self.cancelled():
            msg = "cancelled before starting the command"
            raise CancelledError(msg)

        command = (self.resolve(argv[0]), *argv[1:])
        timeout = timeout_s if timeout_s is not None else self.default_timeout_s
        environment = {**os.environ, **(env or {})}
        started = time.monotonic()

        logger.debug("running: %s", redact(" ".join(command)))
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=environment,
                text=True,
                errors="replace",
                # A new process group means terminating covers the whole tree: ffmpeg and
                # yt-dlp both spawn children that would otherwise survive.
                start_new_session=True,
            )
        except OSError as exc:
            msg = f"could not start {command[0]}: {exc}"
            raise ResourceError(msg, program=command[0]) from exc

        stdout, stderr, timed_out, cancelled = self._communicate(process, stdin_text, timeout)
        duration = time.monotonic() - started
        result = CommandResult(
            argv=command,
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout[:_MAX_CAPTURED_BYTES],
            stderr=stderr[:_MAX_CAPTURED_BYTES],
            duration_s=duration,
        )

        if cancelled:
            msg = f"{Path(command[0]).name} was cancelled after {duration:.1f}s"
            raise CancelledError(msg, command=result.command_line)
        if timed_out:
            msg = f"{Path(command[0]).name} exceeded its {timeout}s time limit"
            raise ProcessError(msg, command=result.command_line, timeout_s=timeout)
        if check and not result.succeeded:
            msg = (
                f"{Path(command[0]).name} failed with exit code {result.returncode}.\n"
                f"{result.failure_summary()}"
            )
            raise ProcessError(msg, command=result.command_line, returncode=result.returncode)
        return result

    def _communicate(
        self, process: subprocess.Popen[str], stdin_text: str | None, timeout: int
    ) -> tuple[str, str, bool, bool]:
        """Drive the process to completion, honouring the timeout and cancellation.

        Returns:
            ``(stdout, stderr, timed_out, cancelled)``.
        """
        captured: dict[str, str] = {"out": "", "err": ""}

        def pump() -> None:
            out, err = process.communicate(input=stdin_text)
            captured["out"], captured["err"] = out or "", err or ""

        worker = threading.Thread(target=pump, daemon=True)
        worker.start()

        deadline = time.monotonic() + timeout
        cancelled = False
        while worker.is_alive():
            if time.monotonic() > deadline:
                self._terminate_tree(process)
                worker.join(_TERMINATE_GRACE_S)
                return captured["out"], captured["err"], True, False
            if self.cancelled():
                cancelled = True
                self._terminate_tree(process)
                worker.join(_TERMINATE_GRACE_S)
                break
            worker.join(0.1)

        worker.join(_TERMINATE_GRACE_S)
        return captured["out"], captured["err"], False, cancelled

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[str]) -> None:
        """Terminate the process and every child it started.

        Signals the process group, waits briefly, then kills. Signalling the group is what
        stops FFmpeg's and yt-dlp's children from surviving the parent.
        """
        if process.poll() is not None:
            return
        try:
            group = os.getpgid(process.pid)
        except (OSError, ProcessLookupError):
            group = None

        try:
            if group is not None:
                os.killpg(group, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, ProcessLookupError):
            return

        deadline = time.monotonic() + _TERMINATE_GRACE_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.05)

        try:
            if group is not None:
                os.killpg(group, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass

    def is_installed(self, program: str) -> bool:
        """Return whether a program is available, without raising.

        Args:
            program: The program name to look for.

        Returns:
            Whether it can be resolved to an executable.
        """
        try:
            self.resolve(program)
        except ConfigurationError:
            return False
        return True
