"""Provider selection.

The registry is the composition root for providers. It decides which implementation backs
each port, given what is installed and what the user configured. Everything else in the
application asks for a port and never learns which implementation it received.

Selection is conservative in two ways. It never picks a ``NETWORK`` provider unless the
user has explicitly allowed one, and it always falls back to something that works rather
than failing a run because an optional dependency is absent - a missing separation model
means ducking instead of stems, not a failed export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from germandubi.application.ports.providers import (
    AcquisitionProvider,
    AlignmentProvider,
    ProbeProvider,
    ProsodyProvider,
    ProviderInfo,
    SeparationProvider,
    TranscriptionProvider,
    TranslationProvider,
    TTSProvider,
)
from germandubi.config import Settings
from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import ProcessRunner
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.captions import CaptionTranscriptProvider
from germandubi.infrastructure.providers.demucs import DemucsSeparationProvider
from germandubi.infrastructure.providers.fakes import (
    FakeAcquisitionProvider,
    FakeAlignmentProvider,
    FakeProbeProvider,
    FakeProsodyProvider,
    FakeSeparationProvider,
    FakeTranscriptionProvider,
    FakeTranslationProvider,
    FakeTTSProvider,
)
from germandubi.infrastructure.providers.localfile import LocalFileProbeProvider
from germandubi.infrastructure.providers.piper import PiperTTSProvider
from germandubi.infrastructure.providers.prosody import TimingProsodyProvider
from germandubi.infrastructure.providers.whisper import WhisperTranscriptionProvider
from germandubi.infrastructure.providers.ytdlp import YtDlpAcquisitionProvider, YtDlpProbeProvider

__all__ = ["DependencyReport", "ProviderRegistry"]

logger = logging.getLogger(__name__)

#: Selects the deterministic fakes for every port. Used by tests and the E2E suite.
FAKE = "fake"
#: Picks the best real provider that is actually installed.
AUTO = "auto"


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """What ``germandubi doctor`` found.

    Attributes:
        tools: External programs and whether each was found.
        providers: Provider identity and whether it can run.
        data_dir: Where project data will be stored.
        writable: Whether the data directory can be written to.
    """

    tools: dict[str, bool]
    providers: list[tuple[ProviderInfo, bool]]
    data_dir: Path
    writable: bool

    @property
    def can_dub(self) -> bool:
        """Return whether a full German dub is possible with what is installed.

        FFmpeg is genuinely required; everything else has a working fallback.
        """
        return self.tools.get("ffmpeg", False) and self.tools.get("ffprobe", False)

    @property
    def missing_required(self) -> list[str]:
        """Return the required tools that are absent."""
        return [name for name in ("ffmpeg", "ffprobe") if not self.tools.get(name)]


class ProviderRegistry:
    """Builds provider instances according to settings and what is installed."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: ProcessRunner | None = None,
        fixture: Path | None = None,
    ) -> None:
        """Initialise the registry.

        Args:
            settings: Application settings, which name the preferred providers.
            runner: The process runner to share across subprocess-backed providers.
            fixture: A local media file used by the fake acquisition provider in tests.
        """
        self.settings = settings
        self.runner = runner or ProcessRunner(default_timeout_s=settings.process_timeout_s)
        self.fixture = fixture
        self._media: FFmpegToolkit | None = None

    # --- media --------------------------------------------------------------------------

    def media(self) -> FFmpegToolkit:
        """Return the shared FFmpeg toolkit."""
        if self._media is None:
            self._media = FFmpegToolkit(
                self.runner,
                ffmpeg=self.settings.ffmpeg_path,
                ffprobe=self.settings.ffprobe_path,
            )
        return self._media

    # --- source -------------------------------------------------------------------------

    def probe(self, source: SourceRef) -> ProbeProvider:
        """Return the probe provider that can inspect this source.

        Selection depends on the source itself: a downloader cannot inspect a file that is
        already on disk, and ``ffprobe`` cannot inspect a URL. Dispatching here keeps that
        knowledge in the registry, which is where provider selection belongs.

        Args:
            source: The source about to be inspected.

        Returns:
            The provider for this source kind, or the fake when the real one is
            unavailable or has been selected explicitly.
        """
        if self.settings.transcription_provider == FAKE:
            return FakeProbeProvider()
        if source.kind is SourceKind.LOCAL_FILE:
            local = LocalFileProbeProvider(self.media())
            return local if local.is_available() else FakeProbeProvider()
        real = YtDlpProbeProvider(self.runner, executable=self.settings.yt_dlp_path)
        return real if real.is_available() else FakeProbeProvider()

    def acquisition(self) -> AcquisitionProvider:
        """Return the acquisition provider.

        Returns:
            The real ``yt-dlp`` downloader, or a fixture-copying fake in tests.
        """
        if self.fixture is not None:
            return FakeAcquisitionProvider(self.fixture)
        return YtDlpAcquisitionProvider(self.runner, executable=self.settings.yt_dlp_path)

    # --- transcript ---------------------------------------------------------------------

    def transcription(
        self, *, caption_path: Path | None = None, caption_is_automatic: bool = False
    ) -> TranscriptionProvider:
        """Return the transcript provider for this project.

        Manual captions win outright: they are punctuated and cased, which is what
        segmentation and translation quality depend on. Speech recognition is preferred
        over *automatic* captions, which are unpunctuated. Automatic captions are used only
        when recognition is unavailable (questions.md Q-C1).

        Args:
            caption_path: A downloaded caption file, when one exists.
            caption_is_automatic: Whether that file was machine-generated by the source.

        Returns:
            The selected transcript provider.
        """
        configured = self.settings.transcription_provider
        if configured == FAKE:
            return FakeTranscriptionProvider()

        captions = (
            CaptionTranscriptProvider(caption_path, automatic=caption_is_automatic)
            if caption_path is not None
            else None
        )
        if captions is not None and not caption_is_automatic and captions.is_available():
            logger.info("using the source's manual captions as the English transcript")
            return captions

        whisper = WhisperTranscriptionProvider(download_root=self.settings.models_dir)
        if configured in {AUTO, "whisper", "faster_whisper"} and whisper.is_available():
            logger.info("using speech recognition for the English transcript")
            return whisper

        if captions is not None and captions.is_available():
            logger.warning(
                "falling back to the source's automatic captions; the text is unpunctuated, "
                "which usually produces noticeably worse German"
            )
            return captions
        return FakeTranscriptionProvider()

    def alignment(self) -> AlignmentProvider:
        """Return the word-alignment provider.

        Recognition already emits word timestamps, so this only fills in timing for a
        caption-derived transcript that has none (questions.md Q-C2).
        """
        return FakeAlignmentProvider()

    # --- translation --------------------------------------------------------------------

    def translation(self) -> TranslationProvider:
        """Return the English-to-German translation provider.

        Returns:
            Argos when installed, otherwise the deterministic fake so the pipeline still
            completes and the failure is visible in the output rather than fatal.
        """
        configured = self.settings.translation_provider
        if configured == FAKE:
            return FakeTranslationProvider()
        argos = ArgosTranslationProvider()
        if configured in {AUTO, "argos"} and argos.is_available():
            return argos
        logger.warning(
            "no real translation provider is installed; using the placeholder provider. "
            "Install it with `uv sync --extra translate`."
        )
        return FakeTranslationProvider()

    # --- speech -------------------------------------------------------------------------

    def tts(self) -> TTSProvider:
        """Return the German speech provider.

        Returns:
            Piper when installed, otherwise the deterministic fake.
        """
        configured = self.settings.tts_provider
        if configured == FAKE:
            return FakeTTSProvider()
        piper = PiperTTSProvider(
            voices_dir=self.settings.models_dir / "piper",
            default_voice=self.settings.tts_voice,
        )
        if configured in {AUTO, "piper"} and piper.is_available():
            return piper
        logger.warning(
            "no real German voice is installed; using the placeholder provider. "
            "Install it with `uv sync --extra tts`."
        )
        return FakeTTSProvider()

    def prosody(self) -> ProsodyProvider:
        """Return the narrator delivery analysis provider."""
        if self.settings.transcription_provider == FAKE:
            return FakeProsodyProvider()
        return TimingProsodyProvider(self.runner, ffmpeg=self.settings.ffmpeg_path)

    # --- separation ---------------------------------------------------------------------

    def separation(self) -> SeparationProvider | None:
        """Return the voice/background separation provider, if one is usable.

        Returns:
            The provider, or ``None`` when separation is unavailable. ``None`` is a normal
            outcome, not an error: the mix stage then ducks the original audio instead,
            which needs only FFmpeg.
        """
        configured = self.settings.separation_provider
        if configured == FAKE:
            return FakeSeparationProvider()
        if configured == "none":
            return None
        demucs = DemucsSeparationProvider(self.runner)
        if configured in {AUTO, "demucs"} and demucs.is_available():
            return demucs
        logger.info(
            "no separation model is installed; the original audio will be ducked under the "
            "German narration instead. Install it with `uv sync --extra separation`."
        )
        return None

    # --- diagnostics --------------------------------------------------------------------

    def report(self) -> DependencyReport:
        """Inspect the environment for ``germandubi doctor``.

        Returns:
            What is installed, what is missing, and whether a dub is possible at all.
        """
        tools = {
            name: self.runner.is_installed(name)
            for name in (
                self.settings.ffmpeg_path,
                self.settings.ffprobe_path,
                self.settings.yt_dlp_path,
            )
        }
        candidates: list[object] = [
            YtDlpProbeProvider(self.runner, executable=self.settings.yt_dlp_path),
            WhisperTranscriptionProvider(download_root=self.settings.models_dir),
            ArgosTranslationProvider(),
            PiperTTSProvider(voices_dir=self.settings.models_dir / "piper"),
            DemucsSeparationProvider(self.runner),
            TimingProsodyProvider(self.runner),
        ]
        providers = [
            (provider.info, provider.is_available())  # type: ignore[attr-defined]
            for provider in candidates
        ]

        writable = True
        try:
            self.settings.ensure_directories()
            probe_file = self.settings.data_dir / ".write-check"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink()
        except OSError:
            writable = False

        return DependencyReport(
            tools=tools,
            providers=providers,
            data_dir=self.settings.data_dir,
            writable=writable,
        )
