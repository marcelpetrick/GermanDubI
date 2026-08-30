"""Source inspection for a file that is already on this machine.

A local file needs no downloader: everything the probe stage reports -- duration, codecs,
dimensions -- is already in the container, and ``ffprobe`` reads it without touching the
network. Acquisition has always understood local files; inspection needs to as well, or a
local source fails before it can start.

A local file advertises no caption tracks. Sidecar subtitle files are a separate feature
and are deliberately not guessed at here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from germandubi.application.ports.providers import ProviderInfo, ProviderKind
from germandubi.domain.entities.project import SourceKind, SourceMedia, SourceRef
from germandubi.domain.errors import MediaProcessingError, SourceAcquisitionError
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit

__all__ = ["LocalFileProbeProvider"]

logger = logging.getLogger(__name__)


class LocalFileProbeProvider:
    """Inspects a local media file with ``ffprobe``."""

    def __init__(self, media: FFmpegToolkit) -> None:
        """Initialise the provider.

        Args:
            media: The shared FFmpeg toolkit.
        """
        self.media = media

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="local_file_probe",
            name="Local file probe",
            kind=ProviderKind.LOCAL,
            requires=("ffprobe",),
            notes="Reads the file's own metadata. Nothing leaves this machine.",
        )

    def is_available(self) -> bool:
        """Return whether ``ffprobe`` is installed."""
        return self.media.is_available()

    def probe(self, source: SourceRef) -> SourceMedia:
        """Inspect a local media file.

        Args:
            source: The validated source reference.

        Returns:
            Title, duration and stream details read from the file itself.

        Raises:
            SourceAcquisitionError: If the source is not a local file, is missing, or
                cannot be read as media.
        """
        if source.kind is not SourceKind.LOCAL_FILE:
            msg = f"this provider cannot inspect a {source.kind} source"
            raise SourceAcquisitionError(msg, kind=str(source.kind))

        path = Path(source.locator)
        if not path.exists():
            msg = f"the file no longer exists: {path.name}"
            raise SourceAcquisitionError(msg, path=str(path))

        try:
            info = self.media.probe(path)
        except MediaProcessingError as exc:
            msg = f"could not read {path.name}: {exc.message}"
            raise SourceAcquisitionError(msg, path=str(path)) from exc

        logger.info("probed local file %s: %.1fs", path.name, info.duration_ms / 1000)
        return SourceMedia(
            # The file name is the only title a local file has.
            title=path.stem,
            duration_ms=info.duration_ms,
            video_codec=info.video_codec,
            audio_codec=info.audio_codec,
            width=info.width,
            height=info.height,
        )
