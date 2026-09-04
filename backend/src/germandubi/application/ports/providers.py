"""Provider port definitions.

Each port is deliberately narrow: it takes application-owned types and returns
application-owned types. Provider output is mapped into these at the adapter boundary, so
that a third-party schema never becomes the canonical domain representation. The raw
provider response may still be kept as a diagnostic artifact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from germandubi.domain.entities.project import SourceMedia, SourceRef
from germandubi.domain.entities.segment import ProsodyProfile, Word
from germandubi.domain.transcript import Transcript
from germandubi.domain.value_objects.timeline import TimeInterval

__all__ = [
    "AcquisitionProvider",
    "AcquisitionRequest",
    "AcquisitionResult",
    "AlignmentProvider",
    "AudioInfo",
    "MediaToolkit",
    "MixRequest",
    "ProbeProvider",
    "ProsodyProvider",
    "Provider",
    "ProviderInfo",
    "ProviderKind",
    "SeparationProvider",
    "SeparationResult",
    "SynthesisRequest",
    "SynthesisResult",
    "TTSProvider",
    "TranscriptionProvider",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
]


class ProviderKind(StrEnum):
    """Whether using a provider sends data off the machine.

    The UI must state this before a network provider is used, so it is part of the port
    rather than documentation (``docs/product/vision.md`` section 3.4).
    """

    LOCAL = "local"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Identity and capabilities of a provider implementation.

    Attributes:
        id: Stable identifier recorded in artifact provenance, e.g. ``piper``.
        name: Human-readable name for the settings screen.
        kind: Whether the provider is local or sends data over the network.
        model_id: The model or voice in use, when applicable.
        deterministic: Whether the same input reliably yields the same output. Only
            deterministic providers may be used in default CI.
        requires: External packages or tools the provider needs, for the doctor command.
        notes: Anything the user should know, such as a license restriction.
    """

    id: str
    name: str
    kind: ProviderKind = ProviderKind.LOCAL
    model_id: str | None = None
    deterministic: bool = False
    requires: tuple[str, ...] = ()
    notes: str | None = None


@runtime_checkable
class Provider(Protocol):
    """Common behaviour every provider implementation exposes."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity, recorded in artifact provenance."""
        ...

    def is_available(self) -> bool:
        """Return whether this provider can run right now.

        Checks for the presence of its dependencies and model files without downloading
        anything. Used by ``germandubi doctor`` and by automatic provider selection.
        """
        ...


# --- source inspection and acquisition --------------------------------------------------


@runtime_checkable
class ProbeProvider(Provider, Protocol):
    """Inspects a source cheaply, before any large download."""

    def probe(self, source: SourceRef) -> SourceMedia:
        """Inspect the source and report what is available.

        Args:
            source: The validated source reference.

        Returns:
            Title, duration, available caption tracks and stream formats.

        Raises:
            SourceAcquisitionError: If the source cannot be inspected.
        """
        ...


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    """What to download and where to put it.

    Attributes:
        source: The validated source reference.
        destination: Directory inside the project workspace to write into.
        want_captions: Whether to fetch English caption tracks.
        prefer_manual_captions: Whether to prefer human-written captions when both exist.
    """

    source: SourceRef
    destination: Path
    want_captions: bool = True
    prefer_manual_captions: bool = True


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """What acquisition produced.

    Attributes:
        video_path: The downloaded media file.
        caption_paths: Caption files, keyed by whether they are automatic.
        media: Refreshed source metadata observed during download.
    """

    video_path: Path
    caption_paths: dict[bool, Path] = field(default_factory=dict)
    media: SourceMedia | None = None


@runtime_checkable
class AcquisitionProvider(Provider, Protocol):
    """Downloads or copies the source media into the project workspace."""

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        """Fetch the source media and any captions.

        Args:
            request: What to fetch and where to put it.

        Returns:
            Paths to the acquired files.

        Raises:
            SourceAcquisitionError: If the media cannot be retrieved.
        """
        ...


# --- transcript -------------------------------------------------------------------------


@runtime_checkable
class TranscriptionProvider(Provider, Protocol):
    """Converts normalized source audio into a timed English transcript."""

    def transcribe(self, audio: Path, *, language: str = "en") -> Transcript:
        """Transcribe speech.

        Args:
            audio: Normalized mono audio prepared for recognition.
            language: The spoken language; always ``en`` in ``0.x``.

        Returns:
            A canonical transcript, with word timing when the provider supplies it.

        Raises:
            TranscriptionError: If recognition fails.
        """
        ...


@runtime_checkable
class AlignmentProvider(Provider, Protocol):
    """Produces word-level timing for a known transcript."""

    def align(self, audio: Path, transcript: Transcript) -> Transcript:
        """Attach word timing to an existing transcript.

        Args:
            audio: Normalized mono audio.
            transcript: The transcript whose text is already known.

        Returns:
            The same transcript with word timing filled in. A provider that cannot improve
            on the input returns it unchanged rather than raising.

        Raises:
            AlignmentError: If alignment fails outright.
        """
        ...


# --- translation ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    """One segment to translate, with the context needed to translate it well.

    Attributes:
        text: The English text.
        preceding: The previous segment's English text, for pronoun and tense continuity.
        following: The next segment's English text.
        glossary: Terms that must be translated a specific way, English to German.
        max_characters: A soft ceiling that asks for a shorter rendering, used by the
            duration-aware loop. ``None`` means translate naturally.
    """

    text: str
    preceding: str | None = None
    following: str | None = None
    glossary: dict[str, str] = field(default_factory=dict)
    max_characters: int | None = None


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """A translated segment.

    Attributes:
        text: The German text.
        provider_id: The provider that produced it.
        model_id: The model used, when applicable.
    """

    text: str
    provider_id: str
    model_id: str | None = None


@runtime_checkable
class TranslationProvider(Provider, Protocol):
    """Translates English segments into German."""

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate one segment.

        Args:
            request: The text and its context.

        Returns:
            The German rendering.

        Raises:
            TranslationError: If translation fails.
        """
        ...

    def translate_batch(self, requests: list[TranslationRequest]) -> list[TranslationResult]:
        """Translate several segments, in order.

        Batching matters because model warm-up dominates per-segment cost for local
        translation models.

        Args:
            requests: The segments to translate.

        Returns:
            One result per request, in the same order.

        Raises:
            TranslationError: If translation fails.
        """
        ...


# --- speech -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    """One German utterance to synthesize.

    Attributes:
        text: The German text.
        voice: The voice identifier.
        destination: Where to write the audio file.
        speaking_rate: Rate multiplier; ``1.0`` is the voice's natural rate. Used to fit
            speech into its slot before falling back to acoustic time-stretching.
        target_duration_ms: The slot the speech should fit, when known.
    """

    text: str
    voice: str
    destination: Path
    speaking_rate: float = 1.0
    target_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Synthesized German speech.

    Attributes:
        audio_path: The written audio file.
        duration_ms: Measured duration of the audio.
        sample_rate: Sample rate of the written file.
        provider_id: The provider that produced it.
        model_id: The voice or model used.
    """

    audio_path: Path
    duration_ms: int
    sample_rate: int
    provider_id: str
    model_id: str | None = None


@runtime_checkable
class TTSProvider(Protocol):
    """Synthesizes German speech."""

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        ...

    def is_available(self) -> bool:
        """Return whether this provider can run right now."""
        ...

    def available_voices(self) -> tuple[str, ...]:
        """Return the voice identifiers this provider can use."""
        ...

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Synthesize one utterance.

        Args:
            request: The text, voice and destination.

        Returns:
            The written audio and its measured duration.

        Raises:
            SynthesisError: If synthesis fails or produces empty audio.
        """
        ...


@runtime_checkable
class ProsodyProvider(Provider, Protocol):
    """Analyses how the original narrator delivered a stretch of speech."""

    def analyse(
        self, audio: Path, interval: TimeInterval, *, words: tuple[Word, ...] = ()
    ) -> ProsodyProfile:
        """Measure delivery characteristics for one segment.

        Args:
            audio: The master audio file.
            interval: The segment's slot on the timeline.
            words: Word timing for the segment, when available.

        Returns:
            The measured delivery profile.
        """
        ...


# --- separation -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeparationResult:
    """The result of splitting narration from everything else.

    Attributes:
        background_path: Music and effects with the narration removed.
        voice_path: The isolated narration, kept for diagnostics and QA.
        provider_id: The provider that produced it.
        model_id: The model used.
    """

    background_path: Path
    voice_path: Path | None
    provider_id: str
    model_id: str | None = None


@runtime_checkable
class SeparationProvider(Provider, Protocol):
    """Separates narration from music and effects."""

    def separate(self, audio: Path, destination: Path) -> SeparationResult:
        """Split the audio into a background stem and a voice stem.

        Args:
            audio: The master audio file.
            destination: Directory to write the stems into.

        Returns:
            Paths to the produced stems.

        Raises:
            SeparationError: If separation fails.
        """
        ...


# --- media toolkit ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AudioInfo:
    """What ``ffprobe`` reports about a media file.

    Attributes:
        duration_ms: Duration in milliseconds.
        sample_rate: Audio sample rate, when the file has audio.
        channels: Audio channel count.
        has_video: Whether a video stream is present.
        video_codec: Video codec name.
        audio_codec: Audio codec name.
        width: Video width in pixels.
        height: Video height in pixels.
    """

    duration_ms: int
    sample_rate: int | None = None
    channels: int | None = None
    has_video: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class MixRequest:
    """How to combine the German narration with the original audio.

    Attributes:
        narration_path: The assembled German narration track.
        background_path: The background stem, when separation ran.
        original_path: The original master audio, used when there is no separation.
        destination: Where to write the mixed audio.
        speech_intervals: Where German speech occurs, used to duck the original audio when
            no separated stem is available.
        duck_db: How far to attenuate the original audio under speech.
    """

    narration_path: Path
    destination: Path
    background_path: Path | None = None
    original_path: Path | None = None
    speech_intervals: tuple[TimeInterval, ...] = ()
    duck_db: float = -18.0


@runtime_checkable
class MediaToolkit(Protocol):
    """The media operations the pipeline needs from FFmpeg.

    Wrapping FFmpeg behind a port keeps the stage handlers testable without spawning
    processes, and keeps every invocation inside the one audited process runner.
    """

    def probe(self, path: Path) -> AudioInfo:
        """Inspect a media file.

        Args:
            path: The file to inspect.

        Returns:
            Stream information.

        Raises:
            MediaProcessingError: If the file cannot be inspected.
        """
        ...

    def extract_audio(
        self, source: Path, destination: Path, *, sample_rate: int, mono: bool
    ) -> Path:
        """Extract and normalize an audio track.

        Args:
            source: The media file.
            destination: Where to write the audio.
            sample_rate: Target sample rate.
            mono: Whether to downmix to one channel.

        Returns:
            The written file.

        Raises:
            MediaProcessingError: If extraction fails.
        """
        ...

    def concatenate_speech(
        self,
        placements: list[tuple[TimeInterval, Path]],
        destination: Path,
        *,
        total_ms: int,
        on_batch: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Assemble per-segment speech into one continuous narration track.

        Each clip is placed at its own timeline position and the gaps are filled with
        silence, so the narration stays synchronized with the video regardless of how the
        individual clips were generated.

        Args:
            placements: Timeline position and audio file for each segment.
            destination: Where to write the narration track.
            total_ms: Total length of the track.
            on_batch: Called with ``(clips placed, clips in total)`` after each batch, so a
                caller can report progress and stay cancellable during a long assembly.

        Returns:
            The written file.

        Raises:
            MixError: If assembly fails.
        """
        ...

    def mix(self, request: MixRequest) -> Path:
        """Combine German narration with background or ducked original audio.

        Args:
            request: What to mix and how.

        Returns:
            The written mixed audio file.

        Raises:
            MixError: If mixing fails.
        """
        ...

    def time_stretch(self, source: Path, destination: Path, *, factor: float) -> Path:
        """Change an audio clip's duration without changing its pitch.

        Args:
            source: The clip to stretch.
            destination: Where to write the result.
            factor: Speed factor; values above ``1.0`` shorten the clip.

        Returns:
            The written file.

        Raises:
            MediaProcessingError: If the operation fails.
        """
        ...

    def mux(
        self,
        *,
        video_source: Path,
        german_audio: Path,
        destination: Path,
        original_audio: Path | None = None,
        subtitles: dict[str, Path] | None = None,
    ) -> Path:
        """Produce the final container.

        The original video stream is copied without re-encoding wherever possible, both
        because re-encoding is slow and because it would needlessly lose quality.

        Args:
            video_source: The file holding the original video stream.
            german_audio: The mixed German audio track, made the default track.
            destination: Where to write the output.
            original_audio: The original audio, kept as a secondary track.
            subtitles: Subtitle files keyed by language code.

        Returns:
            The written file.

        Raises:
            ExportError: If muxing fails.
        """
        ...
