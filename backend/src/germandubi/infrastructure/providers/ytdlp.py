"""Source inspection and acquisition backed by ``yt-dlp``.

``yt-dlp`` is invoked through the process runner as an argument array. The UI never supplies
downloader arguments, and the URL has already passed the domain's allowlist validation
before it reaches this module.

This adapter does not implement, and must not be extended to implement, any form of
access-control or DRM circumvention.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

from germandubi.application.ports.providers import (
    AcquisitionRequest,
    AcquisitionResult,
    ProviderInfo,
    ProviderKind,
)
from germandubi.domain.entities.project import CaptionTrack, SourceKind, SourceMedia, SourceRef
from germandubi.domain.errors import SourceAcquisitionError
from germandubi.domain.value_objects.language import LanguageCode
from germandubi.domain.value_objects.timeline import seconds_to_ms
from germandubi.infrastructure.processes.runner import (
    MAX_STRUCTURED_OUTPUT_BYTES,
    ProcessError,
    ProcessRunner,
)

__all__ = ["YtDlpAcquisitionProvider", "YtDlpProbeProvider"]

logger = logging.getLogger(__name__)

#: A probe must stay cheap: it is run interactively while the user waits.
_PROBE_TIMEOUT_S: Final = 90
#: Prefer a container the browser can play directly, falling back to whatever exists.
_FORMAT_SELECTOR: Final = (
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "best[height<=1080][ext=mp4]/"
    "bestvideo[height<=1080]+bestaudio/best"
)


class YtDlpProbeProvider:
    """Inspects a source with ``yt-dlp --dump-single-json``, downloading nothing."""

    def __init__(self, runner: ProcessRunner, *, executable: str = "yt-dlp") -> None:
        """Initialise the provider.

        Args:
            runner: The process runner to use.
            executable: Name or path of the ``yt-dlp`` executable.
        """
        self.runner = runner
        self.executable = executable

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="yt_dlp_probe",
            name="yt-dlp source probe",
            kind=ProviderKind.NETWORK,
            requires=("yt-dlp",),
            notes="Contacts the source site to read metadata. No media is downloaded.",
        )

    def is_available(self) -> bool:
        """Return whether ``yt-dlp`` is installed."""
        return self.runner.is_installed(self.executable)

    def probe(self, source: SourceRef) -> SourceMedia:
        """Inspect the source without downloading it.

        Args:
            source: The validated source reference.

        Returns:
            Title, duration, caption tracks and stream formats.

        Raises:
            SourceAcquisitionError: If the source cannot be inspected, for example because
                it is private, removed, age-restricted or region-blocked.
        """
        if source.kind is not SourceKind.YOUTUBE:
            msg = f"this provider cannot inspect a {source.kind} source"
            raise SourceAcquisitionError(msg, kind=str(source.kind))

        try:
            result = self.runner.run(
                [
                    self.executable,
                    "--dump-single-json",
                    "--no-playlist",
                    "--no-warnings",
                    "--skip-download",
                    source.locator,
                ],
                timeout_s=_PROBE_TIMEOUT_S,
                max_output_bytes=MAX_STRUCTURED_OUTPUT_BYTES,
            )
        except ProcessError as exc:
            msg = f"could not read the source: {_explain(exc.message)}"
            raise SourceAcquisitionError(msg, url=source.locator) from exc

        if result.stdout_truncated:
            msg = (
                "the source returned more metadata than this version can hold; "
                "please report this, as it is a limit in GermanDubI, not in the source"
            )
            raise SourceAcquisitionError(msg, url=source.locator)
        try:
            payload: dict[str, Any] = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            msg = "the source site returned metadata this version cannot read"
            raise SourceAcquisitionError(msg, url=source.locator) from exc
        return _to_source_media(payload)


def _explain(message: str) -> str:
    """Turn a ``yt-dlp`` failure into something a user can act on."""
    lowered = message.lower()
    known = (
        ("private video", "the video is private"),
        ("video unavailable", "the video is unavailable"),
        ("removed", "the video has been removed"),
        ("age-restricted", "the video is age-restricted and cannot be processed"),
        ("confirm your age", "the video is age-restricted and cannot be processed"),
        ("sign in", "the source requires signing in, which this version does not do"),
        ("not available in your country", "the video is blocked in this region"),
        # Ambiguous on purpose. A removed video says this, and so does a working one when
        # no JavaScript runtime is available to solve YouTube's challenge -- the same words
        # for a fault in the source and a fault in this installation, so the message names
        # both and points at the command that tells them apart.
        (
            "this video is not available",
            (
                "the video is unavailable. If it plays in a browser, this machine may be "
                "missing the JavaScript runtime YouTube requires; run `germandubi doctor`"
            ),
        ),
        ("unable to download webpage", "the source site could not be reached"),
    )
    for needle, explanation in known:
        if needle in lowered:
            return explanation
    return message.splitlines()[-1] if message else "the source could not be read"


def _to_source_media(payload: dict[str, Any]) -> SourceMedia:
    """Map a ``yt-dlp`` info dictionary onto the application's own type.

    Provider output is mapped immediately rather than persisted as-is, so a change in
    ``yt-dlp``'s schema cannot ripple into the domain.
    """
    duration = payload.get("duration")
    if not duration:
        msg = "the source reports no duration; it may be a live stream or a playlist"
        raise SourceAcquisitionError(msg, title=str(payload.get("title", "")))

    captions: list[CaptionTrack] = []
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        for language, tracks in (payload.get(key) or {}).items():
            base = language.split("-", 1)[0].lower()
            if base != LanguageCode.ENGLISH.value:
                continue
            best = next((t for t in tracks if t.get("ext") == "vtt"), tracks[0] if tracks else None)
            captions.append(
                CaptionTrack(
                    language=LanguageCode.ENGLISH,
                    automatic=automatic,
                    name=(best or {}).get("name") or language,
                    format=(best or {}).get("ext"),
                )
            )

    return SourceMedia(
        title=str(payload.get("title") or "Untitled"),
        duration_ms=seconds_to_ms(float(duration)),
        uploader=payload.get("uploader") or payload.get("channel"),
        thumbnail_url=payload.get("thumbnail"),
        captions=tuple(captions),
        video_codec=_clean_codec(payload.get("vcodec")),
        audio_codec=_clean_codec(payload.get("acodec")),
        width=payload.get("width"),
        height=payload.get("height"),
    )


def _clean_codec(value: Any) -> str | None:
    """Normalize a codec field, treating yt-dlp's "none" sentinel as absent."""
    if not value or value == "none":
        return None
    return str(value).split(".", 1)[0]


class YtDlpAcquisitionProvider:
    """Downloads source media and English captions into the project workspace."""

    def __init__(self, runner: ProcessRunner, *, executable: str = "yt-dlp") -> None:
        """Initialise the provider.

        Args:
            runner: The process runner to use.
            executable: Name or path of the ``yt-dlp`` executable.
        """
        self.runner = runner
        self.executable = executable

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="yt_dlp",
            name="yt-dlp acquisition",
            kind=ProviderKind.NETWORK,
            requires=("yt-dlp", "ffmpeg"),
            notes="Downloads the source media. You are responsible for holding the rights "
            "to process and redistribute it.",
        )

    def is_available(self) -> bool:
        """Return whether ``yt-dlp`` is installed."""
        return self.runner.is_installed(self.executable)

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        """Download the source media and any English captions.

        The output template is fixed rather than derived from the video title, so no
        filename ever comes from remote data.

        Args:
            request: What to fetch and where to put it.

        Returns:
            Paths to the downloaded media and caption files.

        Raises:
            SourceAcquisitionError: If the download fails or produces no media file.
        """
        if request.source.kind is SourceKind.LOCAL_FILE:
            return self._copy_local_file(request)

        request.destination.mkdir(parents=True, exist_ok=True)
        argv = [
            self.executable,
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--format",
            _FORMAT_SELECTOR,
            "--merge-output-format",
            "mkv",
            # A fixed template: never let a remote title decide a path on this machine.
            "--output",
            str(request.destination / "source.%(ext)s"),
        ]
        if request.want_captions:
            argv += [
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "en.*",
                "--sub-format",
                "vtt",
                "--convert-subs",
                "vtt",
            ]
        argv.append(request.source.locator)

        try:
            self.runner.run(argv)
        except ProcessError as exc:
            msg = f"could not download the source: {_explain(exc.message)}"
            raise SourceAcquisitionError(msg, url=request.source.locator) from exc

        return AcquisitionResult(
            video_path=self._find_media(request.destination),
            caption_paths=self._find_captions(request.destination),
        )

    @staticmethod
    def _copy_local_file(request: AcquisitionRequest) -> AcquisitionResult:
        """Copy a local media file into the workspace, leaving the original untouched."""
        source = Path(request.source.locator)
        if not source.exists():
            msg = f"the local source file does not exist: {source.name}"
            raise SourceAcquisitionError(msg, path=str(source))
        request.destination.mkdir(parents=True, exist_ok=True)
        target = request.destination / f"source{source.suffix or '.mp4'}"
        target.write_bytes(source.read_bytes())
        return AcquisitionResult(video_path=target)

    @staticmethod
    def _find_media(destination: Path) -> Path:
        """Return the downloaded media file.

        Raises:
            SourceAcquisitionError: If nothing playable was written.
        """
        candidates = sorted(
            (
                path
                for path in destination.glob("source.*")
                if path.suffix.lower() not in {".vtt", ".srt", ".json", ".part"}
            ),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not candidates:
            msg = "the download reported success but no media file was written"
            raise SourceAcquisitionError(msg, destination=str(destination))
        return candidates[0]

    @staticmethod
    def _find_captions(destination: Path) -> dict[bool, Path]:
        """Return caption files keyed by whether they are automatically generated.

        ``yt-dlp`` marks automatic captions with an ``orig`` or ``auto`` marker in the
        filename; manual tracks are plain ``source.en.vtt``.
        """
        found: dict[bool, Path] = {}
        for path in sorted(destination.glob("source.*.vtt")):
            automatic = any(marker in path.name for marker in ("-orig", ".auto", "-auto"))
            found.setdefault(automatic, path)
        return found
