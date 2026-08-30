"""Deterministic fake providers.

These exist so the entire product flow - create a project, run the pipeline, review a
segment, regenerate it, export - can be tested end to end without a GPU, a network
connection or a multi-gigabyte model. Default CI runs on these exclusively.

Every fake is deterministic by construction: the same input produces byte-identical output.
That is what makes golden-file assertions and E2E tests stable rather than flaky.
"""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import replace
from pathlib import Path
from typing import Final

from germandubi.application.ports.providers import (
    AcquisitionRequest,
    AcquisitionResult,
    ProviderInfo,
    SeparationResult,
    SynthesisRequest,
    SynthesisResult,
    TranslationRequest,
    TranslationResult,
)
from germandubi.domain.entities.project import SourceMedia, SourceRef
from germandubi.domain.entities.segment import ProsodyProfile, Word
from germandubi.domain.errors import (
    SourceAcquisitionError,
    SynthesisError,
    TranslationError,
)
from germandubi.domain.transcript import Transcript, TranscriptCue, TranscriptSource
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = [
    "FakeAcquisitionProvider",
    "FakeProbeProvider",
    "FakeProsodyProvider",
    "FakeSeparationProvider",
    "FakeTTSProvider",
    "FakeTranscriptionProvider",
    "FakeTranslationProvider",
]

_SAMPLE_RATE: Final = 22_050
#: Roughly the speaking rate of a calm narrator, used to derive a plausible duration.
_CHARACTERS_PER_SECOND: Final = 14.0
_MIN_SPEECH_MS: Final = 400


# --- source -----------------------------------------------------------------------------


class FakeProbeProvider:
    """Reports fixed metadata for any source, without network access."""

    def __init__(self, media: SourceMedia | None = None) -> None:
        """Initialise the provider.

        Args:
            media: The metadata to report. Defaults to a short single-narrator clip.
        """
        self._media = media or SourceMedia(
            title="Fake narration clip",
            duration_ms=30_000,
            uploader="GermanDubI test fixtures",
            video_codec="h264",
            audio_codec="aac",
            width=320,
            height=240,
        )

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(id="fake_probe", name="Fake source probe", deterministic=True)

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def probe(self, source: SourceRef) -> SourceMedia:
        """Return the configured metadata.

        Args:
            source: Ignored; kept to satisfy the port.

        Returns:
            The configured source metadata.
        """
        del source
        return self._media


class FakeAcquisitionProvider:
    """Copies a fixture media file into the project workspace instead of downloading."""

    def __init__(self, fixture: Path) -> None:
        """Initialise the provider.

        Args:
            fixture: A small local media file to use as the "downloaded" source.
        """
        self.fixture = fixture

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(id="fake_acquire", name="Fake acquisition", deterministic=True)

    def is_available(self) -> bool:
        """Return whether the fixture file exists."""
        return self.fixture.exists()

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        """Copy the fixture into the destination directory.

        Args:
            request: Where to place the media.

        Returns:
            The path to the copied file.

        Raises:
            SourceAcquisitionError: If the fixture is missing.
        """
        if not self.fixture.exists():
            msg = f"the test fixture is missing: {self.fixture}"
            raise SourceAcquisitionError(msg, path=str(self.fixture))
        request.destination.mkdir(parents=True, exist_ok=True)
        target = request.destination / f"source{self.fixture.suffix}"
        target.write_bytes(self.fixture.read_bytes())
        return AcquisitionResult(video_path=target)


# --- transcript -------------------------------------------------------------------------


class FakeTranscriptionProvider:
    """Emits a fixed English transcript with plausible word timing."""

    #: A short narration with the features that matter: punctuation, a proper name, a
    #: number, and both a short and a long sentence.
    SCRIPT: Final[tuple[tuple[int, int, str], ...]] = (
        (500, 3500, "The important thing about dubbing is the timing."),
        (3800, 8200, "When Doctor Sommer recorded these 42 examples, every pause mattered."),
        (8600, 11_000, "In this case, the German text runs longer."),
        (11_400, 13_000, "That is the whole problem."),
    )

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="fake_asr", name="Fake transcription", model_id="script-v1", deterministic=True
        )

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def transcribe(self, audio: Path, *, language: str = "en") -> Transcript:
        """Return the fixed script as a canonical transcript.

        Args:
            audio: Ignored; kept to satisfy the port.
            language: Ignored; always English.

        Returns:
            The fixed transcript, with word timing distributed across each cue.
        """
        del audio, language
        cues = [
            TranscriptCue(
                interval=TimeInterval(start, end),
                text=text,
                words=_distribute_words(text, TimeInterval(start, end)),
                confidence=0.95,
            )
            for start, end, text in self.SCRIPT
        ]
        return Transcript.from_raw(
            cues,
            source=TranscriptSource.ASR,
            provider_id=self.info.id,
            model_id=self.info.model_id,
        )


def _distribute_words(text: str, interval: TimeInterval) -> tuple[Word, ...]:
    """Spread a cue's duration across its words, in proportion to word length.

    Args:
        text: The cue text.
        interval: The cue's timing.

    Returns:
        Word timing covering the interval without gaps or overlaps.
    """
    words = text.split()
    if not words:
        return ()
    total = sum(len(w) for w in words)
    cursor = interval.start_ms
    result: list[Word] = []
    for index, word in enumerate(words):
        is_last = index == len(words) - 1
        share = max(1, round(interval.duration_ms * len(word) / total))
        end = interval.end_ms if is_last else min(cursor + share, interval.end_ms - 1)
        if end <= cursor:
            end = cursor + 1
        result.append(Word(cursor, end, word, confidence=0.95))
        cursor = end
    return tuple(result)


class FakeAlignmentProvider:
    """Fills in word timing that a caption-based transcript does not carry."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(id="fake_align", name="Fake alignment", deterministic=True)

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def align(self, audio: Path, transcript: Transcript) -> Transcript:
        """Distribute each cue's duration across its words.

        Args:
            audio: Ignored; kept to satisfy the port.
            transcript: The transcript to annotate.

        Returns:
            The transcript with word timing filled in.
        """
        del audio
        return replace(
            transcript,
            cues=tuple(
                replace(cue, words=cue.words or _distribute_words(cue.text, cue.interval))
                for cue in transcript.cues
            ),
        )


# --- translation ------------------------------------------------------------------------


class FakeTranslationProvider:
    """Produces deterministic, recognizably German-shaped output.

    A word-for-word substitution is not a translation, and it is not meant to be. What
    matters for testing the pipeline is that the output is deterministic, is different from
    the input, and is realistically **longer** than the English - which is exactly the
    condition the duration-fitting stages exist to handle.
    """

    #: Enough real vocabulary that fixture output reads as German rather than noise.
    DICTIONARY: Final[dict[str, str]] = {
        "the": "die",
        "a": "eine",
        "an": "eine",
        "is": "ist",
        "are": "sind",
        "was": "war",
        "were": "waren",
        "and": "und",
        "or": "oder",
        "but": "aber",
        "in": "in",
        "on": "auf",
        "at": "bei",
        "of": "von",
        "to": "zu",
        "for": "fuer",
        "with": "mit",
        "this": "dieses",
        "that": "dass",
        "these": "diese",
        "it": "es",
        "we": "wir",
        "you": "Sie",
        "they": "sie",
        "he": "er",
        "she": "sie",
        "important": "entscheidend",
        "thing": "Angelegenheit",
        "about": "ueber",
        "dubbing": "Synchronisation",
        "timing": "Zeitabstimmung",
        "when": "als",
        "doctor": "Doktor",
        "recorded": "aufgezeichnet",
        "examples": "Beispiele",
        "every": "jede",
        "pause": "Pause",
        "mattered": "war von Bedeutung",
        "case": "Fall",
        "german": "deutsche",
        "text": "Text",
        "runs": "laeuft",
        "longer": "laenger",
        "problem": "Schwierigkeit",
        "whole": "gesamte",
        "means": "bedeutet",
        "because": "weil",
        "which": "welche",
        "while": "waehrend",
        "so": "also",
        "not": "nicht",
        "very": "sehr",
        "more": "mehr",
        "than": "als",
    }
    #: Applied to any word not in the dictionary, so output stays deterministic and long.
    _SUFFIX: Final = "ung"

    def __init__(self, *, expansion: float = 1.2) -> None:
        """Initialise the provider.

        Args:
            expansion: Roughly how much longer than the English the German should be. The
                default reflects the real English-to-German expansion the pipeline must
                cope with.
        """
        self.expansion = expansion

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="fake_translate",
            name="Fake EN-DE translation",
            model_id="dictionary-v1",
            deterministic=True,
        )

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate one segment deterministically.

        Args:
            request: The text and its context. ``max_characters`` is honoured, so the
                duration-aware retranslation loop can be tested.

        Returns:
            The German rendering.

        Raises:
            TranslationError: If the text is empty, matching the real providers.
        """
        if not request.text.strip():
            msg = "cannot translate empty text"
            raise TranslationError(msg)
        german = self._render(request.text, glossary=request.glossary)
        if request.max_characters is not None and len(german) > request.max_characters:
            german = self._shorten(german, request.max_characters)
        return TranslationResult(text=german, provider_id=self.info.id, model_id=self.info.model_id)

    def translate_batch(self, requests: list[TranslationRequest]) -> list[TranslationResult]:
        """Translate several segments.

        Args:
            requests: The segments to translate.

        Returns:
            One result per request, in order.
        """
        return [self.translate(request) for request in requests]

    def _render(self, text: str, *, glossary: dict[str, str]) -> str:
        """Map an English sentence onto deterministic German-shaped text."""
        lowered_glossary = {k.lower(): v for k, v in glossary.items()}
        pieces: list[str] = []
        for token in text.split():
            stripped = token.strip(".,!?;:\"'")
            trailing = token[len(stripped) :] if stripped else token
            key = stripped.lower()
            if key in lowered_glossary:
                word = lowered_glossary[key]
            elif key in self.DICTIONARY:
                word = self.DICTIONARY[key]
            elif stripped.isdigit():
                word = stripped
            elif stripped:
                word = f"{stripped.capitalize()}{self._SUFFIX}"
            else:
                word = stripped
            pieces.append(f"{word}{trailing}")
        return " ".join(pieces)

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        """Drop trailing words until the text fits, keeping the sentence terminator."""
        terminator = text[-1] if text and text[-1] in ".!?" else ""
        words = text.rstrip(".!?").split()
        while words and len(" ".join(words)) + len(terminator) > limit:
            words.pop()
        return " ".join(words) + terminator if words else text[:limit]


# --- speech -----------------------------------------------------------------------------


class FakeTTSProvider:
    """Writes a deterministic tone whose length is derived from the text.

    The audio is not speech, but it has the property the pipeline actually depends on: a
    duration that varies realistically with the text, so duration fitting, overrun flagging
    and timeline assembly are all exercised for real.
    """

    VOICES: Final[tuple[str, ...]] = ("de_DE-fake-medium", "de_DE-fake-low")

    def __init__(self, *, characters_per_second: float = _CHARACTERS_PER_SECOND) -> None:
        """Initialise the provider.

        Args:
            characters_per_second: How fast the fake voice "speaks".
        """
        self.characters_per_second = characters_per_second

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="fake_tts", name="Fake German TTS", model_id="tone-v1", deterministic=True
        )

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def available_voices(self) -> tuple[str, ...]:
        """Return the fake voice identifiers."""
        return self.VOICES

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Write a tone of a text-derived length.

        Args:
            request: The text, voice and destination.

        Returns:
            The written audio and its exact duration.

        Raises:
            SynthesisError: If the text is empty or the speaking rate is not positive.
        """
        if not request.text.strip():
            msg = "cannot synthesize empty text"
            raise SynthesisError(msg)
        if request.speaking_rate <= 0:
            msg = f"speaking rate must be positive, got {request.speaking_rate}"
            raise SynthesisError(msg, speaking_rate=request.speaking_rate)

        seconds = len(request.text) / (self.characters_per_second * request.speaking_rate)
        duration_ms = max(_MIN_SPEECH_MS, round(seconds * 1000))
        _write_tone(request.destination, duration_ms=duration_ms, frequency=180.0)
        return SynthesisResult(
            audio_path=request.destination,
            duration_ms=duration_ms,
            sample_rate=_SAMPLE_RATE,
            provider_id=self.info.id,
            model_id=request.voice,
        )


def _write_tone(destination: Path, *, duration_ms: int, frequency: float) -> None:
    """Write a mono 16-bit WAV containing a fading sine tone.

    Uses the standard library's ``wave`` module rather than FFmpeg, so the fakes work even
    where FFmpeg is unavailable.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = int(_SAMPLE_RATE * duration_ms / 1000)
    samples = bytearray()
    for index in range(frames):
        # A short fade at each end avoids the click an abrupt start would produce.
        envelope = min(1.0, index / 200, (frames - index) / 200)
        value = int(12000 * envelope * math.sin(2 * math.pi * frequency * index / _SAMPLE_RATE))
        samples += struct.pack("<h", value)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        handle.writeframes(bytes(samples))


# --- prosody and separation -------------------------------------------------------------


class FakeProsodyProvider:
    """Reports a delivery profile derived from the segment's own timing."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(id="fake_prosody", name="Fake prosody analysis", deterministic=True)

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def analyse(
        self, audio: Path, interval: TimeInterval, *, words: tuple[Word, ...] = ()
    ) -> ProsodyProfile:
        """Return a delivery profile computed from the timing alone.

        Args:
            audio: Ignored; kept to satisfy the port.
            interval: The segment's slot on the timeline.
            words: Word timing for the segment.

        Returns:
            A plausible, deterministic delivery profile.
        """
        del audio
        count = len(words) or 1
        return ProsodyProfile(
            speech_rate_wps=count / (interval.duration_ms / 1000.0),
            pause_before_ms=0,
            pause_after_ms=0,
            energy_rms=0.5,
        )


class FakeSeparationProvider:
    """Produces stems by copying the input, so the mix stage can be exercised."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(id="fake_separate", name="Fake separation", deterministic=True)

    def is_available(self) -> bool:
        """Return that the fake is always available."""
        return True

    def separate(self, audio: Path, destination: Path) -> SeparationResult:
        """Write a background and a voice stem.

        Args:
            audio: The master audio.
            destination: Directory to write the stems into.

        Returns:
            Paths to the produced stems.
        """
        destination.mkdir(parents=True, exist_ok=True)
        background = destination / "background.wav"
        voice = destination / "voice.wav"
        payload = audio.read_bytes()
        background.write_bytes(payload)
        voice.write_bytes(payload)
        return SeparationResult(
            background_path=background,
            voice_path=voice,
            provider_id=self.info.id,
            model_id="passthrough",
        )
