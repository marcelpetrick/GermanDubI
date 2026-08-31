"""SQLAlchemy table definitions.

These are persistence models, not domain objects. They are deliberately separate from
:mod:`germandubi.domain`, and mapping happens in the repositories, so that a schema
convenience never leaks into the domain and a domain refactor never forces a migration.

Time is stored as integer milliseconds; timestamps are stored timezone-aware in UTC. Large
media never lives here - only relative paths, hashes, and metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "ArtifactRow",
    "Base",
    "EventRow",
    "ExportRow",
    "JobRow",
    "ProjectRow",
    "RunRow",
    "SegmentRow",
    "TranslationRevisionRow",
    "WordRow",
]


def _now() -> datetime:
    """Return the current time as a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for every table."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class ProjectRow(Base):
    """A dubbing project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_locator: Mapped[str] = mapped_column(Text)
    source_video_id: Mapped[str | None] = mapped_column(String(32))
    source_language: Mapped[str] = mapped_column(String(8), default="en")
    target_language: Mapped[str] = mapped_column(String(8), default="de")
    quality: Mapped[str] = mapped_column(String(16), default="balanced")
    voice: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="new", index=True)
    title: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    media: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    project_format_version: Mapped[int] = mapped_column(Integer, default=1)
    created_with: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    segments: Mapped[list[SegmentRow]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SegmentRow.ordinal"
    )
    artifacts: Mapped[list[ArtifactRow]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    runs: Mapped[list[RunRow]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class SegmentRow(Base):
    """One time-bounded speech segment."""

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("project_id", "ordinal", name="uq_segment_ordinal"),
        Index("ix_segments_project_start", "project_id", "start_ms"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)

    source_text: Mapped[str] = mapped_column(Text)
    source_origin: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)

    translation: Mapped[str | None] = mapped_column(Text)
    translation_origin: Mapped[str | None] = mapped_column(String(32))

    prosody: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fit: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    review_state: Mapped[str] = mapped_column(String(32), default="unreviewed")
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)

    speech_artifact_id: Mapped[str | None] = mapped_column(String(26))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[ProjectRow] = relationship(back_populates="segments")
    words: Mapped[list[WordRow]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", order_by="WordRow.start_ms"
    )
    revisions: Mapped[list[TranslationRevisionRow]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="TranslationRevisionRow.revision",
    )


class WordRow(Base):
    """One word with its timing.

    Word rows dominate table size - a twenty-minute video is roughly three thousand rows -
    but SQLite handles that easily, and word timing is what makes accurate re-segmentation
    and precise pause reconstruction possible later (questions.md Q-B4).
    """

    __tablename__ = "words"
    __table_args__ = (Index("ix_words_segment_start", "segment_id", "start_ms"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), index=True
    )
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)

    segment: Mapped[SegmentRow] = relationship(back_populates="words")


class TranslationRevisionRow(Base):
    """A previous German rendering of a segment.

    Human edits are never overwritten silently, so every translation is kept and the
    current one is a pointer (``vision.md`` section 15.2).
    """

    __tablename__ = "translation_revisions"
    __table_args__ = (UniqueConstraint("segment_id", "revision", name="uq_translation_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    segment: Mapped[SegmentRow] = relationship(back_populates="revisions")


class ArtifactRow(Base):
    """A file produced or acquired by the pipeline."""

    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_project_kind", "project_id", "kind"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[str | None] = mapped_column(String(26), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    relative_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(128))
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[ProjectRow] = relationship(back_populates="artifacts")


class RunRow(Base):
    """One attempt to take a project through the pipeline."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    stages: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[ProjectRow] = relationship(back_populates="runs")
    jobs: Mapped[list[JobRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="JobRow.created_at"
    )


class JobRow(Base):
    """One persisted unit of work."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("run_id", "stage", name="uq_job_stage_per_run"),
        Index("ix_jobs_claimable", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(String(26), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[RunRow] = relationship(back_populates="jobs")


class EventRow(Base):
    """A progress event, persisted so an SSE client can resume after a reconnect.

    The monotonic sequence number is what makes ``Last-Event-ID`` replay possible: a browser
    refresh mid-processing rejoins exactly where it left off rather than losing history
    (questions.md Q-D4).
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_project_sequence", "project_id", "sequence"),)

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(26), index=True)
    run_id: Mapped[str | None] = mapped_column(String(26))
    kind: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExportRow(Base):
    """A produced output file."""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[str | None] = mapped_column(String(26))
    container: Mapped[str] = mapped_column(String(8), default="mkv")
    include_original_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    include_subtitles: Mapped[bool] = mapped_column(Boolean, default=True)
    app_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
