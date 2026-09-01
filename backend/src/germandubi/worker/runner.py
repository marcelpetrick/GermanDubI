"""The worker loop.

The worker claims one job at a time, runs its stage in a transaction, records the result,
and moves on. Everything about it is built around the assumption that it can be killed at
any moment: work is claimed under a lease, results are committed atomically, and a stage
whose inputs are unchanged reuses the previous artifact instead of redoing the work.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import FrameType
from typing import Final

from germandubi.application.services.unit_of_work import UnitOfWork, UnitOfWorkFactory
from germandubi.config import Settings
from germandubi.domain.entities.pipeline import Job, JobStatus
from germandubi.domain.entities.project import ProjectState
from germandubi.domain.errors import CancelledError, GermanDubIError
from germandubi.infrastructure.providers.registry import ProviderRegistry
from germandubi.worker.context import StageContext
from germandubi.worker.handlers import HANDLERS

__all__ = ["Worker"]

logger = logging.getLogger(__name__)

#: How often the cancellation probe may hit the database while a subprocess runs. Frequent
#: enough that a stop feels immediate, rare enough that polling costs nothing.
_CANCELLATION_POLL_S: Final = 0.5


def _NEVER_CANCELLED() -> bool:  # noqa: N802 - used as a sentinel callable
    """The process runner's resting state: nothing to cancel."""
    return False


@dataclass
class Worker:
    """Claims and executes pipeline jobs.

    Attributes:
        unit_of_work: Factory producing a transaction per job.
        registry: Provider selection.
        settings: Application settings.
        stopping: Set when a shutdown signal arrives; the loop finishes its current job and
            exits rather than being killed mid-write.
    """

    unit_of_work: UnitOfWorkFactory
    registry: ProviderRegistry
    settings: Settings
    stopping: bool = field(default=False, init=False)

    # --- lifecycle ----------------------------------------------------------------------

    def install_signal_handlers(self) -> None:
        """Ask the process to shut down cleanly on SIGINT and SIGTERM.

        Without this, Ctrl-C during a long FFmpeg run would leave a job stranded in
        ``RUNNING`` until its lease expired.
        """

        def stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("received signal %s; finishing the current job then stopping", signum)
            self.stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

    def run_forever(self) -> None:
        """Claim and execute jobs until asked to stop."""
        logger.info("worker started; polling for work")
        idle_since: float | None = None
        while not self.stopping:
            executed = self.run_once()
            if executed:
                idle_since = None
                continue
            if idle_since is None:
                idle_since = time.monotonic()
            time.sleep(self.settings.worker_poll_interval_s)
        logger.info("worker stopped")

    def run_until_idle(self, *, max_jobs: int = 1000) -> int:
        """Execute jobs until none remain.

        Used by the CLI and by integration tests, where waiting on a poll interval would
        only make the run slower.

        Args:
            max_jobs: Safety ceiling, so a bug cannot spin forever.

        Returns:
            How many jobs were executed.
        """
        executed = 0
        while executed < max_jobs and self.run_once():
            executed += 1
        return executed

    # --- one job ------------------------------------------------------------------------

    def run_once(self) -> bool:
        """Claim and execute a single job.

        Returns:
            Whether a job was claimed. ``False`` means there is nothing to do.
        """
        with self.unit_of_work() as uow:
            job = uow.jobs.claim_next(lease_seconds=self.settings.job_lease_seconds)
            if job is None:
                return False
            claimed = job

        self._execute(claimed)
        return True

    def _cancellation_probe(self, job: Job) -> Callable[[], bool]:
        """Return a check for "has this run been cancelled", safe to poll.

        Read on its own connection, for two reasons. The stage's transaction holds a
        snapshot from before the cancellation was written, so asking it would answer "no"
        until that transaction commits. And a reader never blocks on a writer under WAL,
        which is what makes a second connection safe here where a second *writer* is not:
        giving progress reporting its own connection deadlocked the process against itself.

        Throttled, because the process runner polls this while a subprocess runs and a
        query every tenth of a second buys nothing.
        """
        last = [0.0]
        cached = [False]

        def cancelled() -> bool:
            if self.stopping or cached[0]:
                return True
            now = time.monotonic()
            if now - last[0] < _CANCELLATION_POLL_S:
                return cached[0]
            last[0] = now
            with self.unit_of_work() as uow:
                cached[0] = uow.jobs.is_cancelled(job.run_id)
            return cached[0]

        return cancelled

    def _execute(self, job: Job) -> None:
        """Run one job's stage and record the outcome.

        The stage runs *outside* any write transaction that is already holding the database.
        Recording that a stage started used to happen inside the same transaction as the
        stage itself, which took SQLite's write lock before a model had even loaded and held
        it for the whole stage -- two minutes for transcription of a long source. Every
        write from the API during that window failed with "database is locked".
        """
        handler = HANDLERS.get(job.stage)
        started = time.monotonic()

        # A short transaction of its own: announce the stage, then let go.
        with self.unit_of_work() as uow:
            project = uow.projects.get(job.project_id)
            run = uow.jobs.get_run(job.run_id)

            if handler is None:
                # An unregistered stage is a programming error, but failing the job with a
                # clear message beats crashing the worker and stalling the whole project.
                logger.error("no handler is registered for stage %s", job.stage)
                uow.jobs.save_job(
                    job.transition_to(
                        JobStatus.FAILED, error=f"no handler for stage {job.stage.value}"
                    )
                )
                return

            uow.events.append(
                project.id,
                "stage_started",
                {"stage": job.stage.value, "label": job.stage.label},
                run_id=run.id,
            )
        logger.info("[%s] %s", project.id, job.stage.label)

        cancelled = self._cancellation_probe(job)
        # Cancelling must reach the process actually doing the work. Without this a stop is
        # only noticed at the next checkpoint, and a stage that spends minutes inside one
        # FFmpeg or Demucs call has no checkpoint to reach. Removed again afterwards so the
        # shared runner never carries one job's cancellation into another's lifetime.
        self.registry.runner.cancelled = cancelled
        try:
            self._run_stage(job, cancelled, started)
        finally:
            self.registry.runner.cancelled = _NEVER_CANCELLED

    def _run_stage(self, job: Job, cancelled: Callable[[], bool], started: float) -> None:
        """Execute the stage itself, with the outcome recorded in one short transaction."""
        handler = HANDLERS[job.stage]
        with self.unit_of_work() as uow:
            project = uow.projects.get(job.project_id)
            run = uow.jobs.get_run(job.run_id)
            context = StageContext(
                uow=uow,
                registry=self.registry,
                settings=self.settings,
                project=project,
                run=run,
                job=job,
                # Progress and cancellation stay on this one connection. Giving them their
                # own would mean a second connection trying to write while this one holds
                # the write lock, which is a deadlock the process has with itself.
                report=lambda fraction, detail: self._report(uow, job, fraction, detail),
                is_cancelled=cancelled,
                release=uow.session.commit,
            )

            try:
                handler(context)
            except CancelledError as exc:
                self._finish_cancelled(uow, job, exc)
                return
            except GermanDubIError as exc:
                self._finish_failed(uow, job, exc.message, code=exc.code)
                return
            except Exception as exc:
                logger.exception("stage %s raised an unexpected error", job.stage)
                self._finish_failed(uow, job, f"unexpected error: {exc}", code="internal_error")
                return

            elapsed = time.monotonic() - started
            uow.jobs.save_job(job.transition_to(JobStatus.SUCCEEDED))
            uow.events.append(
                project.id,
                "stage_finished",
                {"stage": job.stage.value, "seconds": round(elapsed, 2)},
                run_id=run.id,
            )
            self._finish_run_if_complete(uow, job)
            logger.info("[%s] %s finished in %.1fs", project.id, job.stage.label, elapsed)

    # --- outcomes -----------------------------------------------------------------------

    @staticmethod
    def _report(uow: UnitOfWork, job: Job, fraction: float, detail: str | None) -> None:
        """Persist a progress update so the browser sees it."""
        uow.jobs.save_job(job.with_progress(fraction, detail))
        uow.events.append(
            job.project_id,
            "stage_progress",
            {"stage": job.stage.value, "progress": round(fraction, 4), "detail": detail},
            run_id=job.run_id,
        )
        uow.flush()

    def _finish_cancelled(self, uow: UnitOfWork, job: Job, exc: CancelledError) -> None:
        """Record that a stage stopped because cancellation was requested."""
        current = uow.jobs.get_job(job.id)
        uow.jobs.save_job(current.transition_to(JobStatus.CANCELLED))
        uow.events.append(
            job.project_id,
            "stage_cancelled",
            {"stage": job.stage.value, "message": exc.message},
            run_id=job.run_id,
        )
        project = uow.projects.get(job.project_id)
        if project.state is ProjectState.PROCESSING:
            uow.projects.save(project.transition_to(ProjectState.CANCELLED))
        logger.info("stage %s cancelled", job.stage)

    def _finish_failed(self, uow: UnitOfWork, job: Job, message: str, *, code: str) -> None:
        """Record a stage failure, retrying when attempts remain."""
        current = uow.jobs.get_job(job.id)
        failed = current.transition_to(JobStatus.FAILED, error=message)

        if failed.can_retry:
            # Re-queue rather than giving up: transient failures - a dropped connection, a
            # busy GPU - are common and a whole run should not die for one.
            uow.jobs.save_job(failed.transition_to(JobStatus.QUEUED))
            uow.events.append(
                job.project_id,
                "stage_retrying",
                {"stage": job.stage.value, "attempt": failed.attempt, "message": message},
                run_id=job.run_id,
            )
            logger.warning(
                "stage %s failed (attempt %d), retrying: %s", job.stage, failed.attempt, message
            )
            return

        uow.jobs.save_job(failed)
        uow.events.append(
            job.project_id,
            "stage_failed",
            {"stage": job.stage.value, "message": message, "code": code},
            run_id=job.run_id,
        )
        project = uow.projects.get(job.project_id)
        if project.state.is_busy:
            uow.projects.save(
                project.transition_to(ProjectState.FAILED, error=f"{job.stage.label}: {message}")
            )
        logger.error("stage %s failed permanently: %s", job.stage, message)

    @staticmethod
    def _finish_run_if_complete(uow: UnitOfWork, job: Job) -> None:
        """Close the run and settle the project's state once no jobs remain."""
        if uow.jobs.pending_count(job.run_id) > 0:
            return
        run = uow.jobs.get_run(job.run_id)
        uow.jobs.save_run(run.finished())

        project = uow.projects.get(job.project_id)
        if project.state is ProjectState.PROCESSING:
            uow.projects.save(project.transition_to(ProjectState.REVIEW))
        uow.events.append(
            job.project_id, "run_finished", {"run_id": str(job.run_id)}, run_id=job.run_id
        )
