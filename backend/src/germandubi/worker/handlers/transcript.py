"""Stages that turn source audio into reviewable English dubbing segments."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.errors import CaptionError, TranscriptionError
from germandubi.domain.segmentation import SegmentationOptions, build_segments
from germandubi.domain.transcript import Transcript, TranscriptCue, TranscriptSource
from germandubi.domain.value_objects.content_hash import hash_inputs
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.worker.context import StageContext

__all__ = ["handle_align", "handle_segment", "handle_transcribe"]

logger = logging.getLogger(__name__)


def handle_transcribe(context: StageContext) -> None:
    """Obtain a timed English transcript, from captions or by recognition.

    The registry decides which source to use; this stage is only responsible for running it
    and persisting the canonical result.

    Args:
        context: The stage context.

    Raises:
        TranscriptionError: If no usable transcript can be produced.
    """
    audio = context.require(ArtifactKind.ASR_AUDIO)
    caption_path, automatic = _best_caption(context)

    provider = context.registry.transcription(
        caption_path=caption_path, caption_is_automatic=automatic
    )
    context.progress(0.1, f"using {provider.info.name}")

    try:
        transcript = provider.transcribe(audio, language="en")
    except CaptionError as exc:
        # Captions were selected but turned out unusable; recognition is the fallback.
        logger.warning("captions were unusable (%s); falling back to recognition", exc)
        context.checkpoint()
        provider = context.registry.transcription()
        transcript = provider.transcribe(audio, language="en")

    context.checkpoint()
    if not transcript.cues:
        msg = "no English speech was found in this source"
        raise TranscriptionError(msg)

    path = context.directory("transcript") / "transcript.json"
    path.write_text(_serialize(transcript), encoding="utf-8")
    context.publish(
        ArtifactKind.TRANSCRIPT,
        path,
        provider_id=transcript.provider_id,
        model_id=transcript.model_id,
        input_hash=hash_inputs(audio=audio.name, provider=transcript.provider_id),
        parameters={"source": transcript.source.value},
        media_type="application/json",
    )
    context.event(
        "transcript_ready",
        {
            "cues": len(transcript.cues),
            "source": transcript.source.value,
            "has_word_timing": transcript.has_word_timing,
        },
    )
    context.progress(1.0, f"{len(transcript.cues)} cues")
    logger.info("transcript: %d cues from %s", len(transcript.cues), transcript.source.value)


def handle_align(context: StageContext) -> None:
    """Ensure the transcript carries word-level timing.

    Recognition already emits word timestamps, so this is a no-op on that path. It matters
    for the caption path, where timing is only per-cue and precise pause reconstruction and
    re-segmentation would otherwise be impossible.

    Args:
        context: The stage context.
    """
    transcript = _load_transcript(context)
    if transcript.has_word_timing:
        context.progress(1.0, "word timing already present")
        return

    context.progress(0.2, "aligning word timing")
    audio = context.require(ArtifactKind.ASR_AUDIO)
    provider = context.registry.alignment()
    aligned = provider.align(audio, transcript)
    context.checkpoint()

    path = context.directory("transcript") / "aligned.json"
    path.write_text(_serialize(aligned), encoding="utf-8")
    context.publish(
        ArtifactKind.ALIGNMENT,
        path,
        provider_id=provider.info.id,
        input_hash=hash_inputs(transcript=transcript.text, provider=provider.info.id),
        media_type="application/json",
    )
    context.progress(1.0, f"{len(aligned.words)} words")


def handle_segment(context: StageContext) -> None:
    """Group the transcript into dubbing segments.

    Re-segmentation replaces the whole set, which destroys segment identity and with it
    every human correction attached to it. So this stage is idempotent by input hash: when
    the transcript and the segmentation options are unchanged, the existing segments are
    already the right answer and are left alone. Without this, re-running the full pipeline
    after a manual edit would silently discard the edit.

    Args:
        context: The stage context.
    """
    transcript = _load_transcript(context, prefer_aligned=True)
    options = SegmentationOptions()
    input_hash = hash_inputs(
        transcript=transcript.text,
        cues=[(c.start_ms, c.end_ms) for c in transcript.cues],
        max_duration_ms=options.max_duration_ms,
        min_duration_ms=options.min_duration_ms,
        max_gap_ms=options.max_gap_ms,
        max_characters=options.max_characters,
    )

    existing = context.uow.segments.list_for_project(context.project.id)
    if existing and context.reusable(ArtifactKind.SEGMENTS, input_hash) is not None:
        context.progress(1.0, f"{len(existing)} segments unchanged")
        logger.info("transcript unchanged; keeping %d existing segments", len(existing))
        return

    context.progress(0.3, "creating dubbing segments")
    segments = build_segments(transcript, project_id=context.project.id, options=options)
    context.checkpoint()
    context.uow.segments.replace_all(context.project.id, list(segments))
    context.uow.flush()

    manifest = context.directory("transcript") / "segments.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "count": len(segments),
                "segments": [
                    {
                        "ordinal": s.ordinal,
                        "start_ms": s.interval.start_ms,
                        "end_ms": s.interval.end_ms,
                        "text": s.source_text,
                    }
                    for s in segments
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    context.publish(
        ArtifactKind.SEGMENTS,
        manifest,
        provider_id="germandubi",
        input_hash=input_hash,
        media_type="application/json",
    )

    context.event(
        "segments_ready",
        {"count": len(segments), "duration_ms": transcript.duration_ms},
    )
    context.progress(1.0, f"{len(segments)} segments")
    logger.info("created %d dubbing segments", len(segments))


# --- transcript serialization -----------------------------------------------------------


def _serialize(transcript: Transcript) -> str:
    """Render a transcript as the canonical JSON artifact.

    A stable, explicit shape is used rather than whatever the provider returned, so the
    artifact stays readable and diffable as providers change.
    """
    return json.dumps(
        {
            "version": 1,
            "language": transcript.language,
            "source": transcript.source.value,
            "provider_id": transcript.provider_id,
            "model_id": transcript.model_id,
            "cues": [
                {
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "text": cue.text,
                    "confidence": cue.confidence,
                    "words": [
                        {
                            "start_ms": w.start_ms,
                            "end_ms": w.end_ms,
                            "text": w.text,
                            "confidence": w.confidence,
                        }
                        for w in cue.words
                    ],
                }
                for cue in transcript.cues
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _deserialize(payload: str) -> Transcript:
    """Rebuild a transcript from its JSON artifact.

    Raises:
        TranscriptionError: If the artifact cannot be read.
    """
    from germandubi.domain.entities.segment import Word

    try:
        data = json.loads(payload)
        cues = [
            TranscriptCue(
                interval=TimeInterval(cue["start_ms"], cue["end_ms"]),
                text=cue["text"],
                words=tuple(
                    Word(w["start_ms"], w["end_ms"], w["text"], confidence=w.get("confidence"))
                    for w in cue.get("words", [])
                ),
                confidence=cue.get("confidence"),
            )
            for cue in data["cues"]
        ]
        return Transcript(
            source=TranscriptSource(data["source"]),
            cues=tuple(cues),
            provider_id=data["provider_id"],
            model_id=data.get("model_id"),
            language=data.get("language", "en"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"the stored transcript could not be read: {exc}"
        raise TranscriptionError(msg) from exc


def _load_transcript(context: StageContext, *, prefer_aligned: bool = False) -> Transcript:
    """Load the current transcript artifact.

    Args:
        context: The stage context.
        prefer_aligned: Whether to prefer the aligned transcript when one exists.

    Returns:
        The transcript.

    Raises:
        ResourceError: If no transcript has been produced.
    """
    if prefer_aligned:
        aligned = context.latest(ArtifactKind.ALIGNMENT)
        if aligned is not None:
            return _deserialize(context.uow.store.read_text(aligned))
    return _deserialize(context.uow.store.read_text_at(context.require(ArtifactKind.TRANSCRIPT)))


def _best_caption(context: StageContext) -> tuple[Path | None, bool]:
    """Return the caption file to prefer, and whether it is machine-generated.

    Manual captions are chosen over automatic ones because they are punctuated and cased.
    """
    artifacts = [
        a
        for a in context.uow.artifacts.list_for_project(context.project.id)
        if a.kind is ArtifactKind.SOURCE_CAPTIONS
    ]
    if not artifacts:
        return None, False

    def is_automatic(parameters: dict[str, str]) -> bool:
        return parameters.get("automatic", "False") == "True"

    manual = [a for a in artifacts if a.provenance and not is_automatic(a.provenance.parameters)]
    chosen = manual[0] if manual else artifacts[0]
    automatic = bool(chosen.provenance and is_automatic(chosen.provenance.parameters))
    return context.uow.store.path_for(chosen), automatic
