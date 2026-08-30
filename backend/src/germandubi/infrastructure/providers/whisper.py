"""Speech recognition using faster-whisper.

Automatic captions from the source are unpunctuated and coarsely timed. Recognition costs
real CPU or GPU time but produces punctuated, cased text with word-level timestamps - which
is what sentence segmentation, translation quality and precise timing all depend on. This is
therefore the preferred path whenever manual captions are unavailable (questions.md Q-C1).

Word timestamps come from the same pass, so no separate forced-alignment stack is needed
(questions.md Q-C2).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Final

from germandubi.application.ports.providers import ProviderInfo, ProviderKind
from germandubi.domain.entities.segment import Word
from germandubi.domain.errors import ProviderUnavailableError, TranscriptionError
from germandubi.domain.transcript import Transcript, TranscriptCue, TranscriptSource
from germandubi.domain.value_objects.timeline import TimeInterval, seconds_to_ms

__all__ = ["WhisperTranscriptionProvider"]

logger = logging.getLogger(__name__)

#: "small" is the point where English narration transcribes reliably while staying
#: practical on a CPU. Larger models are a quality profile choice, not a default.
DEFAULT_MODEL: Final = "small"


class WhisperTranscriptionProvider:
    """Transcribes English narration with faster-whisper."""

    def __init__(
        self,
        *,
        model_size: str = DEFAULT_MODEL,
        device: str = "auto",
        compute_type: str = "auto",
        download_root: Path | None = None,
    ) -> None:
        """Initialise the provider.

        Args:
            model_size: Whisper model size, e.g. ``tiny``, ``base``, ``small``, ``medium``.
            device: ``cpu``, ``cuda`` or ``auto``.
            compute_type: Quantization, e.g. ``int8`` or ``float16``. ``auto`` lets
                faster-whisper choose what the device supports.
            download_root: Directory to cache downloaded models in.
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self._model: Any | None = None
        self._lock = threading.Lock()

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="faster_whisper",
            name=f"faster-whisper ({self.model_size})",
            kind=ProviderKind.LOCAL,
            model_id=self.model_size,
            # Beam search with a fixed seed is stable in practice but not guaranteed
            # bit-identical across hardware, so this is not claimed as deterministic.
            deterministic=False,
            requires=("faster-whisper",),
            notes="Runs locally. The model is downloaded once, then cached.",
        )

    def is_available(self) -> bool:
        """Return whether faster-whisper is importable."""
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self) -> Any:
        """Load the model, downloading it on first use.

        Raises:
            ProviderUnavailableError: If the package is missing or the model cannot load.
        """
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                msg = (
                    "faster-whisper is not installed. Install the optional ASR extra: "
                    "`uv sync --extra asr`."
                )
                raise ProviderUnavailableError(msg) from exc
            logger.info("loading the faster-whisper %s model", self.model_size)
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(self.download_root) if self.download_root else None,
                )
            except Exception as exc:
                msg = f"could not load the faster-whisper {self.model_size} model: {exc}"
                raise ProviderUnavailableError(msg, model=self.model_size) from exc
            return self._model

    def transcribe(self, audio: Path, *, language: str = "en") -> Transcript:
        """Transcribe narration into a canonical timed transcript.

        Args:
            audio: Normalized mono 16 kHz audio.
            language: The spoken language; always ``en`` in ``0.x``.

        Returns:
            The canonical transcript, with word-level timing.

        Raises:
            TranscriptionError: If recognition fails or finds no speech.
            ProviderUnavailableError: If the model is unavailable.
        """
        if not audio.exists():
            msg = f"the audio file to transcribe is missing: {audio.name}"
            raise TranscriptionError(msg, path=str(audio))

        model = self._load()
        try:
            segments, _ = model.transcribe(
                str(audio),
                language=language,
                word_timestamps=True,
                # Voice activity detection keeps the model from hallucinating text during
                # music and silence, which is the most common failure on real videos.
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                beam_size=5,
                condition_on_previous_text=False,
            )
            cues = [cue for cue in map(_to_cue, segments) if cue is not None]
        except Exception as exc:
            msg = f"speech recognition failed: {exc}"
            raise TranscriptionError(msg, path=str(audio)) from exc

        if not cues:
            msg = (
                "no speech was recognized in the source audio. The video may be music-only, "
                "or the narration may not be in English."
            )
            raise TranscriptionError(msg, path=str(audio))

        return Transcript.from_raw(
            cues,
            source=TranscriptSource.ASR,
            provider_id=self.info.id,
            model_id=self.model_size,
        )


def _to_cue(segment: Any) -> TranscriptCue | None:
    """Map one faster-whisper segment onto a transcript cue.

    Returns ``None`` for a segment with no text or no positive duration, rather than
    raising: a single bad segment must not fail a twenty-minute transcription.
    """
    text = str(getattr(segment, "text", "") or "").strip()
    start = seconds_to_ms(float(getattr(segment, "start", 0.0)))
    end = seconds_to_ms(float(getattr(segment, "end", 0.0)))
    if not text or end <= start:
        return None

    words: list[Word] = []
    for raw in getattr(segment, "words", None) or []:
        word_text = str(getattr(raw, "word", "") or "").strip()
        word_start = seconds_to_ms(float(getattr(raw, "start", 0.0)))
        word_end = seconds_to_ms(float(getattr(raw, "end", 0.0)))
        if not word_text or word_end <= word_start:
            continue
        probability = getattr(raw, "probability", None)
        words.append(
            Word(
                start_ms=word_start,
                end_ms=word_end,
                text=word_text,
                confidence=min(1.0, max(0.0, float(probability))) if probability else None,
            )
        )

    confidence = getattr(segment, "avg_logprob", None)
    return TranscriptCue(
        interval=TimeInterval(start, end),
        text=text,
        words=tuple(words),
        # avg_logprob is a log probability in roughly [-1, 0]; map it into [0, 1].
        confidence=min(1.0, max(0.0, 1.0 + float(confidence))) if confidence else None,
    )
