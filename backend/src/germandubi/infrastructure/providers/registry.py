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
from typing import Final

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
from germandubi.domain.errors import ProviderUnavailableError
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import ProcessRunner
from germandubi.infrastructure.providers.alignment import ProportionalAlignmentProvider
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.captions import CaptionTranscriptProvider
from germandubi.infrastructure.providers.demucs import DemucsSeparationProvider
from germandubi.infrastructure.providers.fakes import (
    FakeAcquisitionProvider,
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

#: Runtimes yt-dlp can use to solve YouTube's JavaScript challenge, in no particular order.
_JS_RUNTIMES: Final = ("deno", "node")

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
        device: The compute device the model providers resolved to.
    """

    tools: dict[str, bool]
    providers: list[tuple[ProviderInfo, bool]]
    data_dir: Path
    writable: bool
    device: str = "cpu"

    @property
    def can_dub(self) -> bool:
        """Return whether a real German dub is possible with what is installed.

        FFmpeg alone is not enough. Without a translation provider and a German voice there
        is nothing to say and nothing to say it with, so this used to report "Ready to dub"
        on a machine that could only produce placeholder audio.
        """
        return not self.missing_required and not self.missing_for_a_real_dub

    @property
    def missing_required(self) -> list[str]:
        """Return the required external tools that are absent."""
        return [name for name in ("ffmpeg", "ffprobe") if not self.tools.get(name)]

    @property
    def missing_for_a_real_dub(self) -> list[str]:
        """Return the provider stacks whose absence would give placeholder output.

        Separation is deliberately excluded: without it the mix ducks the original audio
        instead of removing it, which is a worse dub but still a real one.
        """
        ready = {info.id for info, available in self.providers if available}
        needed = {
            "argos": "translation (uv sync --extra translate)",
            "piper": "German speech (uv sync --extra tts)",
        }
        return [label for provider, label in needed.items() if provider not in ready]


def _missing(what: str, extra: str) -> str:
    """Return the message shown when a required provider stack is absent.

    Naming the exact command matters: the alternative to this error was a run that
    completed, looked finished in the browser, and contained no German.
    """
    return (
        f"no {what} provider is installed, so this run would produce placeholder output "
        f"rather than a usable dub. Install it with `uv sync --extra {extra}` "
        f"(or `make install-providers`), then run `germandubi doctor` to confirm."
    )


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
        when recognition is unavailable (docs/project/questions.md Q-C1).

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

        whisper = WhisperTranscriptionProvider(
            download_root=self.settings.models_dir, device=self.settings.resolved_device()
        )
        if configured in {AUTO, "whisper", "faster_whisper"} and whisper.is_available():
            logger.info("using speech recognition for the English transcript")
            return whisper

        if captions is not None and captions.is_available():
            logger.warning(
                "falling back to the source's automatic captions; the text is unpunctuated, "
                "which usually produces noticeably worse German"
            )
            return captions
        raise ProviderUnavailableError(_missing("English transcript", "asr"), port="transcription")

    def alignment(self) -> AlignmentProvider:
        """Return the word-alignment provider.

        Recognition already emits word timestamps, so this only fills in timing for a
        caption-derived transcript that has none (docs/project/questions.md Q-C2). There is one
        implementation and it runs in production; it is not a test double.
        """
        return ProportionalAlignmentProvider()

    # --- translation --------------------------------------------------------------------

    def translation(self) -> TranslationProvider:
        """Return the English-to-German translation provider.

        Returns:
            Argos when installed. The deterministic fake only when it is asked for by name.

        Raises:
            ProviderUnavailableError: If no real provider is installed. This is deliberately
                fatal: the placeholder does not translate, and a run that used it silently
                produced a finished-looking dub of unusable text.
        """
        configured = self.settings.translation_provider
        if configured == FAKE:
            return FakeTranslationProvider()
        argos = ArgosTranslationProvider()
        if configured in {AUTO, "argos"} and argos.is_available():
            return argos
        raise ProviderUnavailableError(
            _missing("German translation", "translate"), port="translation"
        )

    # --- speech -------------------------------------------------------------------------

    def tts(self) -> TTSProvider:
        """Return the German speech provider.

        Returns:
            Piper when installed. The deterministic fake only when it is asked for by name.

        Raises:
            ProviderUnavailableError: If no real German voice is installed. The placeholder
                emits a quiet synthetic tone, not speech.
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
        raise ProviderUnavailableError(_missing("German speech", "tts"), port="tts")

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
        demucs = DemucsSeparationProvider(self.runner, device=self.settings.resolved_device())
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
        # YouTube will not release formats without a solved JavaScript challenge, and
        # yt-dlp needs a runtime to solve it. Absent one, an available video is reported as
        # unavailable -- a symptom that points nowhere near the cause, which is why this is
        # surfaced as a tool rather than left to be discovered.
        tools["javascript runtime"] = any(
            self.runner.is_installed(runtime) for runtime in _JS_RUNTIMES
        )
        # Every provider that can actually be selected, so the report is a complete
        # picture of what may run rather than a list of the optional extras.
        candidates: list[object] = [
            YtDlpProbeProvider(self.runner, executable=self.settings.yt_dlp_path),
            LocalFileProbeProvider(self.media()),
            WhisperTranscriptionProvider(
                download_root=self.settings.models_dir, device=self.settings.resolved_device()
            ),
            ArgosTranslationProvider(),
            PiperTTSProvider(voices_dir=self.settings.models_dir / "piper"),
            DemucsSeparationProvider(self.runner, device=self.settings.resolved_device()),
            TimingProsodyProvider(self.runner),
            ProportionalAlignmentProvider(),
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
            device=self.settings.resolved_device(),
        )
