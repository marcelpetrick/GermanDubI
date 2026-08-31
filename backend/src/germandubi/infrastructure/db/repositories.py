"""Repositories: the mapping between persistence rows and domain objects.

Keeping the mapping in one place is what lets the domain stay free of SQLAlchemy and lets
the schema change without a domain refactor. Nothing outside this module constructs a
domain entity from a row, or a row from an entity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session, selectinload

from germandubi.domain.entities.artifact import Artifact, ArtifactKind, Provenance
from germandubi.domain.entities.pipeline import (
    STAGE_DEPENDENCIES,
    Job,
    JobStatus,
    PipelineRun,
    Stage,
)
from germandubi.domain.entities.project import (
    CaptionTrack,
    Project,
    ProjectState,
    QualityProfile,
    SourceKind,
    SourceMedia,
    SourceRef,
)
from germandubi.domain.entities.segment import (
    DurationFit,
    ProsodyProfile,
    ReviewState,
    SegmentStatus,
    SpeechSegment,
    TextOrigin,
    Word,
)
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import (
    ArtifactId,
    JobId,
    ProjectId,
    RunId,
    SegmentId,
    Ulid,
)
from germandubi.domain.value_objects.language import LanguageCode
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.db.models import (
    ArtifactRow,
    EventRow,
    JobRow,
    ProjectRow,
    RunRow,
    SegmentRow,
    TranslationRevisionRow,
    WordRow,
)

__all__ = [
    "ArtifactRepository",
    "EventRepository",
    "JobRepository",
    "ProjectRepository",
    "SegmentRepository",
]


# --- projects ---------------------------------------------------------------------------


class ProjectRepository:
    """Reads and writes projects."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def add(self, project: Project, *, created_with: str | None = None) -> Project:
        """Insert a new project.

        Args:
            project: The project to persist.
            created_with: The application version that created it, recorded for
                traceability of the on-disk project format.

        Returns:
            The persisted project.
        """
        self.session.add(_project_to_row(project, created_with=created_with))
        return project

    def get(self, project_id: ProjectId) -> Project:
        """Return a project by identity.

        Args:
            project_id: The project to load.

        Returns:
            The project.

        Raises:
            NotFoundError: If no such project exists.
        """
        row = self.session.get(ProjectRow, str(project_id))
        if row is None:
            msg = f"no project with id {project_id}"
            raise NotFoundError(msg, project_id=str(project_id))
        return _row_to_project(row)

    def find(self, project_id: ProjectId) -> Project | None:
        """Return a project, or ``None`` when it does not exist.

        Args:
            project_id: The project to load.

        Returns:
            The project or ``None``.
        """
        row = self.session.get(ProjectRow, str(project_id))
        return _row_to_project(row) if row else None

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Project]:
        """Return projects, newest first.

        Args:
            limit: Maximum number to return.
            offset: How many to skip.

        Returns:
            The projects.
        """
        rows = self.session.scalars(
            select(ProjectRow).order_by(ProjectRow.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return [_row_to_project(row) for row in rows]

    def count(self) -> int:
        """Return the total number of projects."""
        return len(self.session.scalars(select(ProjectRow.id)).all())

    def save(self, project: Project) -> Project:
        """Update an existing project.

        Args:
            project: The project to write.

        Returns:
            The saved project.

        Raises:
            NotFoundError: If the project does not exist.
        """
        row = self.session.get(ProjectRow, str(project.id))
        if row is None:
            msg = f"no project with id {project.id}"
            raise NotFoundError(msg, project_id=str(project.id))
        _apply_project(row, project)
        return project

    def delete(self, project_id: ProjectId) -> None:
        """Delete a project and, by cascade, everything belonging to it.

        Args:
            project_id: The project to delete.

        Raises:
            NotFoundError: If the project does not exist.
        """
        row = self.session.get(ProjectRow, str(project_id))
        if row is None:
            msg = f"no project with id {project_id}"
            raise NotFoundError(msg, project_id=str(project_id))
        self.session.delete(row)


def _project_to_row(project: Project, *, created_with: str | None = None) -> ProjectRow:
    """Build a new row from a project."""
    row = ProjectRow(id=str(project.id), created_with=created_with)
    _apply_project(row, project)
    return row


def _apply_project(row: ProjectRow, project: Project) -> None:
    """Copy a project's current values onto its row."""
    row.source_kind = project.source.kind.value
    row.source_locator = project.source.locator
    row.source_video_id = project.source.video_id
    row.source_language = project.source_language.value
    row.target_language = project.target_language.value
    row.quality = project.quality.value
    row.voice = project.voice
    row.state = project.state.value
    row.title = project.title
    row.error = project.error
    row.media = _media_to_json(project.media)
    row.created_at = project.created_at
    row.updated_at = project.updated_at


def _media_to_json(media: SourceMedia | None) -> dict[str, Any] | None:
    """Serialize probe results for storage."""
    if media is None:
        return None
    return {
        "title": media.title,
        "duration_ms": media.duration_ms,
        "uploader": media.uploader,
        "thumbnail_url": media.thumbnail_url,
        "video_codec": media.video_codec,
        "audio_codec": media.audio_codec,
        "width": media.width,
        "height": media.height,
        "captions": [
            {
                "language": c.language.value,
                "automatic": c.automatic,
                "name": c.name,
                "format": c.format,
            }
            for c in media.captions
        ],
    }


def _json_to_media(payload: dict[str, Any] | None) -> SourceMedia | None:
    """Rebuild probe results from storage."""
    if not payload:
        return None
    return SourceMedia(
        title=payload["title"],
        duration_ms=payload["duration_ms"],
        uploader=payload.get("uploader"),
        thumbnail_url=payload.get("thumbnail_url"),
        video_codec=payload.get("video_codec"),
        audio_codec=payload.get("audio_codec"),
        width=payload.get("width"),
        height=payload.get("height"),
        captions=tuple(
            CaptionTrack(
                language=LanguageCode(c["language"]),
                automatic=c["automatic"],
                name=c.get("name"),
                format=c.get("format"),
            )
            for c in payload.get("captions", [])
        ),
    )


def _row_to_project(row: ProjectRow) -> Project:
    """Rebuild a project from its row."""
    return Project(
        id=ProjectId(Ulid(row.id)),
        source=SourceRef(
            kind=SourceKind(row.source_kind),
            locator=row.source_locator,
            video_id=row.source_video_id,
        ),
        source_language=LanguageCode(row.source_language),
        target_language=LanguageCode(row.target_language),
        quality=QualityProfile(row.quality),
        voice=row.voice,
        state=ProjectState(row.state),
        title=row.title,
        media=_json_to_media(row.media),
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- segments ---------------------------------------------------------------------------


class SegmentRepository:
    """Reads and writes speech segments, their words and their translation history."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def replace_all(self, project_id: ProjectId, segments: list[SpeechSegment]) -> None:
        """Replace a project's segments wholesale.

        Used when re-segmentation produces a new set. Existing rows are removed first,
        because segment ordinals are unique per project and would otherwise collide.

        Args:
            project_id: The owning project.
            segments: The new segments, in timeline order.
        """
        existing = self.session.scalars(
            select(SegmentRow).where(SegmentRow.project_id == str(project_id))
        ).all()
        for row in existing:
            self.session.delete(row)
        self.session.flush()
        for segment in segments:
            self.session.add(_segment_to_row(segment))

    def list_for_project(self, project_id: ProjectId) -> list[SpeechSegment]:
        """Return a project's segments in timeline order.

        Args:
            project_id: The owning project.

        Returns:
            The segments.
        """
        rows = self.session.scalars(
            select(SegmentRow)
            .where(SegmentRow.project_id == str(project_id))
            .options(selectinload(SegmentRow.words))
            .order_by(SegmentRow.ordinal)
        ).all()
        return [_row_to_segment(row) for row in rows]

    def get(self, segment_id: SegmentId) -> SpeechSegment:
        """Return one segment.

        Args:
            segment_id: The segment to load.

        Returns:
            The segment.

        Raises:
            NotFoundError: If no such segment exists.
        """
        row = self.session.get(SegmentRow, str(segment_id))
        if row is None:
            msg = f"no segment with id {segment_id}"
            raise NotFoundError(msg, segment_id=str(segment_id))
        return _row_to_segment(row)

    def save(self, segment: SpeechSegment) -> SpeechSegment:
        """Update one segment, leaving its word timing untouched.

        Args:
            segment: The segment to write.

        Returns:
            The saved segment.

        Raises:
            NotFoundError: If the segment does not exist.
        """
        row = self.session.get(SegmentRow, str(segment.id))
        if row is None:
            msg = f"no segment with id {segment.id}"
            raise NotFoundError(msg, segment_id=str(segment.id))
        _apply_segment(row, segment)
        row.updated_at = datetime.now(UTC)
        return segment

    def save_many(self, segments: list[SpeechSegment]) -> None:
        """Update several segments.

        Args:
            segments: The segments to write.
        """
        for segment in segments:
            self.save(segment)

    def set_speech_artifact(self, segment_id: SegmentId, artifact_id: ArtifactId | None) -> None:
        """Point a segment at its current German speech artifact.

        Args:
            segment_id: The segment.
            artifact_id: The artifact, or ``None`` to clear the pointer.
        """
        self.session.execute(
            update(SegmentRow)
            .where(SegmentRow.id == str(segment_id))
            .values(speech_artifact_id=str(artifact_id) if artifact_id else None)
        )

    def speech_artifact_id(self, segment_id: SegmentId) -> ArtifactId | None:
        """Return the segment's current speech artifact identity, if any.

        Args:
            segment_id: The segment.

        Returns:
            The artifact id, or ``None``.
        """
        value = self.session.scalar(
            select(SegmentRow.speech_artifact_id).where(SegmentRow.id == str(segment_id))
        )
        return ArtifactId(Ulid(value)) if value else None

    def add_translation_revision(
        self,
        segment_id: SegmentId,
        *,
        text: str,
        origin: TextOrigin,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> int:
        """Append a translation revision.

        Human edits must never be lost, so every German rendering is kept and the current
        one is a pointer on the segment.

        Args:
            segment_id: The segment.
            text: The German text.
            origin: Where it came from.
            provider_id: The provider that produced it.
            model_id: The model used.

        Returns:
            The new revision number, starting at one.
        """
        existing = self.session.scalars(
            select(TranslationRevisionRow.revision).where(
                TranslationRevisionRow.segment_id == str(segment_id)
            )
        ).all()
        revision = (max(existing) if existing else 0) + 1
        self.session.add(
            TranslationRevisionRow(
                segment_id=str(segment_id),
                revision=revision,
                text=text,
                origin=origin.value,
                provider_id=provider_id,
                model_id=model_id,
            )
        )
        return revision

    def translation_revisions(self, segment_id: SegmentId) -> list[tuple[int, str, str]]:
        """Return a segment's translation history.

        Args:
            segment_id: The segment.

        Returns:
            ``(revision, text, origin)`` tuples, oldest first.
        """
        rows = self.session.scalars(
            select(TranslationRevisionRow)
            .where(TranslationRevisionRow.segment_id == str(segment_id))
            .order_by(TranslationRevisionRow.revision)
        ).all()
        return [(row.revision, row.text, row.origin) for row in rows]


def _segment_to_row(segment: SpeechSegment) -> SegmentRow:
    """Build a row, including word timing, from a segment."""
    row = SegmentRow(id=str(segment.id), project_id=str(segment.project_id))
    _apply_segment(row, segment)
    row.words = [
        WordRow(
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            text=word.text,
            confidence=word.confidence,
        )
        for word in segment.words
    ]
    return row


def _apply_segment(row: SegmentRow, segment: SpeechSegment) -> None:
    """Copy a segment's current values onto its row."""
    row.ordinal = segment.ordinal
    row.start_ms = segment.interval.start_ms
    row.end_ms = segment.interval.end_ms
    row.source_text = segment.source_text
    row.source_origin = segment.source_origin.value
    row.confidence = segment.confidence
    row.translation = segment.translation
    row.translation_origin = (
        segment.translation_origin.value if segment.translation_origin else None
    )
    row.prosody = (
        {
            "speech_rate_wps": segment.prosody.speech_rate_wps,
            "pause_before_ms": segment.prosody.pause_before_ms,
            "pause_after_ms": segment.prosody.pause_after_ms,
            "energy_rms": segment.prosody.energy_rms,
        }
        if segment.prosody
        else None
    )
    row.fit = (
        {
            "target_ms": segment.fit.target_ms,
            "generated_ms": segment.fit.generated_ms,
            "applied_rate": segment.fit.applied_rate,
        }
        if segment.fit
        else None
    )
    row.status = segment.status.value
    row.review_state = segment.review_state.value
    row.flags = sorted(segment.flags)


def _row_to_segment(row: SegmentRow) -> SpeechSegment:
    """Rebuild a segment from its row."""
    return SpeechSegment(
        id=SegmentId(Ulid(row.id)),
        project_id=ProjectId(Ulid(row.project_id)),
        ordinal=row.ordinal,
        interval=TimeInterval(row.start_ms, row.end_ms),
        source_text=row.source_text,
        source_origin=TextOrigin(row.source_origin),
        translation=row.translation,
        translation_origin=TextOrigin(row.translation_origin) if row.translation_origin else None,
        words=tuple(
            Word(w.start_ms, w.end_ms, w.text, confidence=w.confidence)
            for w in sorted(row.words, key=lambda w: w.start_ms)
        ),
        prosody=ProsodyProfile(**row.prosody) if row.prosody else None,
        fit=DurationFit(**row.fit) if row.fit else None,
        status=SegmentStatus(row.status),
        review_state=ReviewState(row.review_state),
        flags=frozenset(row.flags or ()),
        confidence=row.confidence,
    )


# --- artifacts --------------------------------------------------------------------------


class ArtifactRepository:
    """Reads and writes artifact records."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def add(self, artifact: Artifact) -> Artifact:
        """Insert an artifact record.

        Args:
            artifact: The artifact to persist.

        Returns:
            The persisted artifact.
        """
        self.session.add(
            ArtifactRow(
                id=str(artifact.id),
                project_id=str(artifact.project_id),
                segment_id=artifact.segment_id,
                kind=artifact.kind.value,
                relative_path=artifact.relative_path,
                content_hash=artifact.content_hash,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                superseded=artifact.superseded,
                provenance=_provenance_to_json(artifact.provenance),
            )
        )
        return artifact

    def get(self, artifact_id: ArtifactId) -> Artifact:
        """Return one artifact.

        Args:
            artifact_id: The artifact to load.

        Returns:
            The artifact.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(ArtifactRow, str(artifact_id))
        if row is None:
            msg = f"no artifact with id {artifact_id}"
            raise NotFoundError(msg, artifact_id=str(artifact_id))
        return _row_to_artifact(row)

    def latest(
        self,
        project_id: ProjectId,
        kind: ArtifactKind,
        *,
        segment_id: str | None = None,
    ) -> Artifact | None:
        """Return the most recent non-superseded artifact of a kind.

        Args:
            project_id: The owning project.
            kind: The artifact kind.
            segment_id: Restrict to one segment, for per-segment artifacts.

        Returns:
            The artifact, or ``None`` when the stage has not produced one yet.
        """
        query = (
            select(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.kind == kind.value,
                ArtifactRow.superseded.is_(False),
            )
            .order_by(ArtifactRow.created_at.desc(), ArtifactRow.id.desc())
        )
        if segment_id is not None:
            query = query.where(ArtifactRow.segment_id == segment_id)
        row = self.session.scalars(query.limit(1)).first()
        return _row_to_artifact(row) if row else None

    def list_for_project(self, project_id: ProjectId) -> list[Artifact]:
        """Return every current artifact of a project.

        Args:
            project_id: The owning project.

        Returns:
            The artifacts, newest first.
        """
        rows = self.session.scalars(
            select(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.superseded.is_(False),
            )
            .order_by(ArtifactRow.created_at.desc())
        ).all()
        return [_row_to_artifact(row) for row in rows]

    def supersede(
        self, project_id: ProjectId, kind: ArtifactKind, *, segment_id: str | None = None
    ) -> None:
        """Mark existing artifacts of a kind as superseded.

        The files stay on disk: processing here is non-destructive, so a previous result
        remains available for comparison and rollback.

        Args:
            project_id: The owning project.
            kind: The artifact kind to supersede.
            segment_id: Restrict to one segment.
        """
        statement = (
            update(ArtifactRow)
            .where(
                ArtifactRow.project_id == str(project_id),
                ArtifactRow.kind == kind.value,
                ArtifactRow.superseded.is_(False),
            )
            .values(superseded=True)
        )
        if segment_id is not None:
            statement = statement.where(ArtifactRow.segment_id == segment_id)
        self.session.execute(statement)


def _provenance_to_json(provenance: Provenance | None) -> dict[str, Any] | None:
    """Serialize provenance for storage."""
    if provenance is None:
        return None
    return {
        "app_version": provenance.app_version,
        "provider_id": provenance.provider_id,
        "model_id": provenance.model_id,
        "input_hash": provenance.input_hash,
        "parameters": provenance.parameters,
        "created_at": provenance.created_at.isoformat(),
    }


def _row_to_artifact(row: ArtifactRow) -> Artifact:
    """Rebuild an artifact from its row."""
    provenance = None
    if row.provenance:
        payload = dict(row.provenance)
        provenance = Provenance(
            app_version=payload["app_version"],
            provider_id=payload["provider_id"],
            input_hash=payload["input_hash"],
            model_id=payload.get("model_id"),
            parameters=payload.get("parameters", {}),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )
    return Artifact(
        id=ArtifactId(Ulid(row.id)),
        project_id=ProjectId(Ulid(row.project_id)),
        kind=ArtifactKind(row.kind),
        relative_path=row.relative_path,
        content_hash=row.content_hash,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        provenance=provenance,
        segment_id=row.segment_id,
        superseded=row.superseded,
    )


# --- jobs and runs ----------------------------------------------------------------------


class JobRepository:
    """Reads and writes runs and jobs, including the worker's claim operation."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def add_run(self, run: PipelineRun, jobs: list[Job]) -> PipelineRun:
        """Insert a run together with its jobs.

        Args:
            run: The run to persist.
            jobs: Its jobs.

        Returns:
            The persisted run.
        """
        self.session.add(
            RunRow(
                id=str(run.id),
                project_id=str(run.project_id),
                stages=[s.value for s in run.stages],
                cancelled=run.cancelled,
                created_at=run.created_at,
            )
        )
        for job in jobs:
            self.session.add(_job_to_row(job))
        return run

    def get_run(self, run_id: RunId) -> PipelineRun:
        """Return one run.

        Args:
            run_id: The run to load.

        Returns:
            The run.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(RunRow, str(run_id))
        if row is None:
            msg = f"no run with id {run_id}"
            raise NotFoundError(msg, run_id=str(run_id))
        return _row_to_run(row)

    def latest_run(self, project_id: ProjectId) -> PipelineRun | None:
        """Return a project's most recent run.

        Args:
            project_id: The owning project.

        Returns:
            The run, or ``None`` when the project has never been processed.
        """
        row = self.session.scalars(
            select(RunRow)
            .where(RunRow.project_id == str(project_id))
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
            .limit(1)
        ).first()
        return _row_to_run(row) if row else None

    def save_run(self, run: PipelineRun) -> None:
        """Update a run.

        Args:
            run: The run to write.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(RunRow, str(run.id))
        if row is None:
            msg = f"no run with id {run.id}"
            raise NotFoundError(msg, run_id=str(run.id))
        row.cancelled = run.cancelled
        row.finished_at = run.finished_at

    def jobs_for_run(self, run_id: RunId) -> list[Job]:
        """Return a run's jobs in creation order.

        Args:
            run_id: The run.

        Returns:
            The jobs.
        """
        rows = self.session.scalars(
            select(JobRow).where(JobRow.run_id == str(run_id)).order_by(JobRow.created_at)
        ).all()
        return [_row_to_job(row) for row in rows]

    def get_job(self, job_id: JobId) -> Job:
        """Return one job.

        Args:
            job_id: The job to load.

        Returns:
            The job.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(JobRow, str(job_id))
        if row is None:
            msg = f"no job with id {job_id}"
            raise NotFoundError(msg, job_id=str(job_id))
        return _row_to_job(row)

    def save_job(self, job: Job) -> Job:
        """Update a job.

        Args:
            job: The job to write.

        Returns:
            The saved job.

        Raises:
            NotFoundError: If it does not exist.
        """
        row = self.session.get(JobRow, str(job.id))
        if row is None:
            msg = f"no job with id {job.id}"
            raise NotFoundError(msg, job_id=str(job.id))
        _apply_job(row, job)
        return job

    def claim_next(self, *, lease_seconds: int, now: datetime | None = None) -> Job | None:
        """Atomically claim the next runnable job.

        A job is runnable when it is claimable, its run has not been cancelled, and every
        stage it depends on has already succeeded in the same run. Jobs whose lease has
        expired - left behind by a worker that died mid-stage - are reclaimed rather than
        stranded in ``RUNNING`` forever.

        The claim is a single ``UPDATE ... WHERE status = 'queued'`` guarded by the
        transaction, so two workers cannot claim the same job.

        Args:
            lease_seconds: How long the claim is held before it may be reclaimed.
            now: The current time; injectable for tests.

        Returns:
            The claimed job, or ``None`` when there is nothing to do.
        """
        moment = now or datetime.now(UTC)
        self._reclaim_expired_leases(moment)

        # Source inspection first, then oldest first. A probe costs a second or two and is
        # what someone who just pasted a URL is waiting on; strict age order put it behind
        # every remaining stage of a dub already running, so the interface did nothing for
        # minutes and looked hung. A run in progress loses nothing by yielding at a stage
        # boundary.
        probe_last = case((JobRow.stage == Stage.PROBE.value, 0), else_=1)
        candidates = self.session.scalars(
            select(JobRow)
            .join(RunRow, RunRow.id == JobRow.run_id)
            .where(
                JobRow.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
                RunRow.cancelled.is_(False),
            )
            .order_by(probe_last, JobRow.created_at, JobRow.id)
        ).all()

        for row in candidates:
            if not self._dependencies_satisfied(row):
                continue
            claimed = _row_to_job(row)
            if claimed.status is JobStatus.PENDING:
                claimed = claimed.transition_to(JobStatus.QUEUED)
            claimed = claimed.claimed(lease_expires_at=moment + timedelta(seconds=lease_seconds))
            _apply_job(row, claimed)
            self.session.flush()
            return claimed
        return None

    def _reclaim_expired_leases(self, now: datetime) -> None:
        """Return jobs whose lease expired to the queue so they can be retried."""
        stale = self.session.scalars(
            select(JobRow).where(
                JobRow.status == JobStatus.RUNNING.value,
                JobRow.lease_expires_at.is_not(None),
                JobRow.lease_expires_at < now,
            )
        ).all()
        for row in stale:
            row.status = JobStatus.QUEUED.value
            row.lease_expires_at = None
            row.error = "the worker holding this job stopped responding; it will be retried"

    def _dependencies_satisfied(self, row: JobRow) -> bool:
        """Return whether every stage this job depends on has succeeded in the same run."""
        needs = STAGE_DEPENDENCIES[Stage(row.stage)]
        if not needs:
            return True
        siblings = {
            sibling.stage: sibling.status
            for sibling in self.session.scalars(
                select(JobRow).where(JobRow.run_id == row.run_id)
            ).all()
        }
        for dependency in needs:
            status = siblings.get(dependency.value)
            # A dependency absent from this run was satisfied by an earlier run; a partial
            # regeneration deliberately re-runs only some stages.
            if status is not None and status not in {
                JobStatus.SUCCEEDED.value,
                JobStatus.SKIPPED.value,
            }:
                return False
        return True

    def pending_count(self, run_id: RunId) -> int:
        """Return how many of a run's jobs have not finished.

        Args:
            run_id: The run.

        Returns:
            The number of unfinished jobs.
        """
        rows = self.session.scalars(select(JobRow.status).where(JobRow.run_id == str(run_id))).all()
        return sum(1 for status in rows if not JobStatus(status).is_finished)

    def cancel_run(self, run_id: RunId) -> None:
        """Request cancellation of a run and of everything it has not started.

        Jobs already running are asked to stop cooperatively; the worker notices at its
        next checkpoint and terminates any external process it started.

        Args:
            run_id: The run to cancel.
        """
        self.session.execute(update(RunRow).where(RunRow.id == str(run_id)).values(cancelled=True))
        self.session.execute(
            update(JobRow)
            .where(
                JobRow.run_id == str(run_id),
                JobRow.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
            )
            .values(status=JobStatus.CANCELLED.value, finished_at=datetime.now(UTC))
        )
        self.session.execute(
            update(JobRow)
            .where(JobRow.run_id == str(run_id), JobRow.status == JobStatus.RUNNING.value)
            .values(status=JobStatus.CANCEL_REQUESTED.value)
        )

    def is_cancelled(self, run_id: RunId) -> bool:
        """Return whether cancellation has been requested for a run.

        Args:
            run_id: The run.

        Returns:
            Whether the run is cancelled.
        """
        return bool(self.session.scalar(select(RunRow.cancelled).where(RunRow.id == str(run_id))))


def _job_to_row(job: Job) -> JobRow:
    """Build a row from a job."""
    row = JobRow(
        id=str(job.id),
        run_id=str(job.run_id),
        project_id=str(job.project_id),
        stage=job.stage.value,
        created_at=job.created_at,
    )
    _apply_job(row, job)
    return row


def _apply_job(row: JobRow, job: Job) -> None:
    """Copy a job's current values onto its row."""
    row.status = job.status.value
    row.attempt = job.attempt
    row.input_hash = job.input_hash
    row.error = job.error
    row.lease_expires_at = job.lease_expires_at
    row.progress = job.progress
    row.progress_detail = job.progress_detail
    row.started_at = job.started_at
    row.finished_at = job.finished_at


def _row_to_job(row: JobRow) -> Job:
    """Rebuild a job from its row."""
    return Job(
        id=JobId(Ulid(row.id)),
        run_id=RunId(Ulid(row.run_id)),
        project_id=ProjectId(Ulid(row.project_id)),
        stage=Stage(row.stage),
        status=JobStatus(row.status),
        attempt=row.attempt,
        input_hash=row.input_hash,
        error=row.error,
        lease_expires_at=row.lease_expires_at,
        progress=row.progress,
        progress_detail=row.progress_detail,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _row_to_run(row: RunRow) -> PipelineRun:
    """Rebuild a run from its row."""
    return PipelineRun(
        id=RunId(Ulid(row.id)),
        project_id=ProjectId(Ulid(row.project_id)),
        stages=tuple(Stage(s) for s in row.stages),
        created_at=row.created_at,
        finished_at=row.finished_at,
        cancelled=row.cancelled,
    )


# --- events -----------------------------------------------------------------------------


class EventRepository:
    """Appends and replays progress events."""

    def __init__(self, session: Session) -> None:
        """Initialise with an open session.

        Args:
            session: The session to operate in.
        """
        self.session = session

    def append(
        self,
        project_id: ProjectId,
        kind: str,
        payload: dict[str, Any],
        *,
        run_id: RunId | None = None,
    ) -> int:
        """Append an event and return its sequence number.

        Args:
            project_id: The project the event concerns.
            kind: The event type, e.g. ``stage_started``.
            payload: Event data, serialized as JSON.
            run_id: The run the event belongs to, when applicable.

        Returns:
            The assigned monotonic sequence number.
        """
        row = EventRow(
            project_id=str(project_id),
            run_id=str(run_id) if run_id else None,
            kind=kind,
            payload=payload,
        )
        self.session.add(row)
        self.session.flush()
        return row.sequence

    def since(
        self, project_id: ProjectId, after: int = 0, *, limit: int = 500
    ) -> list[tuple[int, str, dict[str, Any]]]:
        """Return events after a sequence number.

        This is what makes SSE reconnection lossless: the browser sends the last event id
        it saw and receives exactly what it missed.

        Args:
            project_id: The project.
            after: Return events with a sequence number strictly greater than this.
            limit: Maximum number of events to return.

        Returns:
            ``(sequence, kind, payload)`` tuples, oldest first.
        """
        rows = self.session.scalars(
            select(EventRow)
            .where(EventRow.project_id == str(project_id), EventRow.sequence > after)
            .order_by(EventRow.sequence)
            .limit(limit)
        ).all()
        return [(row.sequence, row.kind, dict(row.payload)) for row in rows]

    def latest_sequence(self, project_id: ProjectId) -> int:
        """Return the highest sequence number recorded for a project.

        Args:
            project_id: The project.

        Returns:
            The highest sequence number, or ``0`` when there are no events.
        """
        value = self.session.scalar(
            select(EventRow.sequence)
            .where(EventRow.project_id == str(project_id))
            .order_by(EventRow.sequence.desc())
            .limit(1)
        )
        return int(value) if value else 0
