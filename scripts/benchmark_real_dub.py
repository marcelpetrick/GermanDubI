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

Timings come from the pipeline's own persisted job records rather than from a stopwatch
wrapped around the call, so what is reported is what the application actually recorded.
"""

from __future__ import annotations

import argparse
import contextlib
import json
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
    parser.add_argument("--url", default=REFERENCE_URL, help="Source to dub.")
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


def fail(message: str) -> None:
    """Print an error and exit non-zero."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_tools() -> None:
    """Exit unless the external tools a real run needs are installed."""
    missing = [tool for tool in ("yt-dlp", "ffmpeg", "ffprobe") if shutil.which(tool) is None]
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
    subprocess.run(
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
        check=True,
    )
    if not downloaded.exists():
        candidates = sorted(destination.parent.glob("source.*"))
        if not candidates:
            fail("the download produced no file")
        downloaded = candidates[0]

    print(f"cutting the first {seconds}s")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(downloaded),
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
        check=True,
    )
    return destination


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
    require_tools()

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
    source: str = arguments.url
    if not arguments.full:
        source = str(
            download_excerpt(arguments.url, arguments.excerpt_seconds, workspace / "excerpt.mp4")
        )

    application = build_application(settings)
    started = time.monotonic()
    try:
        project = (
            application.projects.create_from_file(source, quality=arguments.quality)
            if not arguments.full
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
            source_url=arguments.url,
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
            source_duration_s=2400.0 if arguments.full else float(arguments.excerpt_seconds),
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
