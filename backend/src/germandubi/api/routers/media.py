"""Media preview, artifact listing and export download.

Media is served by the API rather than by handing out file paths, for two reasons: nothing
outside a project workspace can ever be reached, and the browser gets byte-range support so
seeking in a long video works.

Files are streamed in chunks. A twenty-minute video read into Python memory would be a
several-hundred-megabyte allocation per request.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse

from germandubi.api.dependencies import AppDep, ProjectIdDep, SegmentIdDep
from germandubi.api.schemas import ArtifactModel, ErrorResponse
from germandubi.composition import Application
from germandubi.domain.entities.artifact import Artifact, ArtifactKind
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId
from germandubi.infrastructure.artifacts.store import sanitize_filename

router = APIRouter(prefix="/projects/{project_id}", tags=["media"])

logger = logging.getLogger(__name__)

_RANGE = re.compile(r"bytes=(?P<start>\d*)-(?P<end>\d*)")
_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such project, segment or artifact."},
}
#: Media types the browser can play directly.
_FALLBACK_TYPE: Final = "application/octet-stream"


def _resolve(
    app: Application, project_id: ProjectId, kind: ArtifactKind, label: str
) -> tuple[Artifact, Path]:
    """Return an artifact and its verified path inside the project workspace.

    Raises:
        NotFoundError: If the artifact has not been produced, or its file has gone.
    """
    with app.unit_of_work() as uow:
        artifact = uow.artifacts.latest(project_id, kind)
        if artifact is None:
            msg = f"this project has no {label} yet"
            raise NotFoundError(msg, kind=kind.value)
        path = uow.store.path_for(artifact)
    if not path.exists():
        msg = f"the {label} file is missing from the project workspace"
        raise NotFoundError(msg, kind=kind.value)
    return artifact, path


def _serve(app: Application, artifact: Artifact, path: Path, range_header: str | None) -> Response:
    """Stream a file, honouring a byte-range request when one is made.

    Range support is what lets the browser seek in a long video instead of downloading it
    from the start every time the user drags the scrubber.
    """
    size = path.stat().st_size
    media_type = artifact.media_type or _FALLBACK_TYPE
    common = {
        "accept-ranges": "bytes",
        "content-disposition": f'inline; filename="{path.name}"',
    }

    match = _RANGE.fullmatch(range_header.strip()) if range_header else None
    if match is None:
        return StreamingResponse(
            app.store.stream(path),
            media_type=media_type,
            headers={**common, "content-length": str(size)},
        )

    start_text, end_text = match.group("start"), match.group("end")
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    else:
        # A suffix range, "bytes=-500", asks for the last N bytes.
        start = max(0, size - int(end_text or 0))
        end = size - 1
    end = min(end, size - 1)

    if start > end or start >= size:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"content-range": f"bytes */{size}"},
        )

    return StreamingResponse(
        app.store.stream(path, start=start, end=end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers={
            **common,
            "content-range": f"bytes {start}-{end}/{size}",
            "content-length": str(end - start + 1),
        },
    )


@router.get(
    "/preview/video",
    summary="Preview the source video",
    description="Streams the acquired source with byte-range support, so the player can seek.",
    responses=_ERRORS,
    operation_id="previewVideo",
)
async def preview_video(
    project_id: ProjectIdDep,
    app: AppDep,
    request: Request,
    range: str | None = Header(default=None),  # noqa: A002 - the HTTP header is named Range
) -> Response:
    """Stream the source video.

    Args:
        project_id: The project.
        app: The wired application.
        request: The incoming request.
        range: The HTTP ``Range`` header.

    Returns:
        The video stream.
    """
    del request
    artifact, path = _resolve(app, project_id, ArtifactKind.SOURCE_VIDEO, "source video")
    return _serve(app, artifact, path, range)


@router.get(
    "/preview/export",
    summary="Preview the German dub",
    description="Streams the exported German-dubbed file with byte-range support.",
    responses=_ERRORS,
    operation_id="previewExport",
)
async def preview_export(
    project_id: ProjectIdDep,
    app: AppDep,
    range: str | None = Header(default=None),  # noqa: A002
) -> Response:
    """Stream the exported dub.

    Args:
        project_id: The project.
        app: The wired application.
        range: The HTTP ``Range`` header.

    Returns:
        The export stream.
    """
    artifact, path = _resolve(app, project_id, ArtifactKind.EXPORT, "export")
    return _serve(app, artifact, path, range)


@router.get(
    "/preview/audio/{track}",
    summary="Preview an audio track",
    description="`german` is the mixed dub; `original` is the untouched source audio.",
    responses=_ERRORS,
    operation_id="previewAudio",
)
async def preview_audio(
    project_id: ProjectIdDep,
    track: str,
    app: AppDep,
    range: str | None = Header(default=None),  # noqa: A002
) -> Response:
    """Stream the German or the original audio track.

    Args:
        project_id: The project.
        track: ``german`` or ``original``.
        app: The wired application.
        range: The HTTP ``Range`` header.

    Returns:
        The audio stream.

    Raises:
        NotFoundError: If the track name is unknown or the audio has not been produced.
    """
    kinds = {
        "german": (ArtifactKind.MIXED_AUDIO, "German audio"),
        "original": (ArtifactKind.MASTER_AUDIO, "original audio"),
        "background": (ArtifactKind.BACKGROUND_STEM, "background stem"),
    }
    if track not in kinds:
        msg = f"unknown audio track {track!r}; expected one of: {', '.join(sorted(kinds))}"
        raise NotFoundError(msg, track=track)
    kind, label = kinds[track]
    artifact, path = _resolve(app, project_id, kind, label)
    return _serve(app, artifact, path, range)


@router.get(
    "/segments/{segment_id}/speech",
    summary="Preview a segment's German speech",
    description="The synthesized audio for one segment, for A/B comparison while reviewing.",
    responses=_ERRORS,
    operation_id="previewSegmentSpeech",
)
async def preview_segment_speech(
    project_id: ProjectIdDep, segment_id: SegmentIdDep, app: AppDep
) -> Response:
    """Stream one segment's German speech.

    Args:
        project_id: The owning project.
        segment_id: The segment.
        app: The wired application.

    Returns:
        The audio stream.

    Raises:
        NotFoundError: If the segment has no speech yet.
    """
    with app.unit_of_work() as uow:
        segment = uow.segments.get(segment_id)
        if segment.project_id != project_id:
            msg = f"no segment with id {segment_id} in this project"
            raise NotFoundError(msg, segment_id=str(segment_id))
        artifact_id = uow.segments.speech_artifact_id(segment_id)
        if artifact_id is None:
            msg = "no German speech has been generated for this segment yet"
            raise NotFoundError(msg, segment_id=str(segment_id))
        artifact = uow.artifacts.get(artifact_id)
        path = uow.store.path_for(artifact)

    if not path.exists():
        msg = "the speech file is missing from the project workspace"
        raise NotFoundError(msg, segment_id=str(segment_id))
    return _serve(app, artifact, path, None)


@router.get(
    "/artifacts",
    response_model=list[ArtifactModel],
    summary="List artifacts",
    description="Every current artifact, with the provenance that says how it was produced.",
    responses=_ERRORS,
    operation_id="listArtifacts",
)
async def list_artifacts(project_id: ProjectIdDep, app: AppDep) -> list[ArtifactModel]:
    """Return a project's current artifacts.

    Args:
        project_id: The project.
        app: The wired application.

    Returns:
        The artifacts, newest first.
    """
    with app.unit_of_work() as uow:
        artifacts = uow.artifacts.list_for_project(project_id)
    return [
        ArtifactModel(
            id=str(a.id),
            kind=str(a.kind),
            relative_path=a.relative_path,
            size_bytes=a.size_bytes,
            media_type=a.media_type,
            provider_id=a.provenance.provider_id if a.provenance else None,
            model_id=a.provenance.model_id if a.provenance else None,
            created_at=a.provenance.created_at if a.provenance else None,
        )
        for a in artifacts
    ]


@router.get(
    "/download",
    summary="Download the German dub",
    description="The exported file as an attachment, for saving to disk.",
    responses=_ERRORS,
    operation_id="downloadExport",
)
async def download_export(project_id: ProjectIdDep, app: AppDep) -> StreamingResponse:
    """Download the exported dub.

    Args:
        project_id: The project.
        app: The wired application.

    Returns:
        The file, as an attachment.

    Raises:
        NotFoundError: If nothing has been exported.
    """
    artifact, path = _resolve(app, project_id, ArtifactKind.EXPORT, "export")
    with app.unit_of_work() as uow:
        project = uow.projects.get(project_id)

    name = f"{sanitize_filename(project.display_title, fallback='german_dub')}.mkv"
    return StreamingResponse(
        app.store.stream(path),
        media_type=artifact.media_type or _FALLBACK_TYPE,
        headers={
            "content-disposition": f'attachment; filename="{name}"',
            "content-length": str(path.stat().st_size),
        },
    )
