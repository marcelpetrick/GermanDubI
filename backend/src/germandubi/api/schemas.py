"""Request and response models for the HTTP API.

These are deliberately separate from the domain entities. The wire format is a contract
with the browser and must be able to stay stable while the domain evolves; conflating the
two makes every domain refactor a breaking API change.

Every model here also feeds the generated TypeScript client, so field names and
descriptions are part of the developer experience, not decoration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from germandubi.domain.entities.pipeline import Job, PipelineRun, Stage
from germandubi.domain.entities.project import Project, QualityProfile, SourceMedia
from germandubi.domain.entities.segment import SpeechSegment

__all__ = [
    "CreateProjectRequest",
    "ErrorResponse",
    "MetaResponse",
    "ProjectDetail",
    "ProjectSummary",
    "RunDetail",
    "SegmentDetail",
    "SegmentListResponse",
    "UpdateSegmentRequest",
]


class ErrorResponse(BaseModel):
    """The single error shape every failing endpoint returns.

    One shape means the frontend has one error path rather than one per endpoint.
    """

    code: str = Field(description="Stable machine-readable identifier, e.g. `not_found`.")
    message: str = Field(description="Human-readable explanation, safe to show to the user.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Machine-readable context about the failure."
    )


class MetaResponse(BaseModel):
    """Build identity and capability report."""

    application: str = Field(description="Always `germandubi`.")
    version: str = Field(description="PEP 440 version, e.g. `0.6.0.dev17+g1a2b3c4`.")
    display_version: str = Field(description="Short form for the UI footer.")
    api_version: str = Field(description="HTTP API version, versioned independently.")
    git_revision: str | None = Field(description="Commit this build was made from.")
    dirty: bool = Field(description="Whether the build came from a modified working tree.")
    source_language: str = Field(description="Always `en` in 0.x.")
    target_language: str = Field(description="Always `de` in 0.x.")


class HealthResponse(BaseModel):
    """Liveness and dependency status."""

    status: Literal["ok", "degraded"] = Field(
        description="`degraded` when a required external tool is missing."
    )
    tools: dict[str, bool] = Field(description="External programs and whether each was found.")
    missing: list[str] = Field(description="Required tools that are absent.")
    data_dir: str = Field(description="Where project data is stored.")
    writable: bool = Field(description="Whether that directory can be written to.")


class ProviderStatus(BaseModel):
    """One provider and whether it can run."""

    id: str
    name: str
    kind: Literal["local", "network"] = Field(
        description="`network` means using it sends data off this machine."
    )
    model_id: str | None
    available: bool
    notes: str | None


class CaptionTrackModel(BaseModel):
    """A caption track the source advertises."""

    language: str
    automatic: bool = Field(
        description="Machine-generated captions are unpunctuated and usually produce worse German."
    )
    name: str | None = None


class SourceMediaModel(BaseModel):
    """What the probe learned about the source."""

    title: str
    duration_ms: int
    uploader: str | None = None
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    captions: list[CaptionTrackModel] = Field(default_factory=list)
    has_english_captions: bool = False
    best_captions_are_automatic: bool | None = None

    @classmethod
    def of(cls, media: SourceMedia) -> SourceMediaModel:
        """Build the wire model from the domain object.

        Args:
            media: The probe result.

        Returns:
            The serializable model.
        """
        best = media.best_english_caption
        return cls(
            title=media.title,
            duration_ms=media.duration_ms,
            uploader=media.uploader,
            thumbnail_url=media.thumbnail_url,
            width=media.width,
            height=media.height,
            video_codec=media.video_codec,
            audio_codec=media.audio_codec,
            captions=[
                CaptionTrackModel(language=str(c.language), automatic=c.automatic, name=c.name)
                for c in media.captions
            ],
            has_english_captions=best is not None,
            best_captions_are_automatic=best.automatic if best else None,
        )


class CreateProjectRequest(BaseModel):
    """Start a new dubbing project."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}]}
    )

    url: str | None = Field(
        default=None, description="A YouTube URL. Validated against an allowlist."
    )
    file_path: str | None = Field(
        default=None, description="Absolute path to a local media file, as an alternative to a URL."
    )
    quality: QualityProfile = Field(
        default=QualityProfile.BALANCED, description="The speed/quality trade-off."
    )
    voice: str | None = Field(
        default=None,
        description=(
            "The German narrator, from `GET /voices`. Omit to use the configured default."
        ),
    )


class ProjectSummary(BaseModel):
    """A project as it appears in the project list."""

    id: str
    title: str
    state: str
    source_kind: str
    source_locator: str
    duration_ms: int | None
    thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, project: Project) -> ProjectSummary:
        """Build the wire model from the domain object.

        Args:
            project: The project.

        Returns:
            The serializable model.
        """
        return cls(
            id=str(project.id),
            title=project.display_title,
            state=str(project.state),
            source_kind=str(project.source.kind),
            source_locator=project.source.locator,
            duration_ms=project.media.duration_ms if project.media else None,
            thumbnail_url=project.media.thumbnail_url if project.media else None,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectDetail(ProjectSummary):
    """A project with its probe results and error state."""

    source_language: str
    target_language: str
    quality: str
    error: str | None
    media: SourceMediaModel | None

    @classmethod
    def of(cls, project: Project) -> ProjectDetail:
        """Build the wire model from the domain object.

        Args:
            project: The project.

        Returns:
            The serializable model.
        """
        summary = ProjectSummary.of(project)
        return cls(
            **summary.model_dump(),
            source_language=str(project.source_language),
            target_language=str(project.target_language),
            quality=str(project.quality),
            error=project.error,
            media=SourceMediaModel.of(project.media) if project.media else None,
        )


class JobDetail(BaseModel):
    """One pipeline stage's status, as shown on the processing screen."""

    stage: str
    label: str = Field(description="Human-readable stage name, e.g. `Translating to German`.")
    status: str
    progress: float = Field(ge=0.0, le=1.0)
    detail: str | None = Field(description="Short note, e.g. `124 / 192 segments`.")
    attempt: int
    error: str | None

    @classmethod
    def of(cls, job: Job) -> JobDetail:
        """Build the wire model from the domain object.

        Args:
            job: The job.

        Returns:
            The serializable model.
        """
        return cls(
            stage=str(job.stage),
            label=job.stage.label,
            status=str(job.status),
            progress=job.progress,
            detail=job.progress_detail,
            attempt=job.attempt,
            error=job.error,
        )


class RunDetail(BaseModel):
    """A pipeline run and every stage in it."""

    id: str
    project_id: str
    stages: list[str]
    jobs: list[JobDetail]
    progress: float = Field(ge=0.0, le=1.0)
    finished: bool
    failed: bool
    cancelled: bool
    current_stage: str | None
    created_at: datetime

    @classmethod
    def of(
        cls, run: PipelineRun, jobs: list[Job], *, progress: float, finished: bool, failed: bool
    ) -> RunDetail:
        """Build the wire model from the domain objects.

        Args:
            run: The run.
            jobs: Its jobs, in execution order.
            progress: Overall completion.
            finished: Whether every job reached a terminal status.
            failed: Whether a job failed with no retries left.

        Returns:
            The serializable model.
        """
        current = next((j for j in jobs if str(j.status) == "running"), None)
        return cls(
            id=str(run.id),
            project_id=str(run.project_id),
            stages=[str(s) for s in run.stages],
            jobs=[JobDetail.of(job) for job in jobs],
            progress=progress,
            finished=finished,
            failed=failed,
            cancelled=run.cancelled,
            current_stage=str(current.stage) if current else None,
            created_at=run.created_at,
        )


class StartRunRequest(BaseModel):
    """Start a full or partial pipeline run."""

    stages: list[Stage] | None = Field(
        default=None, description="Stages to run. Omit to run the whole pipeline."
    )


class DurationFitModel(BaseModel):
    """How well a segment's German speech fits its slot."""

    target_ms: int
    generated_ms: int
    ratio: float = Field(description="Generated divided by target; 1.0 is a perfect fit.")
    deviation: float = Field(description="Signed relative deviation; 0.14 means 14% too long.")
    applied_rate: float = Field(description="Time-scaling actually applied; 1.0 means untouched.")


class SegmentDetail(BaseModel):
    """One dubbing segment, as shown in the review editor."""

    id: str
    ordinal: int
    start_ms: int
    end_ms: int
    duration_ms: int
    source_text: str
    source_origin: str
    translation: str | None
    translation_origin: str | None
    status: str
    review_state: str
    flags: list[str]
    confidence: float | None
    fit: DurationFitModel | None
    has_speech: bool
    word_count: int

    @classmethod
    def of(cls, segment: SpeechSegment, *, has_speech: bool = False) -> SegmentDetail:
        """Build the wire model from the domain object.

        Args:
            segment: The segment.
            has_speech: Whether German speech has been generated for it.

        Returns:
            The serializable model.
        """
        return cls(
            id=str(segment.id),
            ordinal=segment.ordinal,
            start_ms=segment.interval.start_ms,
            end_ms=segment.interval.end_ms,
            duration_ms=segment.duration_ms,
            source_text=segment.source_text,
            source_origin=str(segment.source_origin),
            translation=segment.translation,
            translation_origin=str(segment.translation_origin)
            if segment.translation_origin
            else None,
            status=str(segment.status),
            review_state=str(segment.review_state),
            flags=sorted(segment.flags),
            confidence=segment.confidence,
            fit=(
                DurationFitModel(
                    target_ms=segment.fit.target_ms,
                    generated_ms=segment.fit.generated_ms,
                    ratio=round(segment.fit.ratio, 4),
                    deviation=round(segment.fit.deviation, 4),
                    applied_rate=round(segment.fit.applied_rate, 4),
                )
                if segment.fit
                else None
            ),
            has_speech=has_speech,
            word_count=segment.word_count,
        )


class SegmentSummaryModel(BaseModel):
    """Aggregate counts shown above the segment table."""

    total: int
    translated: int
    synthesized: int
    approved: int
    flagged: int
    failed: int


class SegmentListResponse(BaseModel):
    """A project's segments plus their aggregate counts."""

    segments: list[SegmentDetail]
    summary: SegmentSummaryModel


class UpdateSegmentRequest(BaseModel):
    """Correct a segment's English or German text."""

    source_text: Annotated[str | None, Field(min_length=1)] = Field(
        default=None, description="Corrected English text. Invalidates the German downstream."
    )
    translation: Annotated[str | None, Field(min_length=1)] = Field(
        default=None, description="Corrected German text. Invalidates only the speech."
    )


class SegmentUpdatedResponse(BaseModel):
    """The updated segment and what became stale because of the edit."""

    segment: SegmentDetail
    invalidated_from: str = Field(
        description="The earliest stage that must be re-run for this change to take effect."
    )
    run_id: str | None = Field(
        default=None, description="The regeneration run, when one was started automatically."
    )


class TranslationRevisionModel(BaseModel):
    """One historical German rendering of a segment."""

    revision: int
    text: str
    origin: str


class ArtifactModel(BaseModel):
    """A file the pipeline produced."""

    id: str
    kind: str
    relative_path: str
    size_bytes: int | None
    media_type: str | None
    provider_id: str | None
    model_id: str | None
    created_at: datetime | None


class VoiceStatus(BaseModel):
    """One German narrator a project can use."""

    id: str = Field(description="The Piper voice identifier, e.g. `de_DE-thorsten-medium`.")
    speaker: str = Field(description="Readable speaker name, e.g. `Thorsten`.")
    quality: str = Field(description="Model quality tier: `low`, `medium`, `high` or similar.")
    downloaded: bool = Field(
        description="Whether the model is already on this machine. If not, first use fetches it."
    )
