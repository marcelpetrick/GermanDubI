"""Segment review and correction endpoints.

These are the endpoints the review editor lives on. Every mutation reports what became
stale, and optionally starts the minimal regeneration run itself, so the browser never has
to reason about the invalidation graph.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from germandubi.api.dependencies import (
    PipelineDep,
    ProjectIdDep,
    SegmentIdDep,
    SegmentsDep,
)
from germandubi.api.schemas import (
    ErrorResponse,
    SegmentDetail,
    SegmentListResponse,
    SegmentSummaryModel,
    SegmentUpdatedResponse,
    TranslationRevisionModel,
    UpdateSegmentRequest,
)
from germandubi.application.services.pipeline import PipelineService
from germandubi.application.services.segments import SegmentService
from germandubi.domain.entities.pipeline import Stage
from germandubi.domain.entities.segment import SpeechSegment
from germandubi.domain.errors import DomainError, NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId, SegmentId

router = APIRouter(prefix="/projects/{project_id}/segments", tags=["segments"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project or segment."},
    409: {"model": ErrorResponse, "description": "The edit is not allowed in this state."},
    422: {"model": ErrorResponse, "description": "The request was not acceptable."},
}


def _with_speech(segments: SegmentService, segment: SpeechSegment) -> SegmentDetail:
    """Render a segment, including whether German speech exists for it."""
    return SegmentDetail.of(segment, has_speech=segments.speech_path(segment.id) is not None)


def _respond(
    segments: SegmentService,
    pipeline: PipelineService,
    project_id: ProjectId,
    segment: SpeechSegment,
    stage: Stage,
    *,
    regenerate: bool,
) -> SegmentUpdatedResponse:
    """Return the updated segment and, optionally, the regeneration run just started."""
    run_id = None
    if regenerate:
        run_id = str(pipeline.regenerate(project_id, changed=stage).id)
    return SegmentUpdatedResponse(
        segment=_with_speech(segments, segment),
        invalidated_from=str(stage),
        run_id=run_id,
    )


@router.get(
    "",
    response_model=SegmentListResponse,
    summary="List segments",
    description="Every dubbing segment in timeline order, plus aggregate review counts.",
    responses=_ERRORS,
    operation_id="listSegments",
)
async def list_segments(project_id: ProjectIdDep, segments: SegmentsDep) -> SegmentListResponse:
    """Return a project's segments and their summary.

    Args:
        project_id: The project.
        segments: The segment service.

    Returns:
        The segments and aggregate counts.
    """
    items = segments.list_for_project(project_id)
    with_speech = {segment.id for segment in items if segments.speech_path(segment.id) is not None}
    summary = segments.summary(project_id)
    return SegmentListResponse(
        segments=[
            SegmentDetail.of(segment, has_speech=segment.id in with_speech) for segment in items
        ],
        summary=SegmentSummaryModel(
            total=summary.total,
            translated=summary.translated,
            synthesized=summary.synthesized,
            approved=summary.approved,
            flagged=summary.flagged,
            failed=summary.failed,
        ),
    )


@router.get(
    "/{segment_id}",
    response_model=SegmentDetail,
    summary="Get a segment",
    responses=_ERRORS,
    operation_id="getSegment",
)
async def get_segment(
    project_id: ProjectIdDep, segment_id: SegmentIdDep, segments: SegmentsDep
) -> SegmentDetail:
    """Return one segment.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.

    Returns:
        The segment.

    Raises:
        NotFoundError: If it does not exist or belongs to another project.
    """
    segment = segments.get(segment_id)
    _require_owner(segment, project_id, segment_id)
    return _with_speech(segments, segment)


@router.patch(
    "/{segment_id}",
    response_model=SegmentUpdatedResponse,
    summary="Correct a segment",
    description=(
        "Corrects the English or the German text. Correcting English invalidates the "
        "translation and everything after it; correcting German invalidates only the "
        "speech. The response names the earliest stage that must be re-run. Set "
        "`regenerate=true` to start that minimal run immediately."
    ),
    responses=_ERRORS,
    operation_id="updateSegment",
)
async def update_segment(
    project_id: ProjectIdDep,
    segment_id: SegmentIdDep,
    payload: UpdateSegmentRequest,
    segments: SegmentsDep,
    pipeline: PipelineDep,
    regenerate: bool = Query(
        default=False, description="Start the minimal regeneration run immediately."
    ),
) -> SegmentUpdatedResponse:
    """Correct a segment's English or German text.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        payload: The corrected text.
        segments: The segment service.
        pipeline: The pipeline service.
        regenerate: Whether to queue the regeneration run.

    Returns:
        The updated segment and what became stale.

    Raises:
        DomainError: If neither field was supplied, or both were.
        NotFoundError: If the segment does not exist.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    if bool(payload.source_text) == bool(payload.translation):
        msg = "correct either the English text or the German text, not both at once"
        raise DomainError(msg)

    if payload.source_text:
        segment, stage = segments.edit_source_text(segment_id, payload.source_text)
    else:
        segment, stage = segments.edit_translation(segment_id, payload.translation or "")
    return _respond(segments, pipeline, project_id, segment, stage, regenerate=regenerate)


@router.post(
    "/{segment_id}/retranslate",
    response_model=SegmentUpdatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Translate this segment again",
    description=(
        "Discards a machine translation so the next run produces a new one. Refused when "
        "the German text was written by hand, so a correction is never thrown away."
    ),
    responses=_ERRORS,
    operation_id="retranslateSegment",
)
async def retranslate_segment(
    project_id: ProjectIdDep,
    segment_id: SegmentIdDep,
    segments: SegmentsDep,
    pipeline: PipelineDep,
    regenerate: bool = Query(default=True),
) -> SegmentUpdatedResponse:
    """Queue a fresh translation for one segment.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.
        pipeline: The pipeline service.
        regenerate: Whether to start the run immediately.

    Returns:
        The updated segment and what became stale.

    Raises:
        DomainError: If the segment carries a hand-written translation.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    segment, stage = segments.mark_for_retranslation(segment_id)
    return _respond(segments, pipeline, project_id, segment, stage, regenerate=regenerate)


@router.post(
    "/{segment_id}/resynthesize",
    response_model=SegmentUpdatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate this segment's speech again",
    description="Keeps the German text and regenerates only its audio.",
    responses=_ERRORS,
    operation_id="resynthesizeSegment",
)
async def resynthesize_segment(
    project_id: ProjectIdDep,
    segment_id: SegmentIdDep,
    segments: SegmentsDep,
    pipeline: PipelineDep,
    regenerate: bool = Query(default=True),
) -> SegmentUpdatedResponse:
    """Queue fresh German speech for one segment.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.
        pipeline: The pipeline service.
        regenerate: Whether to start the run immediately.

    Returns:
        The updated segment and what became stale.

    Raises:
        DomainError: If the segment has no German text yet.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    segment, stage = segments.mark_for_resynthesis(segment_id)
    return _respond(segments, pipeline, project_id, segment, stage, regenerate=regenerate)


@router.post(
    "/{segment_id}/approve",
    response_model=SegmentDetail,
    summary="Approve a segment",
    responses=_ERRORS,
    operation_id="approveSegment",
)
async def approve_segment(
    project_id: ProjectIdDep, segment_id: SegmentIdDep, segments: SegmentsDep
) -> SegmentDetail:
    """Mark a segment as reviewed and accepted.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.

    Returns:
        The updated segment.

    Raises:
        DomainError: If the segment has no German text.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    return _with_speech(segments, segments.approve(segment_id))


@router.post(
    "/{segment_id}/reset",
    response_model=SegmentUpdatedResponse,
    summary="Discard this segment's German output",
    description="Keeps the English text, including a correction to it, and clears the rest.",
    responses=_ERRORS,
    operation_id="resetSegment",
)
async def reset_segment(
    project_id: ProjectIdDep,
    segment_id: SegmentIdDep,
    segments: SegmentsDep,
    pipeline: PipelineDep,
    regenerate: bool = Query(default=False),
) -> SegmentUpdatedResponse:
    """Discard a segment's generated German output.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.
        pipeline: The pipeline service.
        regenerate: Whether to start the run immediately.

    Returns:
        The updated segment and what became stale.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    segment, stage = segments.reset(segment_id)
    return _respond(segments, pipeline, project_id, segment, stage, regenerate=regenerate)


@router.get(
    "/{segment_id}/revisions",
    response_model=list[TranslationRevisionModel],
    summary="Translation history",
    description="Every German rendering this segment has had, oldest first.",
    responses=_ERRORS,
    operation_id="listSegmentRevisions",
)
async def list_revisions(
    project_id: ProjectIdDep, segment_id: SegmentIdDep, segments: SegmentsDep
) -> list[TranslationRevisionModel]:
    """Return a segment's translation history.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        segments: The segment service.

    Returns:
        The revisions, oldest first.
    """
    _require_owner(segments.get(segment_id), project_id, segment_id)
    return [
        TranslationRevisionModel(revision=revision, text=text, origin=origin)
        for revision, text, origin in segments.translation_history(segment_id)
    ]


def _require_owner(segment: SpeechSegment, project_id: ProjectId, segment_id: SegmentId) -> None:
    """Refuse a segment that belongs to a different project.

    Without this, a valid segment id from one project would be readable and editable
    through another project's URL.

    Raises:
        NotFoundError: If the segment belongs to another project.
    """
    if segment.project_id != project_id:
        msg = f"no segment with id {segment_id} in this project"
        raise NotFoundError(msg, segment_id=str(segment_id))
