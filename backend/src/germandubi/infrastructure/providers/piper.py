"""German speech synthesis using Piper.

Piper is the default German voice because it is the only credible option that is
realistically faster than realtime on a CPU. That matters more than raw quality here: the
review loop depends on regenerating a corrected segment in about a second, and a model that
takes thirty seconds per segment would make the editing workflow unusable
(docs/project/questions.md Q-C5).

Voices are ONNX files downloaded once and cached. Synthesis is entirely local.
"""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path
from typing import Any, Final

from germandubi.application.ports.providers import (
    ProviderInfo,
    ProviderKind,
    SynthesisRequest,
    SynthesisResult,
)
from germandubi.domain.errors import ProviderUnavailableError, SynthesisError

__all__ = ["DEFAULT_GERMAN_VOICE", "GERMAN_VOICES", "PiperTTSProvider"]

logger = logging.getLogger(__name__)

#: Thorsten is a permissively licensed, single-speaker German corpus, which is what makes
#: it usable here without a licensing question hanging over every export. The `high` model
#: is the default because the narration is the product: it costs more synthesis time than
#: `medium` and is the best this voice offers. The ceiling is Piper's own 22.05 kHz output,
#: which no export setting can raise.
DEFAULT_GERMAN_VOICE: Final = "de_DE-thorsten-high"
GERMAN_VOICES: Final[tuple[str, ...]] = (
    "de_DE-thorsten-medium",
    "de_DE-thorsten-high",
    "de_DE-thorsten-low",
    "de_DE-eva_k-x_low",
    "de_DE-kerstin-low",
    "de_DE-ramona-low",
    "de_DE-karlsson-low",
    "de_DE-pavoque-low",
)
#: Piper expresses speed as seconds-per-phoneme: larger is slower, so a requested rate is
#: inverted before being passed through.
_MIN_LENGTH_SCALE: Final = 0.5
_MAX_LENGTH_SCALE: Final = 2.0


class PiperTTSProvider:
    """Synthesizes German speech with a locally cached Piper voice."""

    def __init__(self, *, voices_dir: Path, default_voice: str = DEFAULT_GERMAN_VOICE) -> None:
        """Initialise the provider.

        Args:
            voices_dir: Directory holding downloaded voice models.
            default_voice: The voice used when a request does not name one.
        """
        self.voices_dir = voices_dir
        self.default_voice = default_voice
        self._loaded: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="piper",
            name="Piper German TTS",
            kind=ProviderKind.LOCAL,
            model_id=self.default_voice,
            deterministic=True,
            requires=("piper-tts",),
            notes="Runs locally on the CPU. Voices are downloaded once, then cached.",
        )

    def is_available(self) -> bool:
        """Return whether the Piper package and its dependency stack are importable."""
        try:
            from piper import PiperVoice  # noqa: F401
        except Exception:
            logger.debug("Piper is installed but cannot be imported", exc_info=True)
            return False
        return True

    def available_voices(self) -> tuple[str, ...]:
        """Return the German voices this provider knows about.

        Voices already downloaded are listed first, since those need no network access.
        """
        installed = {p.stem for p in self.voices_dir.glob("*.onnx")}
        known = list(GERMAN_VOICES)
        return tuple(sorted(known, key=lambda v: (v not in installed, known.index(v))))

    def _voice(self, name: str) -> Any:
        """Load a voice, downloading it on first use.

        Args:
            name: The voice identifier.

        Returns:
            The loaded Piper voice.

        Raises:
            ProviderUnavailableError: If Piper is missing or the voice cannot be obtained.
        """
        with self._lock:
            if name in self._loaded:
                return self._loaded[name]
            try:
                from piper import PiperVoice
            except Exception as exc:
                msg = (
                    "Piper is unavailable. Install or repair the optional TTS extra: "
                    "`uv sync --extra tts`."
                )
                raise ProviderUnavailableError(msg) from exc

            model = self.voices_dir / f"{name}.onnx"
            if not model.exists():
                self._download_voice(name)
            if not model.exists():
                msg = f"the Piper voice {name!r} could not be downloaded"
                raise ProviderUnavailableError(msg, voice=name)
            try:
                voice = PiperVoice.load(str(model))
            except Exception as exc:
                msg = f"the Piper voice {name!r} could not be loaded: {exc}"
                raise ProviderUnavailableError(msg, voice=name) from exc
            self._loaded[name] = voice
            return voice

    def _download_voice(self, name: str) -> None:
        """Download a voice model into the cache directory.

        Raises:
            ProviderUnavailableError: If the download fails.
        """
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        logger.info("downloading the Piper voice %s; this happens once", name)
        try:
            from piper.download_voices import download_voice

            download_voice(name, self.voices_dir)
        except ImportError as exc:
            msg = (
                f"the Piper voice {name!r} is not present and this Piper version cannot "
                f"download it. Place {name}.onnx and {name}.onnx.json in {self.voices_dir}."
            )
            raise ProviderUnavailableError(msg, voice=name) from exc
        except Exception as exc:
            msg = f"could not download the Piper voice {name!r}: {exc}"
            raise ProviderUnavailableError(msg, voice=name) from exc

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Synthesize one German utterance.

        Args:
            request: The text, voice, destination and speaking rate.

        Returns:
            The written audio and its measured duration.

        Raises:
            SynthesisError: If the text is empty, or synthesis produces no audio.
            ProviderUnavailableError: If Piper or the voice is unavailable.
        """
        text = request.text.strip()
        if not text:
            msg = "cannot synthesize empty text"
            raise SynthesisError(msg)
        if request.speaking_rate <= 0:
            msg = f"speaking rate must be positive, got {request.speaking_rate}"
            raise SynthesisError(msg, speaking_rate=request.speaking_rate)

        voice_name = request.voice or self.default_voice
        voice = self._voice(voice_name)
        request.destination.parent.mkdir(parents=True, exist_ok=True)

        # Piper's length_scale is seconds-per-phoneme, so a faster rate is a smaller scale.
        length_scale = min(_MAX_LENGTH_SCALE, max(_MIN_LENGTH_SCALE, 1.0 / request.speaking_rate))
        try:
            self._write_wav(voice, text, request.destination, length_scale)
        except (OSError, RuntimeError, ValueError) as exc:
            msg = f"German speech synthesis failed: {exc}"
            raise SynthesisError(msg, voice=voice_name, text=text[:120]) from exc

        duration_ms, sample_rate = _measure_wav(request.destination)
        if duration_ms <= 0:
            msg = "German speech synthesis produced an empty audio file"
            raise SynthesisError(msg, voice=voice_name, text=text[:120])

        return SynthesisResult(
            audio_path=request.destination,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            provider_id=self.info.id,
            model_id=voice_name,
        )

    @staticmethod
    def _synthesis_config(length_scale: float) -> Any | None:
        """Build Piper's synthesis config, or ``None`` on a version that has no such type."""
        try:
            from piper.config import SynthesisConfig
        except ImportError:
            return None
        return SynthesisConfig(length_scale=length_scale)

    def _write_wav(self, voice: Any, text: str, destination: Path, length_scale: float) -> None:
        """Write synthesized audio, tolerating the Piper API across versions.

        Piper 1.3 takes a ``SynthesisConfig``; older builds took ``length_scale`` directly
        or nothing at all. Falling back keeps the adapter working with whichever version a
        user happens to have installed, rather than failing on a keyword argument.
        """
        config = self._synthesis_config(length_scale)
        with wave.open(str(destination), "wb") as handle:
            if hasattr(voice, "synthesize_wav"):
                for attempt in ((config,) if config is not None else (), ()):
                    try:
                        voice.synthesize_wav(text, handle, *attempt)
                    except TypeError:
                        continue
                    return
                voice.synthesize_wav(text, handle)
                return

            frames = bytearray()
            sample_rate = 22_050
            sample_width = 2
            channels = 1
            for chunk in voice.synthesize(text):
                frames += bytes(getattr(chunk, "audio_int16_bytes", chunk))
                sample_rate = int(getattr(chunk, "sample_rate", sample_rate))
                sample_width = int(getattr(chunk, "sample_width", sample_width))
                channels = int(getattr(chunk, "sample_channels", channels))
            handle.setnchannels(channels)
            handle.setsampwidth(sample_width)
            handle.setframerate(sample_rate)
            handle.writeframes(bytes(frames))


def _measure_wav(path: Path) -> tuple[int, int]:
    """Return a WAV file's duration in milliseconds and its sample rate.

    Args:
        path: The WAV file.

    Returns:
        ``(duration_ms, sample_rate)``.

    Raises:
        SynthesisError: If the file cannot be read as WAV.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
    except (OSError, wave.Error) as exc:
        msg = f"the synthesized audio could not be read back: {exc}"
        raise SynthesisError(msg, path=str(path)) from exc
    return round(frames * 1000 / rate), rate
