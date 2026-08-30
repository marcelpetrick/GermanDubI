"""Stages that get the source media onto this machine and into a usable shape."""

from __future__ import annotations

import logging
from pathlib import Path

from germandubi.application.ports.providers import AcquisitionRequest
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.project import ProjectState
from germandubi.domain.errors import SourceAcquisitionError
from germandubi.domain.value_objects.content_hash import hash_inputs
from germandubi.infrastructure.media.ffmpeg import ASR_SAMPLE_RATE, MASTER_SAMPLE_RATE
from germandubi.worker.context import StageContext

__all__ = ["handle_acquire", "handle_normalize", "handle_probe"]

logger = logging.getLogger(__name__)


def handle_probe(context: StageContext) -> None:
    """Inspect the source without downloading it.

    Runs before acquisition so the user learns the title, duration and caption availability
    in a second or two, rather than after a multi-hundred-megabyte download.

    Args:
        context: The stage context.

    Raises:
        SourceAcquisitionError: If the source cannot be inspected.
    """
    context.progress(0.1, "contacting the source")
    provider = context.registry.probe()
    media = provider.probe(context.project.source)
    context.checkpoint()

    project = context.project.with_probe_result(media)
    context.uow.projects.save(project)
    context.project = project

    caption = media.best_english_caption
    context.event(
        "source_analysed",
        {
            "title": media.title,
            "duration_ms": media.duration_ms,
            "has_english_captions": caption is not None,
            "captions_are_automatic": caption.automatic if caption else None,
        },
    )
    context.progress(1.0, media.title)
    logger.info("probed %s: %.1fs", media.title, media.duration_ms / 1000)


def handle_acquire(context: StageContext) -> None:
    """Download the source media and any English captions.

    Args:
        context: The stage context.

    Raises:
        SourceAcquisitionError: If the download fails.
    """
    context.progress(0.05, "downloading")
    destination = context.directory("source")
    provider = context.registry.acquisition()

    result = provider.acquire(
        AcquisitionRequest(source=context.project.source, destination=destination)
    )
    context.checkpoint()
    if not result.video_path.exists():
        msg = "the download completed but no media file is present"
        raise SourceAcquisitionError(msg, destination=str(destination))

    input_hash = hash_inputs(source=context.project.source.locator, provider=provider.info.id)
    context.publish(
        ArtifactKind.SOURCE_VIDEO,
        result.video_path,
        provider_id=provider.info.id,
        input_hash=input_hash,
        media_type=_media_type(result.video_path),
    )

    for automatic, caption_path in result.caption_paths.items():
        moved = _move_into(caption_path, context.directory("captions"))
        context.publish(
            ArtifactKind.SOURCE_CAPTIONS,
            moved,
            provider_id=provider.info.id,
            input_hash=hash_inputs(source=context.project.source.locator, automatic=automatic),
            parameters={"automatic": str(automatic)},
            media_type="text/vtt",
            supersede=False,
        )

    context.progress(1.0, f"{result.video_path.stat().st_size // (1024 * 1024)} MB")
    logger.info("acquired %s", result.video_path.name)


def handle_normalize(context: StageContext) -> None:
    """Extract the two audio tracks the rest of the pipeline works from.

    Two are produced deliberately. The master track is 48 kHz stereo and is what the final
    mix is built on, so nothing downstream loses quality. The recognition track is 16 kHz
    mono, which is what speech models are trained on and would resample to anyway; producing
    it once here avoids doing it inside every provider.

    Args:
        context: The stage context.

    Raises:
        MediaProcessingError: If extraction fails.
    """
    source = context.require(ArtifactKind.SOURCE_VIDEO)
    media = context.registry.media()
    audio_dir = context.directory("audio")

    context.progress(0.2, "extracting the master audio")
    master = media.extract_audio(
        source, audio_dir / "master.wav", sample_rate=MASTER_SAMPLE_RATE, mono=False
    )
    context.checkpoint()
    context.publish(
        ArtifactKind.MASTER_AUDIO,
        master,
        provider_id="ffmpeg",
        input_hash=hash_inputs(source=source.name, rate=MASTER_SAMPLE_RATE, mono=False),
        media_type="audio/wav",
    )

    context.progress(0.7, "preparing audio for recognition")
    asr = media.extract_audio(source, audio_dir / "asr.wav", sample_rate=ASR_SAMPLE_RATE, mono=True)
    context.publish(
        ArtifactKind.ASR_AUDIO,
        asr,
        provider_id="ffmpeg",
        input_hash=hash_inputs(source=source.name, rate=ASR_SAMPLE_RATE, mono=True),
        media_type="audio/wav",
    )

    info = media.probe(master)
    context.event("media_normalized", {"duration_ms": info.duration_ms})
    if context.project.state is ProjectState.READY:
        context.progress(1.0, f"{info.duration_ms // 1000}s of audio")
    else:
        context.progress(1.0, None)


def _move_into(path: Path, directory: Path) -> Path:
    """Move a file into a workspace directory, returning its new location."""
    if path.parent.resolve() == directory.resolve():
        return path
    target = directory / path.name
    target.write_bytes(path.read_bytes())
    path.unlink(missing_ok=True)
    return target


def _media_type(path: Path) -> str:
    """Return a browser-meaningful media type for a downloaded container."""
    return {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
    }.get(path.suffix.lower(), "application/octet-stream")
