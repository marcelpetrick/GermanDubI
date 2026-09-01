from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from germandubi.composition import Application, build_application
from germandubi.config import Settings
from germandubi.domain.entities.pipeline import JobStatus, Stage
from germandubi.domain.entities.project import ProjectState, QualityProfile, SourceKind, SourceMedia
from germandubi.domain.entities.segment import SpeechSegment, TextOrigin
from germandubi.domain.errors import DomainError, NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.domain.value_objects.timeline import TimeInterval


@pytest.fixture
def application(tmp_path: Path) -> Iterator[Application]:
    app = build_application(Settings(data_dir=tmp_path / "data"))
    yield app
    app.dispose()


def create_segment(application: Application, *, translated: bool = False) -> SpeechSegment:
    project = application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")
    ready = replace(
        project,
        state=ProjectState.REVIEW,
        title="Ready",
        media=SourceMedia("Ready", 1000),
    )
    segment = SpeechSegment.create(
        project_id=project.id,
        ordinal=0,
        interval=TimeInterval(0, 1000),
        source_text="Hello",
        source_origin=TextOrigin.ASR,
    )
    if translated:
        segment = segment.with_translation("Hallo", origin=TextOrigin.MACHINE_TRANSLATION)
    with application.unit_of_work() as uow:
        uow.projects.save(ready)
        uow.segments.replace_all(project.id, [segment])
    return segment


def test_project_service_quality_busy_resolve_and_description(application: Application) -> None:
    project = application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")
    updated = application.projects.set_quality(project.id, QualityProfile.MAXIMUM)
    assert updated.quality is QualityProfile.MAXIMUM
    application.projects.request_analysis(project.id)
    with pytest.raises(DomainError, match="already probing"):
        application.projects.request_analysis(project.id)

    unknown = ProjectId(new_id())
    with pytest.raises(NotFoundError, match="no project"):
        application.projects.resolve(unknown)

    local = application.projects.create_from_file("/media/source.mp4")
    assert local.source.kind is SourceKind.LOCAL_FILE
    assert application.projects.describe_source(local) == "local file /media/source.mp4"
    assert application.projects.describe_source(updated) == updated.display_title


def test_pipeline_rejects_unanalysed_busy_and_empty_resume(application: Application) -> None:
    project = application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")
    with pytest.raises(DomainError, match="analyse"):
        application.pipeline.start(project.id)
    with pytest.raises(DomainError, match="never been processed"):
        application.pipeline.resume(project.id)

    application.projects.request_analysis(project.id)
    with pytest.raises(DomainError, match="already probing"):
        application.pipeline.start(project.id)


def test_pipeline_cancel_and_resume_unfinished_stages(application: Application) -> None:
    segment = create_segment(application)
    run = application.pipeline.start(segment.project_id, stages=(Stage.TRANSLATE, Stage.EXPORT))
    application.pipeline.cancel(run.id)
    cancelled = application.pipeline.progress(run.id)
    assert cancelled.finished
    assert all(job.status is JobStatus.CANCELLED for job in cancelled.jobs)
    assert application.projects.get(segment.project_id).state is ProjectState.CANCELLED

    resumed = application.pipeline.resume(segment.project_id)
    assert resumed.stages == (Stage.TRANSLATE, Stage.EXPORT)
    assert application.pipeline.latest_progress(segment.project_id) is not None


def test_segment_reset_retranslation_resynthesis_history_and_missing_speech(
    application: Application,
) -> None:
    untranslated = create_segment(application)
    with pytest.raises(DomainError, match="nothing to synthesize"):
        application.segments.mark_for_resynthesis(untranslated.id)
    assert application.segments.speech_path(untranslated.id) is None

    translated = application.segments.edit_translation(untranslated.id, "Hallo")[0]
    assert application.segments.translation_history(translated.id)
    with pytest.raises(DomainError, match="written by hand"):
        application.segments.mark_for_retranslation(translated.id)

    regenerated, stage = application.segments.mark_for_resynthesis(translated.id)
    assert regenerated.is_translated and stage is Stage.SYNTHESIZE
    reset, stage = application.segments.reset(translated.id)
    assert not reset.is_translated and stage is Stage.TRANSLATE


def test_approving_all_segments_completes_project(application: Application) -> None:
    segment = create_segment(application, translated=True)
    approved = application.segments.approve(segment.id)
    assert approved.review_state == "approved"
    assert application.projects.get(segment.project_id).state is ProjectState.COMPLETE


def test_a_failed_create_leaves_no_workspace_behind(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filesystem does not roll back with the transaction, so it is undone by hand.

    A create that failed after the workspace directory existed left it there with no row
    referring to it: invisible in the interface, and not removed by "delete everything".
    Three accumulated in one session when the database was briefly write-locked.
    """
    from germandubi.infrastructure.db.repositories import EventRepository

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "database is locked"
        raise RuntimeError(msg)

    monkeypatch.setattr(EventRepository, "append", refuse)

    before = sorted(application.settings.projects_dir.glob("*"))
    with pytest.raises(RuntimeError, match="database is locked"):
        application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")

    assert sorted(application.settings.projects_dir.glob("*")) == before
