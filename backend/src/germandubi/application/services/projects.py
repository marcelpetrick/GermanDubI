"""Project lifecycle use cases."""

from __future__ import annotations

import logging
from typing import Final

from germandubi.application.services.unit_of_work import UnitOfWorkFactory
from germandubi.domain.entities.pipeline import Job, PipelineRun, Stage
from germandubi.domain.entities.project import (
    Project,
    ProjectState,
    QualityProfile,
    SourceKind,
    SourceRef,
)
from germandubi.domain.errors import DomainError, NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId
from germandubi.domain.value_objects.source_url import validate_source_url
from germandubi.version import build_info

__all__ = ["ProjectService"]

logger = logging.getLogger(__name__)

#: How many projects one pass of a full clear removes before looking again.
_DELETE_BATCH: Final = 200


class ProjectService:
    """Creating, listing, analysing and deleting projects."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        """Initialise the service.

        Args:
            unit_of_work: Factory producing a transaction per operation.
        """
        self.unit_of_work = unit_of_work

    def create_from_url(
        self,
        url: str,
        *,
        quality: QualityProfile = QualityProfile.BALANCED,
        voice: str | None = None,
    ) -> Project:
        """Create a project from a source URL.

        The URL is validated against the domain allowlist before anything is persisted, so
        an unacceptable URL never reaches storage or the downloader.

        Args:
            url: The URL as typed by the user.
            quality: The speed/quality trade-off to use.
            voice: The German narrator, or ``None`` for the configured default.

        Returns:
            The created project, in the ``NEW`` state.

        Raises:
            SourceValidationError: If the URL is not acceptable.
        """
        source = SourceRef.from_url(validate_source_url(url))
        return self._create(source, quality, voice)

    def create_from_file(
        self,
        path: str,
        *,
        quality: QualityProfile = QualityProfile.BALANCED,
        voice: str | None = None,
    ) -> Project:
        """Create a project from a local media file.

        Args:
            path: Absolute path to a readable media file.
            quality: The speed/quality trade-off to use.
            voice: The German narrator, or ``None`` for the configured default.

        Returns:
            The created project.

        Raises:
            DomainError: If the path is not absolute.
        """
        return self._create(SourceRef.from_local_file(path), quality, voice)

    def _create(
        self, source: SourceRef, quality: QualityProfile, voice: str | None = None
    ) -> Project:
        """Persist a new project and create its workspace."""
        project = Project.create(source, quality=quality, voice=voice)
        with self.unit_of_work() as uow:
            uow.projects.add(project, created_with=build_info().version)
            uow.store.create_workspace(project.id)
            uow.events.append(
                project.id,
                "project_created",
                {"source": source.locator, "kind": source.kind.value},
            )
        logger.info("created project %s for %s", project.id, source.locator)
        return project

    def get(self, project_id: ProjectId) -> Project:
        """Return a project.

        Args:
            project_id: The project.

        Returns:
            The project.

        Raises:
            NotFoundError: If it does not exist.
        """
        with self.unit_of_work() as uow:
            return uow.projects.get(project_id)

    def list_projects(self, *, limit: int = 100, offset: int = 0) -> list[Project]:
        """Return projects, newest first.

        Args:
            limit: Maximum number to return.
            offset: How many to skip.

        Returns:
            The projects.
        """
        with self.unit_of_work() as uow:
            return uow.projects.list_all(limit=limit, offset=offset)

    def delete(self, project_id: ProjectId) -> None:
        """Delete a project, its database rows and its workspace.

        Args:
            project_id: The project.

        Raises:
            NotFoundError: If it does not exist.
        """
        with self.unit_of_work() as uow:
            uow.projects.get(project_id)
            uow.projects.delete(project_id)
            uow.store.delete_workspace(project_id)
        logger.info("deleted project %s", project_id)

    def delete_all(self) -> int:
        """Delete every project, its rows and its workspace.

        One operation rather than a loop of deletes driven from the browser: a clear that
        stops halfway would leave workspace directories with no project pointing at them,
        and nothing would ever collect them.

        A run in progress is cancelled first. Deleting a project the worker is still
        writing into would otherwise recreate its directory moments later.

        Returns:
            How many projects were removed.
        """
        removed = 0
        with self.unit_of_work() as uow:
            uow.jobs.cancel_all()
            # Paged rather than capped: a limit chosen for plausibility would silently
            # leave the rest behind, which is the one thing a "delete everything" must not do.
            while batch := uow.projects.list_all(limit=_DELETE_BATCH, offset=0):
                for project in batch:
                    uow.projects.delete(project.id)
                    uow.store.delete_workspace(project.id)
                uow.flush()
                removed += len(batch)
        logger.info("deleted %d project(s) and their workspaces", removed)
        return removed

    def set_quality(self, project_id: ProjectId, quality: QualityProfile) -> Project:
        """Change a project's quality profile.

        Args:
            project_id: The project.
            quality: The new profile.

        Returns:
            The updated project.

        Raises:
            NotFoundError: If the project does not exist.
        """
        with self.unit_of_work() as uow:
            project = uow.projects.get(project_id).with_quality(quality)
            uow.projects.save(project)
            return project

    def request_analysis(self, project_id: ProjectId) -> PipelineRun:
        """Queue the cheap source probe.

        Analysis is a one-stage run rather than a synchronous call, so the UI stays
        responsive while the source site is contacted, and so a failed probe is retryable
        through the same machinery as every other stage.

        Args:
            project_id: The project to analyse.

        Returns:
            The queued run.

        Raises:
            NotFoundError: If the project does not exist.
            InvalidStateTransitionError: If the project is already busy.
        """
        with self.unit_of_work() as uow:
            project = uow.projects.get(project_id)
            if project.state.is_busy:
                msg = f"this project is already {project.state}; wait for it to finish"
                raise DomainError(msg, state=str(project.state))

            run = PipelineRun.create(project.id, stages=(Stage.PROBE,))
            uow.jobs.add_run(
                run, [Job.create(run_id=run.id, project_id=project.id, stage=Stage.PROBE)]
            )
            uow.projects.save(project.transition_to(ProjectState.PROBING))
            uow.events.append(project.id, "analysis_requested", {"run_id": str(run.id)})
            return run

    def resolve(self, project_id: ProjectId) -> Project:
        """Return a project, raising a clear error when the identity is unknown.

        Args:
            project_id: The project.

        Returns:
            The project.

        Raises:
            NotFoundError: If it does not exist.
        """
        project = None
        with self.unit_of_work() as uow:
            project = uow.projects.find(project_id)
        if project is None:
            msg = f"no project with id {project_id}"
            raise NotFoundError(msg, project_id=str(project_id))
        return project

    @staticmethod
    def describe_source(project: Project) -> str:
        """Return a short human-readable description of what is being dubbed.

        Args:
            project: The project.

        Returns:
            A description suitable for a log line or a page title.
        """
        if project.source.kind is SourceKind.LOCAL_FILE:
            return f"local file {project.source.locator}"
        return project.display_title
