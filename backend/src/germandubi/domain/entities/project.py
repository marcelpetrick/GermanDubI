"""The project: an immutable source plus everything derived from it.

A project's lifecycle is an explicit state machine rather than a set of boolean flags,
because the interesting behaviour lives in the transitions - what may be retried, what may
be resumed, and what a browser refresh mid-processing must show.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Self

from germandubi.domain.errors import DomainError, InvalidStateTransitionError
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.domain.value_objects.language import (
    SOURCE_LANGUAGE,
    SUPPORTED_PAIRS,
    TARGET_LANGUAGE,
    LanguageCode,
)
from germandubi.domain.value_objects.source_url import SourceUrl

__all__ = [
    "CaptionTrack",
    "Project",
    "ProjectState",
    "QualityProfile",
    "SourceKind",
    "SourceMedia",
    "SourceRef",
]


class ProjectState(StrEnum):
    """Where a project is in its lifecycle (``docs/product/vision.md`` section 12.1)."""

    NEW = "new"
    PROBING = "probing"
    READY = "ready"
    PROCESSING = "processing"
    REVIEW = "review"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Return whether no work is currently in flight for this state."""
        return self in {
            ProjectState.READY,
            ProjectState.REVIEW,
            ProjectState.COMPLETE,
            ProjectState.FAILED,
            ProjectState.CANCELLED,
        }

    @property
    def is_busy(self) -> bool:
        """Return whether the worker is expected to be doing something."""
        return self in {ProjectState.PROBING, ProjectState.PROCESSING}


#: The only transitions the domain allows. Anything else is a bug, not a user error.
_ALLOWED_TRANSITIONS: Final[dict[ProjectState, frozenset[ProjectState]]] = {
    ProjectState.NEW: frozenset({ProjectState.PROBING, ProjectState.FAILED}),
    ProjectState.PROBING: frozenset({ProjectState.READY, ProjectState.FAILED}),
    ProjectState.READY: frozenset({ProjectState.PROCESSING, ProjectState.FAILED}),
    ProjectState.PROCESSING: frozenset(
        {ProjectState.REVIEW, ProjectState.FAILED, ProjectState.CANCELLED}
    ),
    ProjectState.REVIEW: frozenset({ProjectState.PROCESSING, ProjectState.COMPLETE}),
    ProjectState.COMPLETE: frozenset({ProjectState.PROCESSING, ProjectState.REVIEW}),
    ProjectState.FAILED: frozenset({ProjectState.PROCESSING, ProjectState.PROBING}),
    ProjectState.CANCELLED: frozenset({ProjectState.PROCESSING}),
}


class SourceKind(StrEnum):
    """Where the source media comes from."""

    YOUTUBE = "youtube"
    LOCAL_FILE = "local_file"


class QualityProfile(StrEnum):
    """The speed/quality trade-off chosen for a run (``docs/product/vision.md`` section 40)."""

    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM = "maximum"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A validated reference to the material to be dubbed.

    Attributes:
        kind: Whether the source is a URL or a local file.
        locator: The validated URL, or the absolute path of the local file.
        video_id: The YouTube video id, when the source is a single YouTube video.
    """

    kind: SourceKind
    locator: str
    video_id: str | None = None

    @classmethod
    def from_url(cls, url: SourceUrl) -> Self:
        """Build a reference from an already-validated URL.

        Args:
            url: The validated source URL.

        Returns:
            The source reference.
        """
        return cls(kind=SourceKind.YOUTUBE, locator=url.value, video_id=url.video_id)

    @classmethod
    def from_local_file(cls, path: str) -> Self:
        """Build a reference to a local media file.

        Args:
            path: An absolute path to a readable media file.

        Returns:
            The source reference.

        Raises:
            DomainError: If the path is not absolute.
        """
        if not path.startswith("/"):
            msg = f"local source path must be absolute, got {path!r}"
            raise DomainError(msg, path=path)
        return cls(kind=SourceKind.LOCAL_FILE, locator=path)


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    """A caption track advertised by the source.

    Attributes:
        language: The caption language.
        automatic: Whether the track was machine-generated. Automatic captions are
            unpunctuated and coarsely timed, so they are the last resort
            (docs/project/questions.md Q-C1).
        name: The label the source uses for the track.
        format: The caption file format, e.g. ``vtt``.
    """

    language: LanguageCode
    automatic: bool
    name: str | None = None
    format: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMedia:
    """What the cheap probe learned about the source, before downloading anything.

    Attributes:
        title: The source title.
        uploader: Channel or uploader name.
        duration_ms: Media duration.
        thumbnail_url: URL of a preview image, for the analysis screen.
        captions: Caption tracks the source advertises.
        video_codec: Video codec of the best available stream.
        audio_codec: Audio codec of the best available stream.
        width: Video width in pixels.
        height: Video height in pixels.
    """

    title: str
    duration_ms: int
    uploader: str | None = None
    thumbnail_url: str | None = None
    captions: tuple[CaptionTrack, ...] = ()
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None

    @property
    def english_captions(self) -> tuple[CaptionTrack, ...]:
        """Return the English caption tracks, manual ones first."""
        english = [c for c in self.captions if c.language is LanguageCode.ENGLISH]
        return tuple(sorted(english, key=lambda c: c.automatic))

    @property
    def best_english_caption(self) -> CaptionTrack | None:
        """Return the English caption track the pipeline should prefer, if any."""
        tracks = self.english_captions
        return tracks[0] if tracks else None


@dataclass(frozen=True, slots=True)
class Project:
    """A dubbing project: an immutable source plus everything derived from it.

    Attributes:
        id: Identity of the project.
        source: What is being dubbed.
        source_language: Always English in ``0.x``.
        target_language: Always German in ``0.x``.
        quality: The chosen speed/quality trade-off.
        voice: The German narrator, or ``None`` to use the configured default. Held per
            project rather than per machine: two dubs on one machine can want different
            narrators, and the choice belongs to the work.
        state: Lifecycle state.
        title: Display title, filled in by the probe.
        media: Probe results, once analysed.
        error: Why the project failed, when it did.
        created_at: Creation time.
        updated_at: Time of the last state change.
    """

    id: ProjectId
    source: SourceRef
    source_language: LanguageCode = SOURCE_LANGUAGE
    target_language: LanguageCode = TARGET_LANGUAGE
    quality: QualityProfile = QualityProfile.BALANCED
    voice: str | None = None
    state: ProjectState = ProjectState.NEW
    title: str | None = None
    media: SourceMedia | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate that the requested language pair is supported.

        Raises:
            DomainError: If the pair is not English to German.
        """
        pair = (self.source_language, self.target_language)
        if pair not in SUPPORTED_PAIRS:
            supported = ", ".join(f"{s}->{t}" for s, t in sorted(SUPPORTED_PAIRS))
            msg = (
                f"unsupported language pair {pair[0]}->{pair[1]}; "
                f"this version supports: {supported}"
            )
            raise DomainError(msg, source=str(pair[0]), target=str(pair[1]))

    @classmethod
    def create(
        cls,
        source: SourceRef,
        *,
        quality: QualityProfile = QualityProfile.BALANCED,
        voice: str | None = None,
    ) -> Self:
        """Create a new project in the ``NEW`` state.

        Args:
            source: The validated source reference.
            quality: The speed/quality trade-off to use.
            voice: The German narrator, or ``None`` for the configured default.

        Returns:
            The new project.
        """
        return cls(id=ProjectId(new_id()), source=source, quality=quality, voice=voice)

    @property
    def display_title(self) -> str:
        """Return the title to show in the UI, falling back to the source locator."""
        return self.title or self.source.locator

    def transition_to(self, state: ProjectState, *, error: str | None = None) -> Self:
        """Return a copy in a new lifecycle state.

        Args:
            state: The requested state.
            error: The failure reason, required when moving to ``FAILED``.

        Returns:
            The updated project.

        Raises:
            InvalidStateTransitionError: If the transition is not allowed from the current
                state.
            DomainError: If moving to ``FAILED`` without a reason.
        """
        if state is self.state:
            return self
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            allowed = ", ".join(sorted(_ALLOWED_TRANSITIONS[self.state])) or "nothing"
            msg = f"cannot move a project from {self.state} to {state}; allowed: {allowed}"
            raise InvalidStateTransitionError(msg, current=str(self.state), requested=str(state))
        if state is ProjectState.FAILED and not error:
            msg = "a failed project must record why it failed"
            raise DomainError(msg, project_id=str(self.id))
        return replace(
            self,
            state=state,
            error=error if state is ProjectState.FAILED else None,
            updated_at=datetime.now(UTC),
        )

    def with_probe_result(self, media: SourceMedia) -> Self:
        """Return a copy carrying the probe result and moved to ``READY``.

        Args:
            media: What the probe learned about the source.

        Returns:
            The updated project.
        """
        probed = replace(self, media=media, title=media.title)
        return probed.transition_to(ProjectState.READY)

    def with_quality(self, quality: QualityProfile) -> Self:
        """Return a copy using a different quality profile."""
        return replace(self, quality=quality, updated_at=datetime.now(UTC))
