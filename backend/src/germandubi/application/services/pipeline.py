"""Starting, resuming, cancelling and partially re-running the pipeline."""

from __future__ import annotations

import logging

from germandubi.application.services.unit_of_work import UnitOfWork, UnitOfWorkFactory
from germandubi.domain.entities.pipeline import (
    STAGE_ORDER,
    Job,
    JobStatus,
    PipelineRun,
    Stage,
    downstream_of,
)
from germandubi.domain.entities.project import Project, ProjectState
from germandubi.domain.errors import DomainError
from germandubi.domain.value_objects.identifiers import ProjectId, RunId

__all__ = ["PipelineService", "RunProgress"]

logger = logging.getLogger(__name__)


class RunProgress:
    """A snapshot of a run, in the shape the processing screen needs.

    Attributes:
        run: The run itself.
        jobs: Its jobs, in execution order.
    """

    def __init__(self, run: PipelineRun, jobs: list[Job]) -> None:
        """Initialise the snapshot.

        Args:
            run: The run.
            jobs: Its jobs.
        """
        self.run = run
        self.jobs = sorted(jobs, key=lambda job: STAGE_ORDER.index(job.stage))

    @property
    def finished(self) -> bool:
        """Return whether every job has reached a terminal status."""
        return all(job.status.is_finished for job in self.jobs)

    @property
    def failed(self) -> bool:
        """Return whether any job failed with no retries left."""
        return any(job.status is JobStatus.FAILED and not job.can_retry for job in self.jobs)

    @property
    def current(self) -> Job | None:
        """Return the job currently running, if any."""
        return next((job for job in self.jobs if job.status is JobStatus.RUNNING), None)

    @property
    def fraction(self) -> float:
        """Return overall completion in ``[0, 1]``.

        Counts a running job's own progress, so a long stage does not look stalled.
        """
        if not self.jobs:
            return 0.0
        done = sum(
            1.0
            if job.status is JobStatus.SUCCEEDED or job.status is JobStatus.SKIPPED
            else job.progress
            if job.status is JobStatus.RUNNING
            else 0.0
            for job in self.jobs
        )
        return round(done / len(self.jobs), 4)


class PipelineService:
    """Creates runs and answers questions about their progress."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        """Initialise the service.

        Args:
            unit_of_work: Factory producing a transaction per operation.
        """
        self.unit_of_work = unit_of_work

    def start(
        self, project_id: ProjectId, *, stages: tuple[Stage, ...] | None = None
    ) -> PipelineRun:
        """Queue a full or partial pipeline run.

        Args:
            project_id: The project to process.
            stages: The stages to run. Defaults to everything after the probe, since the
                probe has already happened by the time the user presses "Create German Dub".

        Returns:
            The queued run.

        Raises:
            DomainError: If the project is already busy or has not been analysed.
        """
        with self.unit_of_work() as uow:
            project = uow.projects.get(project_id)
            if project.state.is_busy:
                msg = f"this project is already {project.state}; wait for it to finish"
                raise DomainError(msg, state=str(project.state))
            if project.media is None:
                msg = "analyse the source before starting a dub"
                raise DomainError(msg, project_id=str(project_id))

            wanted = stages or tuple(s for s in STAGE_ORDER if s is not Stage.PROBE)
            run = self._queue(uow, project, wanted)
            uow.projects.save(project.transition_to(ProjectState.PROCESSING))
            uow.events.append(
                project.id,
                "run_started",
                {"run_id": str(run.id), "stages": [s.value for s in run.stages]},
                run_id=run.id,
            )
            logger.info("queued run %s for project %s", run.id, project.id)
            return run

    def regenerate(self, project_id: ProjectId, *, changed: Stage) -> PipelineRun:
        """Re-run one stage and everything that depends on its output.

        This is the invalidation graph put to work: correcting a translation must redo
        synthesis, fitting, assembly, mixing, subtitles, QA and export - and nothing else.
        Acquisition, transcription and separation are left alone, which is what makes a
        correction cheap.

        Args:
            project_id: The project.
            changed: The stage whose output changed.

        Returns:
            The queued run.

        Raises:
            DomainError: If the project is already busy.
        """
        affected = frozenset({changed}) | downstream_of(changed)
        return self.start(project_id, stages=tuple(s for s in STAGE_ORDER if s in affected))

    @staticmethod
    def _queue(uow: UnitOfWork, project: Project, stages: tuple[Stage, ...]) -> PipelineRun:
        """Create a run and one job per stage."""
        run = PipelineRun.create(project.id, stages=stages)
        uow.jobs.add_run(
            run,
            [Job.create(run_id=run.id, project_id=project.id, stage=stage) for stage in run.stages],
        )
        return run

    def progress(self, run_id: RunId) -> RunProgress:
        """Return a snapshot of a run.

        Args:
            run_id: The run.

        Returns:
            The snapshot.

        Raises:
            NotFoundError: If the run does not exist.
        """
        with self.unit_of_work() as uow:
            return RunProgress(uow.jobs.get_run(run_id), uow.jobs.jobs_for_run(run_id))

    def latest_progress(self, project_id: ProjectId) -> RunProgress | None:
        """Return a snapshot of a project's most recent run.

        Args:
            project_id: The project.

        Returns:
            The snapshot, or ``None`` when the project has never been processed.
        """
        with self.unit_of_work() as uow:
            run = uow.jobs.latest_run(project_id)
            if run is None:
                return None
            return RunProgress(run, uow.jobs.jobs_for_run(run.id))

    def cancel(self, run_id: RunId) -> None:
        """Request cancellation of a run.

        Cancellation is cooperative: queued jobs are cancelled immediately, and a running
        job is flagged so the worker stops at its next checkpoint and terminates any
        external process it started.

        Args:
            run_id: The run to cancel.

        Raises:
            NotFoundError: If the run does not exist.
        """
        with self.unit_of_work() as uow:
            run = uow.jobs.get_run(run_id)
            uow.jobs.cancel_run(run_id)
            project = uow.projects.get(run.project_id)
            if project.state is ProjectState.PROCESSING:
                uow.projects.save(project.transition_to(ProjectState.CANCELLED))
            uow.events.append(
                run.project_id, "run_cancelled", {"run_id": str(run_id)}, run_id=run_id
            )
        logger.info("cancellation requested for run %s", run_id)

    def resume(self, project_id: ProjectId) -> PipelineRun:
        """Re-queue the stages of the last run that did not finish successfully.

        Args:
            project_id: The project to resume.

        Returns:
            The new run covering the unfinished stages.

        Raises:
            DomainError: If there is nothing to resume.
        """
        with self.unit_of_work() as uow:
            previous = uow.jobs.latest_run(project_id)
            if previous is None:
                msg = "this project has never been processed, so there is nothing to resume"
                raise DomainError(msg, project_id=str(project_id))
            unfinished = tuple(
                job.stage
                for job in uow.jobs.jobs_for_run(previous.id)
                if job.status is not JobStatus.SUCCEEDED and job.status is not JobStatus.SKIPPED
            )
        if not unfinished:
            msg = "the last run completed successfully, so there is nothing to resume"
            raise DomainError(msg, project_id=str(project_id))
        return self.start(project_id, stages=unfinished)
