"""Stages that build the German audio track and the subtitles."""

from __future__ import annotations

import logging

from germandubi.application.ports.providers import MixRequest
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.segment import SpeechSegment
from germandubi.domain.subtitles import render_srt
from germandubi.domain.value_objects.content_hash import hash_inputs
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.worker.context import StageContext

__all__ = ["handle_assemble", "handle_mix", "handle_separate", "handle_subtitle"]

logger = logging.getLogger(__name__)


def handle_separate(context: StageContext) -> None:
    """Split the original audio into a background stem and a voice stem.

    Skipped when no separation model is installed, which is a normal outcome rather than a
    failure: the mix stage then ducks the original audio instead (questions.md Q-A3).

    Args:
        context: The stage context.
    """
    provider = context.registry.separation()
    if provider is None:
        context.progress(1.0, "no separation model installed; the original audio will be ducked")
        context.event("separation_skipped", {"reason": "no provider installed"})
        return

    master = context.require(ArtifactKind.MASTER_AUDIO)
    context.progress(0.05, f"using {provider.info.name}; this is the slowest stage")
    result = provider.separate(master, context.directory("stems"))
    context.checkpoint()

    input_hash = hash_inputs(
        audio=master.name, provider=provider.info.id, model=provider.info.model_id
    )
    context.publish(
        ArtifactKind.BACKGROUND_STEM,
        result.background_path,
        provider_id=result.provider_id,
        model_id=result.model_id,
        input_hash=input_hash,
        media_type="audio/wav",
    )
    if result.voice_path is not None:
        context.publish(
            ArtifactKind.VOICE_STEM,
            result.voice_path,
            provider_id=result.provider_id,
            model_id=result.model_id,
            input_hash=input_hash,
            media_type="audio/wav",
        )
    context.event("separation_ready", {"provider": result.provider_id})
    context.progress(1.0, "background separated")


def handle_assemble(context: StageContext) -> None:
    """Place every segment's German speech onto one continuous narration track.

    Each clip goes at its own timeline position rather than being concatenated, so a single
    regenerated segment cannot shift everything after it.

    Args:
        context: The stage context.

    Raises:
        MixError: If assembly fails.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    media = context.registry.media()
    master = context.require(ArtifactKind.MASTER_AUDIO)
    total_ms = media.probe(master).duration_ms

    placements: list[tuple[TimeInterval, object]] = []
    for segment in segments:
        artifact_id = context.uow.segments.speech_artifact_id(segment.id)
        if artifact_id is None:
            continue
        artifact = context.uow.artifacts.get(artifact_id)
        path = context.uow.store.path_for(artifact)
        if path.exists():
            placements.append((segment.interval, path))

    context.progress(0.3, f"placing {len(placements)} clips")
    context.checkpoint()
    destination = context.directory("mixes") / "narration.wav"
    media.concatenate_speech(placements, destination, total_ms=total_ms)  # type: ignore[arg-type]

    context.publish(
        ArtifactKind.NARRATION_TRACK,
        destination,
        provider_id="ffmpeg",
        input_hash=hash_inputs(clips=[str(p) for _, p in placements], total_ms=total_ms),
        media_type="audio/wav",
    )
    context.progress(1.0, f"{len(placements)} clips placed")
    logger.info("assembled a %.1fs German narration track", total_ms / 1000)


def handle_mix(context: StageContext) -> None:
    """Combine the German narration with the background or the ducked original.

    Args:
        context: The stage context.

    Raises:
        MixError: If mixing fails.
    """
    media = context.registry.media()
    narration = context.require(ArtifactKind.NARRATION_TRACK)
    master = context.require(ArtifactKind.MASTER_AUDIO)
    background = context.latest(ArtifactKind.BACKGROUND_STEM)

    segments = context.uow.segments.list_for_project(context.project.id)
    speech_intervals = tuple(s.interval for s in segments if s.is_translated)

    if background is not None:
        context.progress(0.3, "mixing German speech onto the separated background")
        background_path = context.uow.store.path_for(background)
        strategy = "background_stem"
    else:
        context.progress(0.3, "ducking the original audio under the German speech")
        background_path = None
        strategy = "ducking"

    destination = context.directory("mixes") / "german.wav"
    context.checkpoint()
    media.mix(
        MixRequest(
            narration_path=narration,
            destination=destination,
            background_path=background_path,
            original_path=None if background_path else master,
            speech_intervals=speech_intervals,
        )
    )
    context.publish(
        ArtifactKind.MIXED_AUDIO,
        destination,
        provider_id="ffmpeg",
        input_hash=hash_inputs(
            narration=narration.name, strategy=strategy, segments=len(speech_intervals)
        ),
        parameters={"strategy": strategy},
        media_type="audio/wav",
    )
    context.event("mix_ready", {"strategy": strategy})
    context.progress(1.0, f"mixed using {strategy.replace('_', ' ')}")


def handle_subtitle(context: StageContext) -> None:
    """Write German and English subtitle files.

    Args:
        context: The stage context.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    subtitles = context.directory("subtitles")

    german = _cues(segments, german=True)
    english = _cues(segments, german=False)

    if german:
        path = subtitles / "german.srt"
        path.write_text(render_srt(german), encoding="utf-8")
        context.publish(
            ArtifactKind.SUBTITLES_DE,
            path,
            provider_id="germandubi",
            input_hash=hash_inputs(cues=len(german), language="de"),
            media_type="application/x-subrip",
        )
    if english:
        path = subtitles / "english.srt"
        path.write_text(render_srt(english), encoding="utf-8")
        context.publish(
            ArtifactKind.SUBTITLES_EN,
            path,
            provider_id="germandubi",
            input_hash=hash_inputs(cues=len(english), language="en"),
            media_type="application/x-subrip",
        )

    context.progress(1.0, f"{len(german)} German, {len(english)} English cues")


def _cues(segments: list[SpeechSegment], *, german: bool) -> list[tuple[TimeInterval, str]]:
    """Return subtitle cues for one language, skipping segments with no text."""
    result: list[tuple[TimeInterval, str]] = []
    for segment in segments:
        text = segment.translation if german else segment.source_text
        if text and text.strip():
            result.append((segment.interval, text.strip()))
    return result
