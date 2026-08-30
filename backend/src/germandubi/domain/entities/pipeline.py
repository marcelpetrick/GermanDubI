"""The processing pipeline as a persisted dependency graph.

The pipeline is not one long function. It is a declared graph of stages, so that a run can
be resumed after a crash, a single stage can be re-run after an edit, and the effect of an
edit on everything downstream can be computed rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Self

from germandubi.domain.errors import DomainError, InvalidStateTransitionError
from germandubi.domain.value_objects.identifiers import JobId, ProjectId, RunId, new_id

__all__ = [
    "STAGE_DEPENDENCIES",
    "STAGE_ORDER",
    "Job",
    "JobStatus",
    "PipelineRun",
    "Stage",
    "downstream_of",
    "stages_in_execution_order",
]


class Stage(StrEnum):
    """One step of the dubbing pipeline (``vision.md`` section 10)."""

    PROBE = "probe"
    ACQUIRE = "acquire"
    NORMALIZE = "normalize"
    TRANSCRIBE = "transcribe"
    ALIGN = "align"
    SEGMENT = "segment"
    SEPARATE = "separate"
    TRANSLATE = "translate"
    PROSODY = "prosody"
    SYNTHESIZE = "synthesize"
    FIT = "fit"
    ASSEMBLE = "assemble"
    MIX = "mix"
    SUBTITLE = "subtitle"
    QA = "qa"
    EXPORT = "export"

    @property
    def label(self) -> str:
        """Return the human-readable stage name shown on the processing screen."""
        return {
            Stage.PROBE: "Inspecting source",
            Stage.ACQUIRE: "Downloading media",
            Stage.NORMALIZE: "Extracting audio",
            Stage.TRANSCRIBE: "Getting English transcript",
            Stage.ALIGN: "Aligning word timing",
            Stage.SEGMENT: "Creating dubbing segments",
            Stage.SEPARATE: "Separating voice and background",
            Stage.TRANSLATE: "Translating to German",
            Stage.PROSODY: "Analysing narration",
            Stage.SYNTHESIZE: "Synthesizing German speech",
            Stage.FIT: "Fitting speech to timing",
            Stage.ASSEMBLE: "Assembling German narration",
            Stage.MIX: "Mixing audio",
            Stage.SUBTITLE: "Writing subtitles",
            Stage.QA: "Running quality checks",
            Stage.EXPORT: "Exporting video",
        }[self]


#: What each stage needs before it can run. This is the single source of truth for both
#: execution order and invalidation; deriving both from one declaration is what keeps them
#: from drifting apart.
STAGE_DEPENDENCIES: Final[dict[Stage, frozenset[Stage]]] = {
    Stage.PROBE: frozenset(),
    Stage.ACQUIRE: frozenset({Stage.PROBE}),
    Stage.NORMALIZE: frozenset({Stage.ACQUIRE}),
    Stage.TRANSCRIBE: frozenset({Stage.NORMALIZE}),
    Stage.ALIGN: frozenset({Stage.TRANSCRIBE}),
    Stage.SEGMENT: frozenset({Stage.ALIGN}),
    Stage.SEPARATE: frozenset({Stage.NORMALIZE}),
    Stage.TRANSLATE: frozenset({Stage.SEGMENT}),
    Stage.PROSODY: frozenset({Stage.SEGMENT}),
    Stage.SYNTHESIZE: frozenset({Stage.TRANSLATE, Stage.PROSODY}),
    Stage.FIT: frozenset({Stage.SYNTHESIZE}),
    Stage.ASSEMBLE: frozenset({Stage.FIT}),
    Stage.MIX: frozenset({Stage.ASSEMBLE, Stage.SEPARATE}),
    Stage.SUBTITLE: frozenset({Stage.TRANSLATE}),
    Stage.QA: frozenset({Stage.MIX, Stage.SUBTITLE}),
    Stage.EXPORT: frozenset({Stage.QA}),
}


def stages_in_execution_order() -> tuple[Stage, ...]:
    """Return every stage in a valid execution order.

    Performs a deterministic topological sort of :data:`STAGE_DEPENDENCIES`, breaking ties
    by declaration order so that the processing screen always lists stages the same way.

    Returns:
        The stages, each appearing after all of its dependencies.

    Raises:
        DomainError: If the declared dependencies contain a cycle.
    """
    declared = list(STAGE_DEPENDENCIES)
    ordered: list[Stage] = []
    placed: set[Stage] = set()
    while len(ordered) < len(declared):
        ready = [s for s in declared if s not in placed and STAGE_DEPENDENCIES[s] <= placed]
        if not ready:
            remaining = sorted(s for s in declared if s not in placed)
            msg = f"the pipeline stage graph contains a cycle involving: {remaining}"
            raise DomainError(msg)
        ordered.extend(ready)
        placed.update(ready)
    return tuple(ordered)


STAGE_ORDER: Final[tuple[Stage, ...]] = stages_in_execution_order()


def downstream_of(stages: frozenset[Stage] | set[Stage] | Stage) -> frozenset[Stage]:
    """Return every stage that must be redone when the given stages change.

    This is the invalidation graph. Editing the English text of one segment invalidates its
    translation, its speech, the narration assembly, the mix and the export - but nothing
    that is upstream, and nothing belonging to an unrelated segment.

    Args:
        stages: The stage or stages whose output changed.

    Returns:
        The transitive closure of dependents, **excluding** the given stages themselves.

    Example:
        >>> Stage.EXPORT in downstream_of(Stage.TRANSLATE)
        True
        >>> Stage.ACQUIRE in downstream_of(Stage.TRANSLATE)
        False
    """
    changed = frozenset({stages}) if isinstance(stages, Stage) else frozenset(stages)
    affected: set[Stage] = set()
    frontier = set(changed)
    while frontier:
        dependents = {
            stage
            for stage, needs in STAGE_DEPENDENCIES.items()
            if needs & frontier and stage not in affected
        }
        affected |= dependents
        frontier = dependents
    return frozenset(affected - changed)


class JobStatus(StrEnum):
    """The lifecycle of one unit of work (``vision.md`` section 12.2)."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"

    @property
    def is_finished(self) -> bool:
        """Return whether the job will not be worked on again as it stands."""
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.SKIPPED,
            JobStatus.INVALIDATED,
        }

    @property
    def is_claimable(self) -> bool:
        """Return whether a worker may claim a job in this status."""
        return self in {JobStatus.PENDING, JobStatus.QUEUED}


_ALLOWED_JOB_TRANSITIONS: Final[dict[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.PENDING: frozenset(
        {JobStatus.QUEUED, JobStatus.SKIPPED, JobStatus.CANCELLED, JobStatus.INVALIDATED}
    ),
    JobStatus.QUEUED: frozenset(
        {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED, JobStatus.INVALIDATED}
    ),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCEL_REQUESTED,
            JobStatus.CANCELLED,
            JobStatus.QUEUED,
        }
    ),
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELLED, JobStatus.SUCCEEDED}),
    JobStatus.SUCCEEDED: frozenset({JobStatus.INVALIDATED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED, JobStatus.INVALIDATED}),
    JobStatus.CANCELLED: frozenset({JobStatus.QUEUED}),
    JobStatus.SKIPPED: frozenset({JobStatus.QUEUED, JobStatus.INVALIDATED}),
    JobStatus.INVALIDATED: frozenset({JobStatus.QUEUED}),
}

#: How many times a failed job is retried before the run gives up.
MAX_ATTEMPTS: Final = 3


@dataclass(frozen=True, slots=True)
class Job:
    """One persisted unit of work: a stage of a run.

    Attributes:
        id: Identity of the job.
        run_id: The run this job belongs to.
        project_id: The owning project.
        stage: Which pipeline stage this job performs.
        status: Current lifecycle status.
        attempt: How many times execution has been started, beginning at zero.
        input_hash: Hash of everything determining the output. A job whose input hash
            matches an existing successful result is skipped rather than repeated.
        error: Why the job failed, when it did.
        lease_expires_at: When the current claim expires. A worker that dies leaves the job
            claimable again after this moment, instead of stranding it in ``RUNNING``.
        progress: Fraction complete in ``[0, 1]``, for stages that can report it.
        progress_detail: A short human-readable note, e.g. ``124 / 192 segments``.
        created_at: When the job was created.
        started_at: When execution last began.
        finished_at: When the job reached a finished status.
    """

    id: JobId
    run_id: RunId
    project_id: ProjectId
    stage: Stage
    status: JobStatus = JobStatus.PENDING
    attempt: int = 0
    input_hash: str | None = None
    error: str | None = None
    lease_expires_at: datetime | None = None
    progress: float = 0.0
    progress_detail: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(cls, *, run_id: RunId, project_id: ProjectId, stage: Stage) -> Self:
        """Create a pending job for a stage.

        Args:
            run_id: The run this job belongs to.
            project_id: The owning project.
            stage: The stage to perform.

        Returns:
            The new job.
        """
        return cls(id=JobId(new_id()), run_id=run_id, project_id=project_id, stage=stage)

    @property
    def can_retry(self) -> bool:
        """Return whether a failed job still has attempts left."""
        return self.status is JobStatus.FAILED and self.attempt < MAX_ATTEMPTS

    def transition_to(self, status: JobStatus, *, error: str | None = None) -> Self:
        """Return a copy in a new status.

        Args:
            status: The requested status.
            error: The failure reason, required when moving to ``FAILED``.

        Returns:
            The updated job.

        Raises:
            InvalidStateTransitionError: If the transition is not allowed.
            DomainError: If moving to ``FAILED`` without a reason.
        """
        if status is self.status:
            return self
        if status not in _ALLOWED_JOB_TRANSITIONS[self.status]:
            msg = f"cannot move job {self.stage} from {self.status} to {status}"
            raise InvalidStateTransitionError(msg, current=str(self.status), requested=str(status))
        if status is JobStatus.FAILED and not error:
            msg = "a failed job must record why it failed"
            raise DomainError(msg, job_id=str(self.id))

        now = datetime.now(UTC)
        return replace(
            self,
            status=status,
            error=error if status is JobStatus.FAILED else self.error,
            started_at=now if status is JobStatus.RUNNING else self.started_at,
            finished_at=now if status.is_finished else None,
            progress=1.0 if status is JobStatus.SUCCEEDED else self.progress,
            lease_expires_at=None if status.is_finished else self.lease_expires_at,
        )

    def claimed(self, *, lease_expires_at: datetime, input_hash: str | None = None) -> Self:
        """Return a copy claimed by a worker and moved to ``RUNNING``.

        Args:
            lease_expires_at: When this claim expires and the job becomes claimable again.
            input_hash: Hash of the job's resolved inputs.

        Returns:
            The claimed job.
        """
        running = self.transition_to(JobStatus.RUNNING)
        return replace(
            running,
            attempt=self.attempt + 1,
            lease_expires_at=lease_expires_at,
            input_hash=input_hash if input_hash is not None else self.input_hash,
        )

    def with_progress(self, progress: float, detail: str | None = None) -> Self:
        """Return a copy with updated progress.

        Args:
            progress: Fraction complete; clamped into ``[0, 1]``.
            detail: A short human-readable note for the processing screen.

        Returns:
            The updated job.
        """
        return replace(self, progress=min(1.0, max(0.0, progress)), progress_detail=detail)


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """One attempt to take a project through the pipeline.

    A run is created when the user presses "Create German Dub", and again for every partial
    regeneration. Keeping runs separate is what lets the UI say what is happening now
    without losing the history of what happened before.

    Attributes:
        id: Identity of the run.
        project_id: The owning project.
        stages: The stages this run intends to execute, in execution order.
        created_at: When the run was created.
        finished_at: When the run reached a terminal outcome.
        cancelled: Whether cancellation was requested for the whole run.
    """

    id: RunId
    project_id: ProjectId
    stages: tuple[Stage, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    cancelled: bool = False

    @classmethod
    def create(cls, project_id: ProjectId, *, stages: tuple[Stage, ...] | None = None) -> Self:
        """Create a run covering the given stages, or the full pipeline.

        Args:
            project_id: The owning project.
            stages: The stages to run. Defaults to the whole pipeline. The given stages are
                reordered into a valid execution order.

        Returns:
            The new run.

        Raises:
            DomainError: If ``stages`` is empty.
        """
        if stages is not None and not stages:
            msg = "a run must contain at least one stage"
            raise DomainError(msg, project_id=str(project_id))
        wanted = set(STAGE_ORDER) if stages is None else set(stages)
        return cls(
            id=RunId(new_id()),
            project_id=project_id,
            stages=tuple(s for s in STAGE_ORDER if s in wanted),
        )

    def finished(self) -> Self:
        """Return a copy marked as finished."""
        return replace(self, finished_at=datetime.now(UTC))

    def cancellation_requested(self) -> Self:
        """Return a copy with cancellation requested."""
        return replace(self, cancelled=True)
