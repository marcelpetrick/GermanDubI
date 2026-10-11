#!/usr/bin/env -S uv run python
"""Take a real source through the whole product path and measure how long it takes.

Everything else in this repository is verified against deterministic fakes, which is the
right choice for CI but proves nothing about the product: a fake cannot show that a real
download, a real transcript, real German speech and a real mix combine into a file someone
can play. This script is the counterpart to that -- the one check that uses real providers
on a real source, and reports what it cost.

It is not part of the quality gate. It needs the network, the optional provider stacks and
several minutes, so it is run deliberately:

    ./scripts/benchmark_real_dub.py --excerpt-seconds 120
    ./scripts/benchmark_real_dub.py --full          # the entire source
    ./scripts/benchmark_real_dub.py --source-file talk.mp4
    ./scripts/benchmark_real_dub.py --spoken-fixture  # offline: no source site involved

``--spoken-fixture`` dubs English narration generated on the spot with espeak-ng. It exists
because the reference source is on YouTube, and YouTube refuses anonymous downloads from
datacenter addresses -- a CI runner among them. Every provider after acquisition still runs
for real; what it does not prove is that the source site can be downloaded from.

Timings come from the pipeline's own persisted job records rather than from a stopwatch
wrapped around the call, so what is reported is what the application actually recorded.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from germandubi.composition import build_application, configure_logging
from germandubi.config import Settings, get_settings
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.project import QualityProfile
from germandubi.domain.errors import GermanDubIError, ProviderUnavailableError

#: The reference source: 40 minutes of English narration with one dominant narrator, which
#: is exactly the case GermanDubI targets first.
REFERENCE_URL = "https://www.youtube.com/watch?v=f3r05guSo1w"

#: Pause before retrying an upstream hiccup, multiplied by the attempt number.
_RETRY_PAUSE_S = 5

#: Exit status when the source site refused the network rather than the request. Distinct
#: from 1 so automation can tell "the product is broken" from "this machine may not
#: download from that site": the second says nothing about the code or the providers.
EXIT_SOURCE_REFUSED = 3

#: What yt-dlp prints when YouTube's bot check rejects the requesting address. Retrying
#: does not help: the verdict is on the network, and it holds for hours.
_BOT_CHECK = "not a bot"

#: Narration for ``--spoken-fixture``: plain English prose of about a minute, written for
#: this purpose, so there is no licence question and nothing to download.
SPOKEN_FIXTURE_TEXT = (
    "The Roman legion was the largest unit of the Roman army. "
    "In the early republic, a legion was raised for a single campaign and disbanded when "
    "the fighting was over. Its soldiers were citizens who owned property, and they paid "
    "for their own equipment. "
    "Over time, the wars grew longer and moved further from home. A farmer could not leave "
    "his fields for years at a time, and the army began to accept men who owned nothing. "
    "These soldiers served for a fixed number of years, and they expected land or money "
    "when they retired. "
    "By the time of the first emperor, the legions had become a permanent professional "
    "force. Each one carried a number and a name, and many of them kept both for "
    "centuries. They built roads, bridges and camps wherever they went, and some of those "
    "camps grew into cities that still exist today."
)


@dataclass(frozen=True)
class StageTiming:
    """How long one pipeline stage took."""

    stage: str
    label: str
    status: str
    seconds: float | None


@dataclass(frozen=True)
class BenchmarkResult:
    """Everything worth recording about one real run."""

    source_url: str
    mode: str
    recorded_at: str
    host: dict[str, str]
    providers: dict[str, str]
    source_title: str
    source_duration_s: float
    processed_duration_s: float
    total_seconds: float
    realtime_factor: float
    segments: int
    export_path: str
    export_bytes: int
    export_audio_codec: str | None
    export_duration_s: float | None
    stages: list[dict[str, Any]]


def parse_arguments() -> argparse.Namespace:
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--url", default=REFERENCE_URL, help="Source to dub.")
    source.add_argument(
        "--source-file",
        type=Path,
        help="Dub a local media file instead of downloading one.",
    )
    source.add_argument(
        "--spoken-fixture",
        action="store_true",
        help=(
            "Dub English narration generated offline with espeak-ng. Exercises every "
            "provider without depending on a source site."
        ),
    )
    parser.add_argument(
        "--excerpt-seconds",
        type=int,
        default=120,
        help="Dub only the first N seconds, so the run is practical to repeat (default: 120).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Dub the entire source from its URL, with no excerpt.",
    )
    parser.add_argument(
        "--quality",
        type=QualityProfile,
        choices=list(QualityProfile),
        default=QualityProfile.BALANCED,
        help="Speed/quality trade-off.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/benchmarks/real-dub.json"),
        help="Where to write the machine-readable result.",
    )
    parser.add_argument(
        "--export-to",
        type=Path,
        default=Path("benchmark-output"),
        help="Directory the dubbed video is copied to (default: benchmark-output).",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep the whole project workspace, not just the dubbed video.",
    )
    return parser.parse_args()


def fail(message: str, *, status: int = 1, title: str = "Real dub failed") -> None:
    """Print an error and exit with ``status``.

    On GitHub Actions the message is also emitted as an annotation, so it appears on the
    run's summary page instead of only deep inside the step's log.
    """
    print(f"error: {message}", file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        level = "warning" if status == EXIT_SOURCE_REFUSED else "error"
        print(f"::{level} title={title}::{_annotation_escape(message)}")
    raise SystemExit(status)


def _annotation_escape(message: str) -> str:
    """Escape a message for a GitHub workflow command, which must be one line."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def require_tools(*, download: bool, speak: bool) -> None:
    """Exit unless the external tools this run needs are installed."""
    needed = ["ffmpeg", "ffprobe"]
    if download:
        needed.append("yt-dlp")
    if speak:
        needed.append("espeak-ng")
    missing = [tool for tool in needed if shutil.which(tool) is None]
    if missing:
        fail(f"missing required tools: {', '.join(missing)}")


def describe_providers(settings: Settings) -> dict[str, str]:
    """Return the provider selected for each port before the run starts.

    A run using the placeholder providers would finish quickly and prove nothing, so the
    report has to record which implementations really ran.

    Transcription is provisional here: the real choice also depends on whether the source
    turns out to ship usable captions, which is not known until it has been downloaded.
    :func:`actual_transcript_source` corrects it afterwards from what was persisted.
    """
    application = build_application(settings, create_schema=False)
    try:
        registry = application.registry
        separation = registry.separation()
        try:
            transcription = type(registry.transcription()).__name__
        except ProviderUnavailableError:
            # Recognition is absent, which is not yet an error: a source that ships usable
            # captions still has a transcript. Whether this run does is unknown until the
            # source has been downloaded, and the real answer is read back afterwards.
            transcription = "pending (depends on the source's captions)"
        return {
            "transcription": transcription,
            "translation": type(registry.translation()).__name__,
            "tts": type(registry.tts()).__name__,
            "separation": type(separation).__name__ if separation else "none (ducking fallback)",
        }
    finally:
        application.dispose()


def actual_transcript_source(path: Path) -> str | None:
    """Return the transcript provider that really ran, read from its own artifact.

    The registry can only report what it *would* select. Which transcript provider actually
    runs depends on the captions the source turns out to carry, so reporting the selection
    made before the download can name a provider that never executed.
    """
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    provider = payload.get("provider_id")
    origin = payload.get("source")
    if provider is None and origin is None:
        return None
    return f"{provider} ({origin})" if provider and origin else str(provider or origin)


def download_excerpt(url: str, seconds: int, destination: Path) -> Path:
    """Download the source and cut its first ``seconds`` into a standalone file.

    The pipeline processes whatever source it is given, start to finish. Bounding the work
    therefore means bounding the *input*, not adding a mode to the pipeline: the excerpt is
    an ordinary local media file, and every stage after acquisition behaves identically to
    a full run.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = destination.parent / "source.mp4"

    print(f"downloading {url}")
    _run_or_fail(
        [
            "yt-dlp",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "-f",
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
            "--download-sections",
            f"*0-{seconds + 5}",
            "--force-keyframes-at-cuts",
            "-o",
            str(downloaded),
            url,
        ],
        what="download the source",
    )
    if not downloaded.exists():
        candidates = sorted(destination.parent.glob("source.*"))
        if not candidates:
            fail("the download produced no file")
        downloaded = candidates[0]

    return cut_excerpt(downloaded, seconds, destination)


def cut_excerpt(source: Path, seconds: int, destination: Path) -> Path:
    """Write the first ``seconds`` of ``source`` to ``destination`` as a standalone file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"cutting the first {seconds}s")
    _run_or_fail(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            str(destination),
        ],
        what="cut the excerpt",
    )
    return destination


def make_spoken_fixture(destination: Path) -> Path:
    """Generate a video of English narration with espeak-ng, entirely offline.

    The voice is synthetic, which makes recognition easier than a human narrator would.
    That is the price of a source no site can refuse; it still takes the real recognition,
    translation, speech and mixing providers through the whole pipeline.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    speech = destination.parent / "narration.wav"
    print("generating English narration with espeak-ng")
    _run_or_fail(
        ["espeak-ng", "-v", "en-us", "-s", "150", "-w", str(speech), SPOKEN_FIXTURE_TEXT],
        what="generate the narration",
        attempts=1,
    )
    _run_or_fail(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25",
            "-i",
            str(speech),
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(destination),
        ],
        what="build the narration video",
        attempts=1,
    )
    return destination


def _run_or_fail(argv: list[str], *, what: str, attempts: int = 3) -> None:
    """Run a command, retrying an upstream hiccup and reporting failure as a message.

    The source site intermittently answers "This video is not available" for a video that
    is plainly available a minute later -- observed on a URL whose metadata had just been
    read successfully. The application retries every stage for this reason; this script
    would otherwise report a healthy video as broken.

    A stack trace tells the reader nothing they can act on, so a real failure is a message.

    YouTube's bot check is the exception to retrying: it rejects the requesting network,
    not the request, and it ends the run at once with :data:`EXIT_SOURCE_REFUSED`.
    """
    for attempt in range(1, attempts + 1):
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.returncode}"
        if _BOT_CHECK in reason.lower():
            fail(
                f"could not {what}: the source site refused this network as automated "
                "traffic. That is a verdict on the address, not on this code or the "
                "providers: the same download works from a residential connection. "
                f"Use --spoken-fixture to dub without a source site. ({reason})",
                status=EXIT_SOURCE_REFUSED,
                title="Source site refused this network",
            )
        if attempt < attempts:
            print(f"could not {what} ({reason}); retrying {attempt}/{attempts - 1}")
            time.sleep(_RETRY_PAUSE_S * attempt)
    fail(f"could not {what} after {attempts} attempts: {reason}")


def probe_media(path: Path) -> tuple[float | None, str | None]:
    """Return the duration and audio codec of a media file, for verifying the output."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    duration = payload.get("format", {}).get("duration")
    audio = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "audio"),
        None,
    )
    return (float(duration) if duration else None, audio.get("codec_name") if audio else None)


def render_summary(result: BenchmarkResult) -> str:
    """Return the human-readable report."""
    lines = [
        "",
        "=" * 74,
        f"  Real dub: {result.source_title}",
        "=" * 74,
        f"  source          {result.source_url}",
        f"  mode            {result.mode}",
        (
            f"  processed       {result.processed_duration_s:.0f}s"
            f" of {result.source_duration_s:.0f}s source"
        ),
        f"  segments        {result.segments}",
        "",
        f"  transcription   {result.providers['transcription']}",
        f"  translation     {result.providers['translation']}",
        f"  speech          {result.providers['tts']}",
        f"  separation      {result.providers['separation']}",
        "",
        "  stage                            status        seconds     share",
        "  " + "-" * 62,
    ]
    total = result.total_seconds or 1.0
    for stage in result.stages:
        seconds = stage["seconds"]
        rendered = f"{seconds:8.1f}" if seconds is not None else "       -"
        share = f"{(seconds / total * 100):5.1f}%" if seconds else "     -"
        lines.append(f"  {stage['label']:<30} {stage['status']:<12} {rendered}   {share}")
    lines += [
        "  " + "-" * 62,
        f"  {'total':<30} {'':<12} {result.total_seconds:8.1f}",
        "",
        (
            f"  realtime factor {result.realtime_factor:.2f}x "
            f"({result.total_seconds:.0f}s of work per {result.processed_duration_s:.0f}s"
            " of video)"
        ),
        "",
        f"  output          {result.export_path}",
        f"  size            {result.export_bytes / 1_000_000:.1f} MB",
        f"  audio           {result.export_audio_codec}, {result.export_duration_s:.0f}s"
        if result.export_duration_s
        else f"  audio           {result.export_audio_codec}",
        "=" * 74,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Run the benchmark."""
    arguments = parse_arguments()
    downloading = arguments.source_file is None and not arguments.spoken_fixture
    require_tools(download=downloading, speak=arguments.spoken_fixture)

    workspace = Path.cwd() / ".benchmark"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    settings = get_settings().model_copy(update={"data_dir": workspace / "data"})
    configure_logging(settings)

    providers = describe_providers(settings)
    placeholders = {port: name for port, name in providers.items() if name.startswith("Fake")}
    if placeholders:
        fail(
            "these ports resolved to placeholder providers, so the run would prove nothing: "
            f"{', '.join(sorted(placeholders))}. Install them with `make install-providers`."
        )

    mode = "full source" if arguments.full else f"first {arguments.excerpt_seconds}s"
    source_label: str = arguments.url
    local: Path | None = None
    if arguments.spoken_fixture:
        source_label = "espeak-ng narration (offline fixture)"
        local = make_spoken_fixture(workspace / "fixture" / "narration.mp4")
    elif arguments.source_file is not None:
        source_label = arguments.source_file.name
        local = arguments.source_file.resolve()
        if not local.is_file():
            fail(f"no such file: {arguments.source_file}")

    source: str = arguments.url
    from_file = local is not None or not arguments.full
    if local is not None and arguments.full:
        source = str(local)
    elif local is not None:
        source = str(cut_excerpt(local, arguments.excerpt_seconds, workspace / "excerpt.mp4"))
    elif not arguments.full:
        source = str(
            download_excerpt(arguments.url, arguments.excerpt_seconds, workspace / "excerpt.mp4")
        )

    application = build_application(settings)
    started = time.monotonic()
    try:
        project = (
            application.projects.create_from_file(source, quality=arguments.quality)
            if from_file
            else application.projects.create_from_url(source, quality=arguments.quality)
        )
        print(f"project {project.id}")

        worker = application.worker()
        application.projects.request_analysis(project.id)
        worker.run_until_idle()

        analysed = application.projects.get(project.id)
        if analysed.media is None:
            fail(analysed.error or "the source could not be analysed")

        print(f"analysed: {analysed.display_title}")
        application.pipeline.start(project.id)
        worker.run_until_idle()
        total_seconds = time.monotonic() - started

        progress = application.pipeline.latest_progress(project.id)
        if progress is None:
            fail("the run recorded no progress")
            return 1
        if progress.failed:
            broken = [job.stage for job in progress.jobs if job.status.is_finished and job.error]
            fail(f"the run failed at: {', '.join(str(stage) for stage in broken) or 'unknown'}")

        stages = [
            StageTiming(
                stage=str(job.stage),
                label=job.stage.label,
                status=str(job.status),
                seconds=(
                    (job.finished_at - job.started_at).total_seconds()
                    if job.started_at and job.finished_at
                    else None
                ),
            )
            for job in progress.jobs
        ]

        with application.unit_of_work() as uow:
            export = uow.artifacts.latest(project.id, ArtifactKind.EXPORT)
            if export is None:
                fail("the run finished without producing an export")
                return 1
            export_path = Path(uow.store.path_for(export))
            transcript = uow.artifacts.latest(project.id, ArtifactKind.TRANSCRIPT)
            transcript_path = Path(uow.store.path_for(transcript)) if transcript else None

        if transcript_path is not None:
            used = actual_transcript_source(transcript_path)
            if used is not None:
                providers["transcription"] = used

        if not export_path.exists() or export_path.stat().st_size == 0:
            fail(f"the export is missing or empty: {export_path}")

        export_duration, export_codec = probe_media(export_path)
        summary = application.segments.summary(project.id)
        media = application.projects.get(project.id).media
        processed = (media.duration_ms / 1000.0) if media else 0.0

        # The workspace is deleted below, so the one artifact worth keeping -- the file a
        # person can actually play -- is copied out first. It is deliberately not written
        # into the repository: the measurements belong in Git, a video does not.
        arguments.export_to.mkdir(parents=True, exist_ok=True)
        kept = arguments.export_to / export_path.name
        shutil.copy2(export_path, kept)

        result = BenchmarkResult(
            source_url=source_label,
            mode=mode,
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            host={
                "platform": platform.platform(),
                "python": platform.python_version(),
                "processor": platform.processor() or "unknown",
                "device": settings.resolved_device(),
            },
            providers=providers,
            source_title=analysed.display_title,
            source_duration_s=(
                (2400.0 if downloading else processed)
                if arguments.full
                else float(arguments.excerpt_seconds)
            ),
            processed_duration_s=processed,
            total_seconds=round(total_seconds, 1),
            realtime_factor=round(total_seconds / processed, 2) if processed else 0.0,
            segments=summary.total,
            export_path=str(kept),
            export_bytes=kept.stat().st_size,
            export_audio_codec=export_codec,
            export_duration_s=export_duration,
            stages=[asdict(stage) for stage in stages],
        )

        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(asdict(result), indent=2) + "\n")
        print(render_summary(result))
        print(f"wrote {arguments.output}")
        return 0
    except GermanDubIError as error:
        fail(error.message)
        return 1
    finally:
        application.dispose()
        if not arguments.keep_data:
            with contextlib.suppress(OSError):
                shutil.rmtree(workspace)


if __name__ == "__main__":
    raise SystemExit(main())
