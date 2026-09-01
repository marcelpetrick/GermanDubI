"""What a stage handler is given to do its work.

A handler receives one context and returns nothing. Everything it may touch - repositories,
the artifact store, providers, progress reporting, cancellation - arrives through this
object, so a handler is testable by constructing a context and is unable to reach around
the boundaries by accident.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from germandubi.application.services.unit_of_work import UnitOfWork
from germandubi.config import Settings
from germandubi.domain.entities.artifact import Artifact, ArtifactKind, Provenance
from germandubi.domain.entities.pipeline import Job, PipelineRun
from germandubi.domain.entities.project import Project
from germandubi.domain.errors import CancelledError, ResourceError
from germandubi.domain.value_objects.content_hash import ContentHash
from germandubi.infrastructure.providers.registry import ProviderRegistry
from germandubi.version import build_info

__all__ = ["StageContext"]

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    """Everything one stage needs, and nothing more.

    Attributes:
        uow: The transaction this stage runs in.
        registry: Provider selection.
        settings: Application settings.
        project: The project being processed.
        run: The run this stage belongs to.
        job: The job being executed.
        report: Callback for progress updates, shown on the processing screen. Like a
            checkpoint it commits, so reporting progress never leaves the write lock held
            across the work that follows it.
        is_cancelled: Consulted at checkpoints; a handler that never calls it cannot be
            cancelled, which is a bug in that handler.
        release: Commits what the stage has written so far and drops the database write
            lock. Called at every checkpoint, because a stage that writes as it goes would
            otherwise hold the lock for its whole duration and fail every concurrent write
            from the API.
    """

    uow: UnitOfWork
    registry: ProviderRegistry
    settings: Settings
    project: Project
    run: PipelineRun
    job: Job
    report: Callable[[float, str | None], None] = field(default=lambda _p, _d: None)
    is_cancelled: Callable[[], bool] = field(default=lambda: False)
    release: Callable[[], None] = field(default=lambda: None)

    # --- workspace ----------------------------------------------------------------------

    @property
    def workspace(self) -> Path:
        """Return the project's workspace directory."""
        return self.uow.store.workspace(self.project.id)

    def directory(self, name: str) -> Path:
        """Return a workspace sub-directory, creating it if needed.

        Args:
            name: The sub-directory name, e.g. ``speech``.

        Returns:
            The absolute path.
        """
        path = self.workspace / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- artifacts ----------------------------------------------------------------------

    def latest(self, kind: ArtifactKind, *, segment_id: str | None = None) -> Artifact | None:
        """Return the current artifact of a kind, if a previous stage produced one.

        Args:
            kind: The artifact kind.
            segment_id: Restrict to one segment.

        Returns:
            The artifact, or ``None``.
        """
        return self.uow.artifacts.latest(self.project.id, kind, segment_id=segment_id)

    def require(self, kind: ArtifactKind) -> Path:
        """Return the path of a required upstream artifact.

        Args:
            kind: The artifact kind this stage depends on.

        Returns:
            The absolute path to the file.

        Raises:
            ResourceError: If the artifact is missing or its file has disappeared. This is
                a clearer failure than whatever the tool would emit two steps later.
        """
        artifact = self.latest(kind)
        if artifact is None:
            msg = (
                f"the {kind.value.replace('_', ' ')} this stage needs has not been produced "
                f"yet. Re-run the pipeline from the start."
            )
            raise ResourceError(msg, kind=kind.value, stage=self.job.stage.value)
        path = self.uow.store.path_for(artifact)
        if not path.exists():
            msg = (
                f"the {kind.value.replace('_', ' ')} file is missing from the project "
                f"workspace. It may have been deleted; re-run the pipeline."
            )
            raise ResourceError(msg, kind=kind.value, path=artifact.relative_path)
        return path

    def publish(
        self,
        kind: ArtifactKind,
        path: Path,
        *,
        provider_id: str,
        input_hash: ContentHash,
        model_id: str | None = None,
        parameters: dict[str, str] | None = None,
        segment_id: str | None = None,
        media_type: str | None = None,
        supersede: bool = True,
    ) -> Artifact:
        """Record a file this stage produced, with its provenance.

        Args:
            kind: What the artifact is.
            path: The file, already written inside the workspace.
            provider_id: The provider that produced it.
            input_hash: Hash of everything that determined the output.
            model_id: The model or voice used.
            parameters: Provider configuration, for diagnostics.
            segment_id: The owning segment, for per-segment artifacts.
            media_type: IANA media type, for the preview endpoints.
            supersede: Whether to mark previous artifacts of this kind superseded. Their
                files stay on disk; processing here is non-destructive.

        Returns:
            The recorded artifact.

        Raises:
            ResourceError: If the file was not actually written.
        """
        if supersede:
            self.uow.artifacts.supersede(self.project.id, kind, segment_id=segment_id)

        relative = path.resolve().relative_to(self.workspace.resolve()).as_posix()
        artifact = Artifact(
            id=Artifact.create(project_id=self.project.id, kind=kind, filename=path.name).id,
            project_id=self.project.id,
            kind=kind,
            relative_path=relative,
            segment_id=segment_id,
            media_type=media_type,
            provenance=Provenance(
                app_version=build_info().version,
                provider_id=provider_id,
                input_hash=input_hash,
                model_id=model_id,
                parameters=parameters or {},
            ),
        )
        recorded = self.uow.store.record(artifact)
        self.uow.artifacts.add(recorded)
        return recorded

    def reusable(
        self, kind: ArtifactKind, input_hash: ContentHash, *, segment_id: str | None = None
    ) -> Path | None:
        """Return an existing artifact's path when its inputs are unchanged.

        This is what makes the pipeline idempotent by input hash: re-running a stage whose
        inputs did not change reuses the previous result instead of recomputing it, which
        is why a partial regeneration is cheap.

        Args:
            kind: The artifact kind.
            input_hash: The hash of this run's inputs.
            segment_id: Restrict to one segment.

        Returns:
            The path to reuse, or ``None`` when the work must be done.
        """
        artifact = self.latest(kind, segment_id=segment_id)
        if artifact is None or artifact.provenance is None:
            return None
        if artifact.provenance.input_hash != input_hash:
            return None
        path = self.uow.store.path_for(artifact)
        return path if path.exists() else None

    # --- progress and cancellation ------------------------------------------------------

    def progress(self, fraction: float, detail: str | None = None) -> None:
        """Report progress for the processing screen.

        This commits, for the same reason :meth:`checkpoint` does, and the resumability
        requirement documented there applies here too. Announcing a step and *then* doing it
        is the natural way to write a handler -- ``progress(0.1, "using faster-whisper")``
        followed by two minutes of recognition -- and if that report only flushed, those two
        minutes would be spent holding SQLite's write lock with every API write failing.

        Args:
            fraction: Completion in ``[0, 1]``.
            detail: A short note, e.g. ``124 / 192 segments``.
        """
        self.report(fraction, detail)

    def checkpoint(self) -> None:
        """Stop the stage if cancellation has been requested.

        Handlers call this between units of work. A stage that never calls it cannot be
        cancelled, which makes the UI's cancel button a lie.

        It is also where a long stage lets go of the database, and that carries a
        requirement every handler must meet.

        **A handler must be safe to run again after stopping part-way.** Committing here
        means a stage that fails later leaves what it had already written, and the retry
        will meet that partial work. Handlers satisfy this by looking for their own output
        before producing it -- speech synthesis skips a segment that already has audio --
        so a retry resumes rather than duplicating. A handler that assumed its writes would
        roll back would silently corrupt a project on its second attempt.

        The alternative is holding the write lock for the whole stage, which is what this
        used to do: two minutes during transcription of a long source, and every write from
        the API failing with "database is locked" for the duration. :meth:`progress`
        commits for the same reason, so a handler cannot dodge the contract by reporting
        instead of checkpointing.

        Raises:
            CancelledError: If cancellation was requested.
        """
        if self.is_cancelled():
            msg = f"the {self.job.stage.label.lower()} stage was cancelled"
            raise CancelledError(msg, stage=self.job.stage.value)
        self.release()

    def event(self, kind: str, payload: dict[str, object]) -> None:
        """Append a progress event for the browser.

        Args:
            kind: The event type.
            payload: Event data.
        """
        self.uow.events.append(self.project.id, kind, dict(payload), run_id=self.run.id)
