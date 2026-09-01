"""Project lifecycle endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from germandubi.api.dependencies import PipelineDep, ProjectIdDep, ProjectsDep
from germandubi.api.schemas import (
    CreateProjectRequest,
    ErrorResponse,
    ProjectDetail,
    ProjectSummary,
    RunDetail,
)
from germandubi.domain.errors import DomainError

router = APIRouter(prefix="/projects", tags=["projects"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project."},
    409: {"model": ErrorResponse, "description": "The project is in the wrong state."},
    422: {"model": ErrorResponse, "description": "The request was not acceptable."},
}


@router.post(
    "",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description=(
        "Creates a dubbing project from a YouTube URL or a local file. The URL is validated "
        "against a host allowlist before anything is stored or downloaded."
    ),
    responses=_ERRORS,
    operation_id="createProject",
)
async def create_project(payload: CreateProjectRequest, projects: ProjectsDep) -> ProjectDetail:
    """Create a project.

    Args:
        payload: The source and quality profile.
        projects: The project service.

    Returns:
        The created project.

    Raises:
        DomainError: If neither a URL nor a file path was given, or both were.
        SourceValidationError: If the URL is not acceptable.
    """
    if bool(payload.url) == bool(payload.file_path):
        msg = "provide either a source URL or a local file path, not both and not neither"
        raise DomainError(msg)
    project = (
        projects.create_from_url(payload.url, quality=payload.quality, voice=payload.voice)
        if payload.url
        else projects.create_from_file(
            payload.file_path or "", quality=payload.quality, voice=payload.voice
        )
    )
    return ProjectDetail.of(project)


@router.get(
    "",
    response_model=list[ProjectSummary],
    summary="List projects",
    description="Returns projects newest first.",
    operation_id="listProjects",
)
async def list_projects(
    projects: ProjectsDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectSummary]:
    """Return projects, newest first.

    Args:
        projects: The project service.
        limit: Maximum number to return.
        offset: How many to skip.

    Returns:
        The project summaries.
    """
    return [ProjectSummary.of(p) for p in projects.list_projects(limit=limit, offset=offset)]


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Get a project",
    responses=_ERRORS,
    operation_id="getProject",
)
async def get_project(project_id: ProjectIdDep, projects: ProjectsDep) -> ProjectDetail:
    """Return one project.

    Args:
        project_id: The project.
        projects: The project service.

    Returns:
        The project.

    Raises:
        NotFoundError: If it does not exist.
    """
    return ProjectDetail.of(projects.get(project_id))


@router.post(
    "/{project_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Stop this project",
    description=(
        "Stops whatever this project is currently doing. Work already finished is kept and "
        "the run can be resumed later."
    ),
    responses=_ERRORS,
    operation_id="cancelProject",
)
async def cancel_project(project_id: ProjectIdDep, pipeline: PipelineDep) -> None:
    """Cancel the project's most recent run.

    Args:
        project_id: The project.
        pipeline: The pipeline service.
    """
    pipeline.cancel_latest(project_id)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete every project",
    description=(
        "Cancels anything still running, then deletes every project and its workspace. "
        "This cannot be undone."
    ),
    operation_id="deleteAllProjects",
)
async def delete_all_projects(projects: ProjectsDep) -> None:
    """Clear every project and its files.

    Args:
        projects: The project service.
    """
    projects.delete_all()


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    description="Deletes the project and everything in its workspace. This cannot be undone.",
    responses=_ERRORS,
    operation_id="deleteProject",
)
async def delete_project(project_id: ProjectIdDep, projects: ProjectsDep) -> None:
    """Delete a project and its workspace.

    Args:
        project_id: The project.
        projects: The project service.

    Raises:
        NotFoundError: If it does not exist.
    """
    projects.delete(project_id)


@router.post(
    "/{project_id}/analyze",
    response_model=RunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Analyze the source",
    description=(
        "Queues a cheap probe that reads the source's title, duration and caption "
        "availability without downloading any media. Watch progress on the events stream."
    ),
    responses=_ERRORS,
    operation_id="analyzeProject",
)
async def analyze_project(
    project_id: ProjectIdDep, projects: ProjectsDep, pipeline: PipelineDep
) -> RunDetail:
    """Queue the source probe.

    Args:
        project_id: The project to analyse.
        projects: The project service.
        pipeline: The pipeline service.

    Returns:
        The queued run.

    Raises:
        NotFoundError: If the project does not exist.
        DomainError: If the project is already busy.
    """
    run = projects.request_analysis(project_id)
    progress = pipeline.progress(run.id)
    return RunDetail.of(
        progress.run,
        progress.jobs,
        progress=progress.fraction,
        finished=progress.finished,
        failed=progress.failed,
    )
