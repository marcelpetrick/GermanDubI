"""FastAPI dependency wiring.

This is the API's half of the composition root. It builds the application once at startup
and hands services to routers, so a router never constructs infrastructure itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from germandubi.application.services.pipeline import PipelineService
from germandubi.application.services.projects import ProjectService
from germandubi.application.services.segments import SegmentService
from germandubi.composition import Application
from germandubi.domain.value_objects.identifiers import ProjectId, RunId, SegmentId, Ulid

__all__ = [
    "AppDep",
    "PipelineDep",
    "ProjectsDep",
    "SegmentsDep",
    "parse_project_id",
    "parse_run_id",
    "parse_segment_id",
]


def get_application(request: Request) -> Application:
    """Return the application built at startup.

    Args:
        request: The incoming request.

    Returns:
        The wired application.
    """
    application: Application = request.app.state.application
    return application


AppDep = Annotated[Application, Depends(get_application)]


def get_projects(app: AppDep) -> ProjectService:
    """Return the project service."""
    return app.projects


def get_pipeline(app: AppDep) -> PipelineService:
    """Return the pipeline service."""
    return app.pipeline


def get_segments(app: AppDep) -> SegmentService:
    """Return the segment service."""
    return app.segments


ProjectsDep = Annotated[ProjectService, Depends(get_projects)]
PipelineDep = Annotated[PipelineService, Depends(get_pipeline)]
SegmentsDep = Annotated[SegmentService, Depends(get_segments)]


def _parse(raw: str, label: str) -> Ulid:
    """Parse an identifier from the path, rejecting malformed input as 404.

    A malformed identifier cannot name an existing resource, so 404 is both correct and
    avoids leaking whether a well-formed identifier exists.

    Args:
        raw: The path segment.
        label: What the identifier names, for the error message.

    Returns:
        The parsed identifier.

    Raises:
        HTTPException: With status 404 if the identifier is malformed.
    """
    try:
        return Ulid(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"no {label} with id {raw!r}", "details": {}},
        ) from exc


def parse_project_id(project_id: str) -> ProjectId:
    """Parse a project identifier from the path."""
    return ProjectId(_parse(project_id, "project"))


def parse_run_id(run_id: str) -> RunId:
    """Parse a run identifier from the path."""
    return RunId(_parse(run_id, "run"))


def parse_segment_id(segment_id: str) -> SegmentId:
    """Parse a segment identifier from the path."""
    return SegmentId(_parse(segment_id, "segment"))


ProjectIdDep = Annotated[ProjectId, Depends(parse_project_id)]
RunIdDep = Annotated[RunId, Depends(parse_run_id)]
SegmentIdDep = Annotated[SegmentId, Depends(parse_segment_id)]
