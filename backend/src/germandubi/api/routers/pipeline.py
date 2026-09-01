"""Pipeline run endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from germandubi.api.dependencies import PipelineDep, ProjectIdDep, RunIdDep
from germandubi.api.schemas import ErrorResponse, RunDetail, StartRunRequest
from germandubi.application.services.pipeline import RunProgress
from germandubi.domain.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["pipeline"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project or run."},
    409: {"model": ErrorResponse, "description": "The project is in the wrong state."},
}


def _detail(progress: RunProgress) -> RunDetail:
    """Render a run snapshot for the wire."""
    return RunDetail.of(
        progress.run,
        progress.jobs,
        progress=progress.fraction,
        finished=progress.finished,
        failed=progress.failed,
        queue_position=progress.queue_position,
        queue_length=progress.queue_length,
    )


@router.post(
    "",
    response_model=RunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a dub",
    description=(
        "Queues the pipeline. Omit `stages` to run everything after the probe. Progress "
        "arrives on the events stream; this returns as soon as the work is queued."
    ),
    responses=_ERRORS,
    operation_id="startRun",
)
async def start_run(
    project_id: ProjectIdDep, payload: StartRunRequest, pipeline: PipelineDep
) -> RunDetail:
    """Queue a full or partial pipeline run.

    Args:
        project_id: The project to process.
        payload: Which stages to run.
        pipeline: The pipeline service.

    Returns:
        The queued run.

    Raises:
        NotFoundError: If the project does not exist.
        DomainError: If the project is busy or has not been analysed.
    """
    run = pipeline.start(project_id, stages=tuple(payload.stages) if payload.stages else None)
    return _detail(pipeline.progress(run.id))


@router.get(
    "/latest",
    response_model=RunDetail | None,
    summary="Latest run",
    description="The project's most recent run, or null if it has never been processed.",
    responses=_ERRORS,
    operation_id="getLatestRun",
)
async def get_latest_run(project_id: ProjectIdDep, pipeline: PipelineDep) -> RunDetail | None:
    """Return the project's most recent run.

    Args:
        project_id: The project.
        pipeline: The pipeline service.

    Returns:
        The run, or ``None``.
    """
    progress = pipeline.latest_progress(project_id)
    return _detail(progress) if progress else None


@router.get(
    "/{run_id}",
    response_model=RunDetail,
    summary="Get a run",
    responses=_ERRORS,
    operation_id="getRun",
)
async def get_run(project_id: ProjectIdDep, run_id: RunIdDep, pipeline: PipelineDep) -> RunDetail:
    """Return one run.

    Args:
        project_id: The owning project.
        run_id: The run.
        pipeline: The pipeline service.

    Returns:
        The run.

    Raises:
        NotFoundError: If the run does not exist or belongs to another project.
    """
    progress = pipeline.progress(run_id)
    if progress.run.project_id != project_id:
        msg = f"no run with id {run_id} in this project"
        raise NotFoundError(msg, run_id=str(run_id))
    return _detail(progress)


@router.post(
    "/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunDetail,
    summary="Cancel a run",
    description=(
        "Cancellation is cooperative: queued stages stop immediately and a running stage "
        "stops at its next checkpoint, terminating any external process it started."
    ),
    responses=_ERRORS,
    operation_id="cancelRun",
)
async def cancel_run(
    project_id: ProjectIdDep, run_id: RunIdDep, pipeline: PipelineDep
) -> RunDetail:
    """Request cancellation of a run.

    Args:
        project_id: The owning project.
        run_id: The run to cancel.
        pipeline: The pipeline service.

    Returns:
        The cancelled run.

    Raises:
        NotFoundError: If the run does not exist.
    """
    del project_id
    pipeline.cancel(run_id)
    return _detail(pipeline.progress(run_id))


@router.post(
    "/resume",
    response_model=RunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resume after a failure or cancellation",
    description="Re-queues only the stages of the last run that did not finish successfully.",
    responses=_ERRORS,
    operation_id="resumeRun",
)
async def resume_run(project_id: ProjectIdDep, pipeline: PipelineDep) -> RunDetail:
    """Re-queue the unfinished stages of the last run.

    Args:
        project_id: The project to resume.
        pipeline: The pipeline service.

    Returns:
        The new run.

    Raises:
        DomainError: If there is nothing to resume.
    """
    run = pipeline.resume(project_id)
    return _detail(pipeline.progress(run.id))
