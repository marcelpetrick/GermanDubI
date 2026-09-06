"""The job and run repository, including the worker's claim operation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from germandubi.domain.entities.pipeline import (
    STAGE_DEPENDENCIES,
    Job,
    JobStatus,
    PipelineRun,
    Stage,
)
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import (
    JobId,
    ProjectId,
    RunId,
    Ulid,
)
from germandubi.infrastructure.db.models import (
    JobRow,
    RunRow,
)

__all__ = ["JobRepository"]


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

        for row in self._runnable_in_claim_order(ready_at=moment):
            claimed = _row_to_job(row)
            if claimed.status is JobStatus.PENDING:
                claimed = claimed.transition_to(JobStatus.QUEUED)
            claimed = claimed.claimed(lease_expires_at=moment + timedelta(seconds=lease_seconds))
            _apply_job(row, claimed)
            self.session.flush()
            return claimed
        return None

    def _runnable_in_claim_order(self, *, ready_at: datetime | None = None) -> Iterator[JobRow]:
        """Return every job with runnable work, in the order the worker will take them.

        Source inspection first, then oldest first. A probe costs a second or two and is
        what someone who just pasted a URL is waiting on; strict age order put it behind
        every remaining stage of a dub already running, so the interface did nothing for
        minutes and looked hung. A run in progress loses nothing by yielding at a stage
        boundary.

        Shared with :meth:`waiting_projects` on purpose. A queue position derived from a
        second, similar query would be a position in a queue that does not exist -- it has
        to be the same order the worker actually follows, or the interface would confidently
        show the wrong wait.

        Lazy, because claiming stops at the first runnable job and each candidate costs a
        query to check its dependencies.

        Args:
            ready_at: When given, jobs still inside their retry backoff are skipped. The
                claim path passes it; the queue-position path does not, because a job
                waiting out a backoff is still a project waiting its turn and dropping it
                from the queue would make the interface show nothing for those seconds.

        Yields:
            Runnable jobs, first to be claimed first.
        """
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
            # Both sides are UTC-aware: `UtcDateTime` guarantees it for the stored one.
            due = row.next_attempt_at
            if ready_at is not None and due is not None and due > ready_at:
                continue
            if self._dependencies_satisfied(row):
                yield row

    def waiting_projects(self) -> list[ProjectId]:
        """Return the projects with runnable work, in the order the worker will reach them.

        One entry per project, because a project's fifteen remaining stages are one wait
        from the reader's point of view, not fifteen. A project whose stage is already
        running does not appear: it is not waiting.

        Returns:
            The project ids, first to be worked on first.
        """
        ordered: list[ProjectId] = []
        for row in self._runnable_in_claim_order():
            project_id = ProjectId(Ulid(row.project_id))
            if project_id not in ordered:
                ordered.append(project_id)
        return ordered

    def renew_lease(self, job_id: JobId, *, lease_seconds: int) -> None:
        """Push a running job's lease out, so long work is not reclaimed underneath it.

        A stage that outlives its lease looks abandoned, and an abandoned job is requeued.
        Renewing as the stage makes progress keeps the lease a statement about liveness
        rather than about how long the work was expected to take.
        """
        expires = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        self.session.execute(
            update(JobRow)
            .where(JobRow.id == str(job_id), JobRow.status == JobStatus.RUNNING.value)
            .values(lease_expires_at=expires)
        )

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

    def cancel_all(self) -> None:
        """Mark every run cancelled.

        Used when clearing all work: a stage still running would otherwise recreate the
        workspace directory it is writing into, moments after it was deleted.
        """
        self.session.execute(update(RunRow).values(cancelled=True))

    def is_cancelled(self, run_id: RunId) -> bool:
        """Return whether a run should stop.

        A run that no longer exists counts as cancelled. Deleting a project cascades its runs
        and jobs away while the worker may be minutes into a stage, and the only sensible
        answer to "should this keep going" is no. Reading it as "not cancelled" let the stage
        run to completion and then try to write an artifact for a project that was gone,
        which SQLite refuses with a foreign-key violation.

        This is also what makes a delete stop the work promptly: the cancellation probe is
        wired into the process runner, so the FFmpeg or Demucs process actually running is
        terminated rather than left to finish.

        Args:
            run_id: The run.

        Returns:
            Whether the run is cancelled or gone.
        """
        cancelled = self.session.execute(
            select(RunRow.cancelled).where(RunRow.id == str(run_id))
        ).one_or_none()
        return cancelled is None or bool(cancelled[0])


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
    row.next_attempt_at = job.next_attempt_at
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
        next_attempt_at=row.next_attempt_at,
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
