"""Stages that produce the German side of the dub.

This is where the central difficulty of English-to-German dubbing lives. German is typically
10-30 % longer than the equivalent English, but the timeline slot is fixed by the original
narration. Four remedies exist, applied in order of how much they damage the result:

1. ask for a shorter translation,
2. speak slightly faster,
3. stretch the audio acoustically, within a bound,
4. flag the segment and let a person decide.

Anything past the configured bounds is flagged rather than forced, because a segment
crushed by 30 % sounds worse than one that overruns slightly (questions.md Q-C6).
"""

from __future__ import annotations

import logging

from germandubi.application.ports.providers import SynthesisRequest, TranslationRequest
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.segment import (
    DurationFit,
    SpeechSegment,
    TextOrigin,
)
from germandubi.domain.errors import SynthesisError
from germandubi.domain.value_objects.content_hash import hash_inputs
from germandubi.worker.context import StageContext

__all__ = ["handle_fit", "handle_prosody", "handle_synthesize", "handle_translate"]

logger = logging.getLogger(__name__)

#: Flags a segment can carry into review.
FLAG_TOO_LONG = "duration_overrun"
FLAG_STRETCHED = "time_stretched"
FLAG_SYNTHESIS_FAILED = "synthesis_failed"
FLAG_LOW_CONFIDENCE = "low_transcription_confidence"

#: German characters that fit in one second of speech at a natural rate. Used only to ask
#: the translator for something shorter; the real duration always comes from measurement.
_CHARACTERS_PER_SECOND = 15.0


def handle_translate(context: StageContext) -> None:
    """Translate every untranslated segment into German.

    A human correction is never overwritten: a segment whose German text was written by a
    person is skipped, so re-running this stage after an edit does not undo the edit.

    Args:
        context: The stage context.

    Raises:
        TranslationError: If translation fails.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    pending = [s for s in segments if not s.is_translated and not s.has_human_translation]
    if not pending:
        context.progress(1.0, "already translated")
        return

    provider = context.registry.translation()
    context.progress(0.02, f"using {provider.info.name}")
    by_ordinal = {s.ordinal: s for s in segments}

    done = 0
    for segment in pending:
        context.checkpoint()
        request = TranslationRequest(
            text=segment.source_text,
            preceding=_text_at(by_ordinal, segment.ordinal - 1),
            following=_text_at(by_ordinal, segment.ordinal + 1),
            max_characters=_character_budget(segment),
        )
        result = provider.translate(request)
        translated = segment.with_translation(result.text, origin=TextOrigin.MACHINE_TRANSLATION)
        context.uow.segments.save(translated)
        context.uow.segments.add_translation_revision(
            segment.id,
            text=result.text,
            origin=TextOrigin.MACHINE_TRANSLATION,
            provider_id=result.provider_id,
            model_id=result.model_id,
        )
        done += 1
        context.progress(done / len(pending), f"{done} / {len(pending)} segments")

    context.uow.flush()
    context.event("translation_ready", {"segments": done})
    logger.info("translated %d segments into German", done)


def handle_prosody(context: StageContext) -> None:
    """Measure how the original narrator delivered each segment.

    Args:
        context: The stage context.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    if not segments:
        context.progress(1.0, None)
        return

    provider = context.registry.prosody()
    master = context.require(ArtifactKind.MASTER_AUDIO)
    context.progress(0.02, f"using {provider.info.name}")

    for index, segment in enumerate(segments, start=1):
        context.checkpoint()
        profile = provider.analyse(master, segment.interval, words=segment.words)
        context.uow.segments.save(segment.with_prosody(profile))
        if index % 10 == 0 or index == len(segments):
            context.progress(index / len(segments), f"{index} / {len(segments)} segments")

    context.uow.flush()
    context.progress(1.0, f"{len(segments)} segments analysed")


def handle_synthesize(context: StageContext) -> None:
    """Generate German speech for every translated segment.

    Speaking rate is pre-adjusted from the translation's length, which is free, before the
    fit stage resorts to acoustic stretching, which is not.

    Args:
        context: The stage context.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    translated = [s for s in segments if s.is_translated]
    if not translated:
        context.progress(1.0, "nothing to synthesize")
        return

    provider = context.registry.tts()
    voice = _pick_voice(provider, context.settings.tts_voice)
    speech_dir = context.directory("speech")
    context.progress(0.02, f"using {provider.info.name}")

    synthesized = 0
    failed = 0
    for index, segment in enumerate(translated, start=1):
        context.checkpoint()
        text = segment.translation or ""
        input_hash = hash_inputs(
            text=text, voice=voice, provider=provider.info.id, target_ms=segment.duration_ms
        )

        reused = context.reusable(
            ArtifactKind.SEGMENT_SPEECH, input_hash, segment_id=str(segment.id)
        )
        if reused is not None:
            synthesized += 1
            continue

        destination = speech_dir / f"segment_{segment.ordinal:05d}.wav"
        rate = _initial_speaking_rate(segment, context)
        try:
            result = provider.synthesize(
                SynthesisRequest(
                    text=text,
                    voice=voice,
                    destination=destination,
                    speaking_rate=rate,
                    target_duration_ms=segment.duration_ms,
                )
            )
        except SynthesisError as exc:
            # One bad segment must not fail a whole video; flag it for review instead.
            logger.warning("segment %d could not be synthesized: %s", segment.ordinal, exc)
            context.uow.segments.save(segment.failed(FLAG_SYNTHESIS_FAILED))
            failed += 1
            continue

        artifact = context.publish(
            ArtifactKind.SEGMENT_SPEECH,
            result.audio_path,
            provider_id=result.provider_id,
            model_id=result.model_id,
            input_hash=input_hash,
            parameters={"voice": voice, "speaking_rate": f"{rate:.3f}"},
            segment_id=str(segment.id),
            media_type="audio/wav",
        )
        context.uow.segments.set_speech_artifact(segment.id, artifact.id)
        context.uow.segments.save(segment.synthesized())
        synthesized += 1
        context.progress(index / len(translated), f"{index} / {len(translated)} segments")

    context.uow.flush()
    context.event("speech_ready", {"segments": synthesized, "failed": failed})
    context.progress(1.0, f"{synthesized} segments" + (f", {failed} failed" if failed else ""))
    logger.info("synthesized %d segments (%d failed)", synthesized, failed)


def handle_fit(context: StageContext) -> None:
    """Fit each segment's German speech into its timeline slot.

    Measures what synthesis actually produced, applies a bounded acoustic stretch when that
    closes the gap, and flags anything still over the threshold rather than crushing it.

    Args:
        context: The stage context.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    with_speech = [
        (segment, context.uow.segments.speech_artifact_id(segment.id)) for segment in segments
    ]
    pending = [(s, a) for s, a in with_speech if a is not None]
    if not pending:
        context.progress(1.0, "nothing to fit")
        return

    media = context.registry.media()
    max_stretch = context.settings.max_time_stretch
    warn_at = context.settings.duration_warning_threshold
    overrunning = 0

    for index, (segment, artifact_id) in enumerate(pending, start=1):
        context.checkpoint()
        assert artifact_id is not None  # noqa: S101 - guaranteed by the filter above
        artifact = context.uow.artifacts.get(artifact_id)
        path = context.uow.store.path_for(artifact)
        generated_ms = media.probe(path).duration_ms

        fit = DurationFit(target_ms=segment.duration_ms, generated_ms=generated_ms)
        flags = set(segment.flags)
        applied = 1.0

        if fit.deviation > 0:
            # Only stretch by as much as is needed, and never past the configured bound.
            needed = fit.generated_ms / fit.target_ms
            factor = min(needed, 1.0 + max_stretch)
            if factor > 1.001:
                stretched = path.with_name(f"{path.stem}_fitted.wav")
                media.time_stretch(path, stretched, factor=factor)
                applied = factor
                flags.add(FLAG_STRETCHED)
                fitted = context.publish(
                    ArtifactKind.SEGMENT_SPEECH,
                    stretched,
                    provider_id="ffmpeg",
                    input_hash=hash_inputs(source=artifact.content_hash, factor=round(factor, 4)),
                    parameters={"factor": f"{factor:.4f}"},
                    segment_id=str(segment.id),
                    media_type="audio/wav",
                )
                context.uow.segments.set_speech_artifact(segment.id, fitted.id)
                generated_ms = media.probe(stretched).duration_ms
                fit = DurationFit(
                    target_ms=segment.duration_ms,
                    generated_ms=generated_ms,
                    applied_rate=applied,
                )

        if fit.deviation > warn_at:
            flags.add(FLAG_TOO_LONG)
            overrunning += 1
        else:
            flags.discard(FLAG_TOO_LONG)

        context.uow.segments.save(segment.with_fit(fit, flags=frozenset(flags)))
        if index % 10 == 0 or index == len(pending):
            context.progress(index / len(pending), f"{index} / {len(pending)} segments")

    context.uow.flush()
    context.event("fit_ready", {"segments": len(pending), "overrunning": overrunning})
    detail = f"{len(pending)} segments"
    if overrunning:
        detail += f", {overrunning} need attention"
    context.progress(1.0, detail)
    logger.info("fitted %d segments, %d still overrunning", len(pending), overrunning)


# --- helpers ----------------------------------------------------------------------------


def _text_at(by_ordinal: dict[int, SpeechSegment], ordinal: int) -> str | None:
    """Return a neighbouring segment's English text, for translation context."""
    neighbour = by_ordinal.get(ordinal)
    return neighbour.source_text if neighbour else None


def _character_budget(segment: SpeechSegment) -> int:
    """Return how many German characters plausibly fit in the segment's slot.

    A soft hint to the translator, not a hard limit: a provider that cannot honour it
    returns its natural output and the fit stage deals with the consequences.
    """
    return max(20, round(segment.duration_ms / 1000 * _CHARACTERS_PER_SECOND))


def _initial_speaking_rate(segment: SpeechSegment, context: StageContext) -> float:
    """Choose a speaking rate from how much longer the German text is than its slot allows.

    Adjusting the rate at synthesis time is free and sounds better than stretching audio
    afterwards, so it is tried first, within the configured bound.
    """
    text = segment.translation or ""
    if not text:
        return 1.0
    estimated_ms = len(text) / _CHARACTERS_PER_SECOND * 1000
    if estimated_ms <= segment.duration_ms:
        return 1.0
    needed = estimated_ms / segment.duration_ms
    return min(needed, 1.0 + context.settings.max_speaking_rate_adjustment)


def _pick_voice(provider: object, configured: str) -> str:
    """Return the voice to use, falling back to the provider's first available one."""
    voices = provider.available_voices()  # type: ignore[attr-defined]
    if configured in voices:
        return str(configured)
    return str(voices[0]) if voices else configured
