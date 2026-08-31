"""The German voices a project can be narrated with, and samples of each.

A list of identifiers like ``de_DE-pavoque-low`` asks someone to choose a narrator they
have never heard. The sample endpoint is what makes the list answerable: a few seconds of
each voice, synthesized once and cached, so the choice is made by ear.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from germandubi.api.dependencies import AppDep
from germandubi.api.schemas import VoiceStatus
from germandubi.application.ports.providers import SynthesisRequest
from germandubi.domain.errors import GermanDubIError
from germandubi.infrastructure.providers.piper import GERMAN_VOICES

router = APIRouter(tags=["voices"])

logger = logging.getLogger(__name__)

#: Spoken for every sample. Short enough to synthesize quickly, long enough to judge a
#: narrator by, and it says what the product does rather than being filler.
SAMPLE_TEXT = "Guten Tag. So klingt diese Stimme, wenn sie Ihr Video auf Deutsch erzählt."


def _describe(name: str) -> VoiceStatus:
    """Split a Piper voice identifier into something a person can read."""
    parts = name.split("-")
    speaker = parts[1].replace("_", " ").title() if len(parts) > 2 else name
    quality = parts[-1].replace("_", " ") if len(parts) > 2 else "unknown"
    return VoiceStatus(id=name, speaker=speaker, quality=quality, downloaded=False)


@router.get(
    "/voices",
    response_model=list[VoiceStatus],
    summary="Available German voices",
    description=(
        "The German narrators a project can use. `downloaded` says whether the model is "
        "already on this machine; one that is not is fetched on first use."
    ),
    operation_id="listVoices",
)
async def list_voices(app: AppDep) -> list[VoiceStatus]:
    """Return the catalogue, voices already on disk first.

    Args:
        app: The wired application.

    Returns:
        Every known German voice with its readable name and download state.
    """
    provider = app.registry.tts()
    ordered: tuple[str, ...] = getattr(provider, "available_voices", lambda: GERMAN_VOICES)()
    voices_dir: Path | None = getattr(provider, "voices_dir", None)
    installed = {path.stem for path in voices_dir.glob("*.onnx")} if voices_dir else set()

    described = []
    for name in ordered:
        voice = _describe(name)
        described.append(voice.model_copy(update={"downloaded": name in installed}))
    return described


@router.get(
    "/voices/{voice}/sample",
    summary="Hear a voice",
    description=(
        "A few seconds of German in this voice, so the choice can be made by ear. "
        "Synthesized once and cached; the first request for an undownloaded voice also "
        "fetches its model and is therefore slow."
    ),
    operation_id="getVoiceSample",
    responses={404: {"description": "No such voice."}},
)
async def get_voice_sample(voice: str, app: AppDep) -> FileResponse:
    """Return a cached audio sample of one voice.

    Args:
        voice: The voice identifier, which must be one this build knows.
        app: The wired application.

    Returns:
        A WAV file of the sample.

    Raises:
        HTTPException: If the voice is unknown, or synthesis fails.
    """
    # The name becomes part of a cache path, so it is matched against the catalogue this
    # build actually offers rather than sanitized. Anything else is a 404, which also keeps
    # the endpoint honest with whichever provider is selected.
    if voice not in {known.id for known in await list_voices(app)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown voice {voice!r}")

    cache = app.settings.models_dir / "samples"
    cache.mkdir(parents=True, exist_ok=True)
    # The text is part of the key so an edited sample line does not serve stale audio.
    digest = hashlib.sha256(SAMPLE_TEXT.encode()).hexdigest()[:8]
    destination = cache / f"{voice}.{digest}.wav"

    if not destination.exists():
        try:
            app.registry.tts().synthesize(
                SynthesisRequest(text=SAMPLE_TEXT, voice=voice, destination=destination)
            )
        except GermanDubIError as error:
            logger.warning("could not synthesize a sample for %s: %s", voice, error.message)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.message
            ) from error

    return FileResponse(destination, media_type="audio/wav", filename=f"{voice}.wav")
