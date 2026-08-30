"""Quality checks and export.

QA runs before export deliberately. Every check here is a deterministic, measurable property
of the artifacts - not a judgement about whether the German sounds good - so it can fail
loudly and point at the specific segment responsible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import pairwise

from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.project import ProjectState
from germandubi.domain.entities.segment import SegmentStatus, SpeechSegment
from germandubi.domain.errors import ExportError
from germandubi.domain.value_objects.content_hash import hash_inputs
from germandubi.worker.context import StageContext

__all__ = ["QualityFinding", "handle_export", "handle_qa"]

logger = logging.getLogger(__name__)

#: How far the exported media may differ from the source before it is a real problem.
_DURATION_TOLERANCE_MS = 1_500


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One thing worth telling the user before they export.

    Attributes:
        code: Stable machine-readable identifier.
        severity: ``warning`` or ``error``. An error blocks a confident export.
        message: What is wrong, in the user's terms.
        segment_ordinal: The segment responsible, when one is.
    """

    code: str
    severity: str
    message: str
    segment_ordinal: int | None = None


def handle_qa(context: StageContext) -> None:
    """Check the produced artifacts for measurable problems.

    Args:
        context: The stage context.
    """
    segments = context.uow.segments.list_for_project(context.project.id)
    findings: list[QualityFinding] = []

    findings += _check_untranslated(segments)
    findings += _check_failed(segments)
    findings += _check_overruns(segments)
    findings += _check_ordering(segments)
    findings += _check_audio(context)

    errors = [f for f in findings if f.severity == "error"]
    context.event(
        "qa_complete",
        {
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "segment": f.segment_ordinal,
                }
                for f in findings
            ],
            "errors": len(errors),
        },
    )
    detail = "no problems found" if not findings else f"{len(findings)} findings"
    context.progress(1.0, detail)
    logger.info("quality checks: %d findings, %d errors", len(findings), len(errors))


def _check_untranslated(segments: list[SpeechSegment]) -> list[QualityFinding]:
    """Report segments that never received German text."""
    missing = [s for s in segments if not s.is_translated]
    if not missing:
        return []
    return [
        QualityFinding(
            code="untranslated_segments",
            severity="error",
            message=(
                f"{len(missing)} of {len(segments)} segments have no German text. "
                f"They will be silent in the export."
            ),
        )
    ]


def _check_failed(segments: list[SpeechSegment]) -> list[QualityFinding]:
    """Report segments whose speech could not be generated."""
    return [
        QualityFinding(
            code="synthesis_failed",
            severity="error",
            message=f"segment {s.ordinal} could not be synthesized and will be silent",
            segment_ordinal=s.ordinal,
        )
        for s in segments
        if s.status is SegmentStatus.FAILED
    ]


def _check_overruns(segments: list[SpeechSegment]) -> list[QualityFinding]:
    """Report segments whose German speech is materially longer than its slot."""
    overrunning = [s for s in segments if s.fit and s.fit.deviation > 0.15]
    if not overrunning:
        return []
    worst = max(overrunning, key=lambda s: s.fit.deviation if s.fit else 0.0)
    return [
        QualityFinding(
            code="duration_overrun",
            severity="warning",
            message=(
                f"{len(overrunning)} segments have German speech noticeably longer than "
                f"the original, the worst by "
                f"{(worst.fit.deviation * 100 if worst.fit else 0):.0f}%. "
                f"Shorten the German text on those segments for a tighter result."
            ),
            segment_ordinal=worst.ordinal,
        )
    ]


def _check_ordering(segments: list[SpeechSegment]) -> list[QualityFinding]:
    """Report overlapping segments, which would make two German lines play at once."""
    return [
        QualityFinding(
            code="segments_overlap",
            severity="error",
            message=f"segments {earlier.ordinal} and {later.ordinal} overlap in time",
            segment_ordinal=earlier.ordinal,
        )
        for earlier, later in pairwise(segments)
        if earlier.interval.end_ms > later.interval.start_ms
    ]


def _check_audio(context: StageContext) -> list[QualityFinding]:
    """Check that the mixed audio exists and matches the source duration."""
    mixed = context.latest(ArtifactKind.MIXED_AUDIO)
    if mixed is None:
        return [
            QualityFinding(
                code="no_mixed_audio",
                severity="error",
                message="no German audio track was produced",
            )
        ]
    media = context.registry.media()
    mixed_ms = media.probe(context.uow.store.path_for(mixed)).duration_ms
    source_ms = media.probe(context.require(ArtifactKind.MASTER_AUDIO)).duration_ms
    if abs(mixed_ms - source_ms) > _DURATION_TOLERANCE_MS:
        return [
            QualityFinding(
                code="duration_mismatch",
                severity="warning",
                message=(
                    f"the German audio is {abs(mixed_ms - source_ms) / 1000:.1f}s "
                    f"{'longer' if mixed_ms > source_ms else 'shorter'} than the original, "
                    f"so it may drift out of sync"
                ),
            )
        ]
    return []


def handle_export(context: StageContext) -> None:
    """Mux the German dub into its final container.

    Args:
        context: The stage context.

    Raises:
        ExportError: If muxing fails or the required inputs are missing.
    """
    media = context.registry.media()
    source = context.require(ArtifactKind.SOURCE_VIDEO)
    german_audio = context.require(ArtifactKind.MIXED_AUDIO)
    master = context.require(ArtifactKind.MASTER_AUDIO)

    subtitles = {}
    for language, kind in (("de", ArtifactKind.SUBTITLES_DE), ("en", ArtifactKind.SUBTITLES_EN)):
        artifact = context.latest(kind)
        if artifact is not None:
            subtitles[language] = context.uow.store.path_for(artifact)

    if not media.probe(source).has_video:
        msg = "the source has no video stream, so there is nothing to export"
        raise ExportError(msg)

    destination = context.directory("exports") / "german_dub.mkv"
    context.progress(0.3, "muxing the German dub")
    context.checkpoint()
    media.mux(
        video_source=source,
        german_audio=german_audio,
        destination=destination,
        original_audio=master,
        subtitles=subtitles,
    )

    artifact = context.publish(
        ArtifactKind.EXPORT,
        destination,
        provider_id="ffmpeg",
        input_hash=hash_inputs(
            audio=german_audio.name, subtitles=sorted(subtitles), container="mkv"
        ),
        parameters={"container": "mkv", "subtitles": ",".join(sorted(subtitles))},
        media_type="video/x-matroska",
    )

    project = context.uow.projects.get(context.project.id)
    if project.state is ProjectState.PROCESSING:
        context.uow.projects.save(project.transition_to(ProjectState.REVIEW))

    size_mb = (artifact.size_bytes or 0) // (1024 * 1024)
    context.event(
        "export_ready",
        {"path": artifact.relative_path, "size_bytes": artifact.size_bytes},
    )
    context.progress(1.0, f"{destination.name} ({size_mb} MB)")
    logger.info("exported %s (%d MB)", destination.name, size_mb)
