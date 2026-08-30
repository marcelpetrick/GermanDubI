"""Voice and background separation using Demucs.

Separation is what turns "the German dub plays over the English narration" into "the German
dub replaces it". It is also the largest optional dependency in the project, so it is never
required: without it the mix falls back to ducking the original audio, which needs only
FFmpeg (questions.md Q-A3, Q-C3).

Demucs is invoked as a subprocess rather than imported, because its torch requirement
routinely conflicts with other ML stacks in the same environment.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Final

from germandubi.application.ports.providers import ProviderInfo, ProviderKind, SeparationResult
from germandubi.domain.errors import SeparationError
from germandubi.infrastructure.processes.runner import ProcessError, ProcessRunner

__all__ = ["DemucsSeparationProvider"]

logger = logging.getLogger(__name__)

#: The hybrid transformer model, which separates speech from music better than the older
#: variants on narration-plus-background material.
DEFAULT_MODEL: Final = "htdemucs"
#: Separation is by far the slowest stage; give it room before declaring failure.
_TIMEOUT_S: Final = 7200


class DemucsSeparationProvider:
    """Splits master audio into a background stem and a voice stem."""

    def __init__(
        self,
        runner: ProcessRunner,
        *,
        model: str = DEFAULT_MODEL,
        device: str = "cpu",
    ) -> None:
        """Initialise the provider.

        Args:
            runner: The process runner to use.
            model: The Demucs model name.
            device: ``cpu`` or ``cuda``.
        """
        self.runner = runner
        self.model = model
        self.device = device

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="demucs",
            name=f"Demucs source separation ({self.model})",
            kind=ProviderKind.LOCAL,
            model_id=self.model,
            deterministic=False,
            requires=("demucs",),
            notes="Runs locally. Slow on a CPU; a GPU is strongly preferred.",
        )

    def is_available(self) -> bool:
        """Return whether Demucs is importable."""
        try:
            import demucs.separate  # noqa: F401
        except ImportError:
            return False
        return True

    def separate(self, audio: Path, destination: Path) -> SeparationResult:
        """Split the audio into a background stem and a voice stem.

        Demucs produces four stems; the three non-vocal ones are recombined into a single
        background bed, which is what the mix stage actually needs.

        Args:
            audio: The master audio file.
            destination: Directory to write the stems into.

        Returns:
            Paths to the produced stems.

        Raises:
            SeparationError: If separation fails or produces no stems.
        """
        if not audio.exists():
            msg = f"the audio file to separate is missing: {audio.name}"
            raise SeparationError(msg, path=str(audio))
        destination.mkdir(parents=True, exist_ok=True)
        work = destination / "_demucs"

        try:
            self.runner.run(
                [
                    "python",
                    "-m",
                    "demucs.separate",
                    "--name",
                    self.model,
                    "--device",
                    self.device,
                    # Two stems: vocals and everything else. Exactly what the mix needs,
                    # and faster than producing four and recombining them ourselves.
                    "--two-stems",
                    "vocals",
                    "--out",
                    str(work),
                    str(audio),
                ],
                timeout_s=_TIMEOUT_S,
            )
        except ProcessError as exc:
            msg = f"voice and background separation failed: {exc.message}"
            raise SeparationError(msg, path=str(audio)) from exc

        background = self._collect(work, "no_vocals", destination / "background.wav")
        voice = self._collect(work, "vocals", destination / "voice.wav")
        shutil.rmtree(work, ignore_errors=True)

        if background is None:
            msg = "separation reported success but produced no background stem"
            raise SeparationError(msg, path=str(audio))

        return SeparationResult(
            background_path=background,
            voice_path=voice,
            provider_id=self.info.id,
            model_id=self.model,
        )

    @staticmethod
    def _collect(work: Path, stem: str, target: Path) -> Path | None:
        """Move a named stem out of Demucs' nested output directory."""
        matches = sorted(work.rglob(f"{stem}.*"))
        if not matches:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(matches[0], target)
        return target
