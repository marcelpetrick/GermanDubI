"""Filesystem artifact storage.

Media belongs in files, not in SQLite. The database stores relative paths, hashes and
lineage; this store owns the bytes.

Every path that comes from outside - a stored relative path, a filename derived from a
video title - is resolved and checked to remain inside the project workspace before it is
opened. That check is the reason this class exists rather than callers using
``Path`` directly.
"""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from germandubi.domain.entities.artifact import Artifact, ArtifactKind
from germandubi.domain.errors import DomainError, ResourceError
from germandubi.domain.value_objects.content_hash import ContentHash, hash_file
from germandubi.domain.value_objects.identifiers import ProjectId

__all__ = ["ArtifactStore", "sanitize_filename"]

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)
_MAX_STEM_LENGTH: Final = 80
#: Reading a media file whole would exhaust memory; range requests stream in chunks.
_STREAM_CHUNK: Final = 64 * 1024


def sanitize_filename(name: str, *, fallback: str = "file") -> str:
    """Reduce arbitrary text to a safe file name.

    Video titles routinely contain slashes, colons, emoji and right-to-left marks. This
    strips them to a conservative set, removes any directory component, and refuses names
    that would resolve to the current or parent directory.

    Args:
        name: The candidate name, typically derived from a video title.
        fallback: The name to use when nothing usable remains.

    Returns:
        A safe bare filename.

    Example:
        >>> sanitize_filename("../../etc/passwd")
        'etcpasswd'
        >>> sanitize_filename("Why C++ is 🔥 / hot")
        'Why C is  hot'
    """
    normalised = unicodedata.normalize("NFKD", name).replace("/", "").replace("\\", "")
    cleaned = _UNSAFE.sub("", normalised).strip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)[:_MAX_STEM_LENGTH].strip()
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


class ArtifactStore:
    """Reads and writes project artifacts under a fixed root.

    Attributes:
        root: The directory holding one workspace per project.
    """

    #: Sub-directories created for every project workspace.
    LAYOUT: Final = (
        "source",
        "captions",
        "audio",
        "transcript",
        "stems",
        "speech",
        "mixes",
        "subtitles",
        "exports",
        "logs",
    )

    def __init__(self, root: Path) -> None:
        """Initialise the store.

        Args:
            root: Directory that will contain one sub-directory per project.
        """
        self.root = root.expanduser().resolve()

    # --- workspaces ---------------------------------------------------------------------

    def workspace(self, project_id: ProjectId) -> Path:
        """Return the workspace directory for a project.

        Args:
            project_id: The project.

        Returns:
            The absolute workspace path.
        """
        return self.root / str(project_id)

    def create_workspace(self, project_id: ProjectId) -> Path:
        """Create a project workspace with its standard sub-directories.

        Args:
            project_id: The project.

        Returns:
            The workspace path.

        Raises:
            ResourceError: If the directories cannot be created.
        """
        workspace = self.workspace(project_id)
        try:
            for directory in self.LAYOUT:
                (workspace / directory).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"could not create the project workspace: {exc}"
            raise ResourceError(msg, project_id=str(project_id)) from exc
        return workspace

    def delete_workspace(self, project_id: ProjectId) -> None:
        """Remove a project's workspace and everything in it.

        Args:
            project_id: The project.
        """
        workspace = self.workspace(project_id)
        # Guard against a caller having somehow produced a path outside the root.
        if not self._is_inside_root(workspace):
            msg = f"refusing to delete a path outside the artifact root: {workspace}"
            raise DomainError(msg)
        shutil.rmtree(workspace, ignore_errors=True)

    # --- paths --------------------------------------------------------------------------

    def resolve(self, project_id: ProjectId, relative_path: str) -> Path:
        """Resolve a stored relative path to an absolute one inside the workspace.

        Args:
            project_id: The owning project.
            relative_path: The path as stored in the database.

        Returns:
            The absolute path.

        Raises:
            DomainError: If the path escapes the project workspace. This is the check that
                makes serving artifacts over HTTP safe.
        """
        workspace = self.workspace(project_id)
        candidate = (workspace / relative_path).resolve()
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError as exc:
            msg = f"artifact path escapes the project workspace: {relative_path!r}"
            raise DomainError(msg, relative_path=relative_path) from exc
        return candidate

    def path_for(self, artifact: Artifact) -> Path:
        """Return the absolute path of an artifact.

        Args:
            artifact: The artifact record.

        Returns:
            Its absolute path inside the workspace.
        """
        return self.resolve(artifact.project_id, artifact.relative_path)

    def allocate(
        self,
        project_id: ProjectId,
        kind: ArtifactKind,
        filename: str,
        *,
        segment_id: str | None = None,
        media_type: str | None = None,
    ) -> tuple[Artifact, Path]:
        """Reserve a location for a new artifact.

        Args:
            project_id: The owning project.
            kind: What the artifact is; determines the sub-directory.
            filename: The desired bare file name; sanitized before use.
            segment_id: The owning segment, for per-segment artifacts.
            media_type: IANA media type.

        Returns:
            The artifact record and the absolute path to write to. The parent directory
            exists on return.
        """
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        safe = f"{sanitize_filename(stem, fallback=kind.value)}{suffix}"
        artifact = Artifact.create(
            project_id=project_id,
            kind=kind,
            filename=safe,
            segment_id=segment_id,
            media_type=media_type,
        )
        path = self.resolve(project_id, artifact.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return artifact, path

    # --- content ------------------------------------------------------------------------

    def record(self, artifact: Artifact) -> Artifact:
        """Measure a written file and fill in its hash and size.

        Args:
            artifact: The artifact whose file has been written.

        Returns:
            The artifact with ``content_hash`` and ``size_bytes`` populated.

        Raises:
            ResourceError: If the file is missing or empty.
        """
        path = self.path_for(artifact)
        if not path.exists():
            msg = f"the artifact file was not written: {artifact.relative_path}"
            raise ResourceError(msg, relative_path=artifact.relative_path)
        size = path.stat().st_size
        if size == 0:
            msg = f"the artifact file is empty: {artifact.relative_path}"
            raise ResourceError(msg, relative_path=artifact.relative_path)
        return artifact.recorded(content_hash=hash_file(path), size_bytes=size)

    def write_text(self, artifact: Artifact, content: str) -> Artifact:
        """Write text content and record the artifact.

        Args:
            artifact: The allocated artifact.
            content: UTF-8 text to write.

        Returns:
            The recorded artifact.
        """
        path = self.path_for(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.record(artifact)

    def read_text(self, artifact: Artifact) -> str:
        """Read an artifact's text content.

        Args:
            artifact: The artifact to read.

        Returns:
            The decoded content.

        Raises:
            ResourceError: If the file is missing.
        """
        path = self.path_for(artifact)
        if not path.exists():
            msg = f"artifact file is missing: {artifact.relative_path}"
            raise ResourceError(msg, relative_path=artifact.relative_path)
        return path.read_text(encoding="utf-8")

    def read_text_at(self, path: Path) -> str:
        """Read a workspace file that a caller already resolved.

        Args:
            path: The absolute path, obtained from this store.

        Returns:
            The decoded content.

        Raises:
            ResourceError: If the file is missing.
        """
        if not path.exists():
            msg = f"file is missing from the project workspace: {path.name}"
            raise ResourceError(msg, path=str(path))
        return path.read_text(encoding="utf-8")

    def stream(self, path: Path, *, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """Yield a byte range of a file in chunks.

        Media files are far too large to read into Python memory, so the preview endpoints
        stream. This also implements the byte-range support the browser needs for seeking.

        Args:
            path: The absolute file path, already resolved inside a workspace.
            start: First byte to send, inclusive.
            end: Last byte to send, inclusive. ``None`` means to the end of the file.

        Yields:
            Chunks of file content.
        """
        remaining = (end - start + 1) if end is not None else None
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining is None or remaining > 0:
                size = _STREAM_CHUNK if remaining is None else min(_STREAM_CHUNK, remaining)
                chunk = handle.read(size)
                if not chunk:
                    return
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk

    def verify(self, artifact: Artifact) -> bool:
        """Return whether an artifact's file still matches its recorded hash.

        Args:
            artifact: The artifact to check.

        Returns:
            Whether the file exists and its content hash is unchanged.
        """
        if artifact.content_hash is None:
            return False
        path = self.path_for(artifact)
        if not path.exists():
            return False
        return hash_file(path) == artifact.content_hash

    def content_hash(self, path: Path) -> ContentHash:
        """Return the hash of a file's contents.

        Args:
            path: The file to hash.

        Returns:
            The prefixed hash.
        """
        return hash_file(path)

    def _is_inside_root(self, path: Path) -> bool:
        """Return whether ``path`` resolves to somewhere under the artifact root."""
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True
