"""Generating the tiny media fixtures the integration tests run against.

Fixtures are generated rather than committed. A checked-in video would be either too small
to be realistic or too large to belong in Git, and generating gives every test a file with
exactly the properties it needs.
"""

from __future__ import annotations

from pathlib import Path

from germandubi.infrastructure.processes.runner import ProcessRunner

__all__ = ["make_narration_video"]


def make_narration_video(
    destination: Path,
    *,
    seconds: int = 15,
    runner: ProcessRunner | None = None,
) -> Path:
    """Create a small video with a video stream and an audio stream.

    Args:
        destination: Where to write the file.
        seconds: Length of the clip.
        runner: Process runner to use.

    Returns:
        The written file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = runner or ProcessRunner(default_timeout_s=120)
    process.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=15:duration={seconds}",
            # Two tones at different frequencies stand in for narration over a music bed.
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=200:duration={seconds}",
            "-filter_complex",
            "[1:a]volume=0.6[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
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
