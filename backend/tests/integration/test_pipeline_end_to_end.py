"""The whole pipeline, end to end, on deterministic fakes and real FFmpeg.

This is the test that proves the product works: create a project, run every stage, get a
playable German-dubbed file with two audio tracks and subtitles - then correct a segment and
watch only the affected work be redone.

No GPU, no network, no large model. FFmpeg is real, because the media assertions are the
point.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest

from germandubi.composition import Application, build_application
from germandubi.config import Settings
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.pipeline import JobStatus, Stage
from germandubi.domain.entities.project import ProjectState
from germandubi.domain.entities.segment import SegmentStatus
from germandubi.domain.errors import DomainError
from germandubi.domain.value_objects.identifiers import ProjectId
from germandubi.infrastructure.media.ffmpeg import FFmpegToolkit
from germandubi.infrastructure.processes.runner import ProcessRunner
from tests.fixtures.media import make_narration_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 15-second video, generated once for the whole module."""
    return make_narration_video(tmp_path_factory.mktemp("fixture") / "clip.mp4", seconds=15)


@pytest.fixture
def app(tmp_path: Path, clip: Path) -> Iterator[Application]:
    """An application wired entirely to deterministic fake providers."""
    settings = Settings(
        data_dir=tmp_path / "data",
        transcription_provider="fake",
        translation_provider="fake",
        tts_provider="fake",
        separation_provider="fake",
        job_lease_seconds=300,
    )
    application = build_application(settings, fixture=clip)
    yield application
    application.dispose()


def run_full_pipeline(app: Application) -> ProjectId:
    """Create a project, analyse it and take it all the way through export.

    Returns:
        The finished project's identity.
    """
    project = app.projects.create_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    app.projects.request_analysis(project.id)
    worker = app.worker()
    worker.run_until_idle()
    app.pipeline.start(project.id)
    worker.run_until_idle()
    return project.id


class TestFullRun:
    @pytest.fixture
    def finished(self, app: Application) -> ProjectId:
        return run_full_pipeline(app)

    def test_the_project_reaches_review(self, app: Application, finished: ProjectId) -> None:
        assert app.projects.get(finished).state is ProjectState.REVIEW

    def test_every_stage_succeeded(self, app: Application, finished: ProjectId) -> None:
        progress = app.pipeline.latest_progress(finished)
        assert progress is not None
        failures = [j for j in progress.jobs if j.status is not JobStatus.SUCCEEDED]
        assert not failures, [f"{j.stage}: {j.error}" for j in failures]
        assert progress.fraction == 1.0

    def test_segments_were_created_translated_and_synthesized(
        self, app: Application, finished: ProjectId
    ) -> None:
        segments = app.segments.list_for_project(finished)
        assert segments
        assert all(s.is_translated for s in segments)
        assert all(s.status is SegmentStatus.FITTED for s in segments)
        assert all(s.fit is not None for s in segments)

    def test_the_german_text_differs_from_the_english(
        self, app: Application, finished: ProjectId
    ) -> None:
        for segment in app.segments.list_for_project(finished):
            assert segment.translation != segment.source_text

    def test_segments_are_ordered_and_do_not_overlap(
        self, app: Application, finished: ProjectId
    ) -> None:
        segments = app.segments.list_for_project(finished)
        for earlier, later in pairwise(segments):
            assert earlier.interval.end_ms <= later.interval.start_ms

    def test_the_export_is_a_playable_file_with_both_audio_tracks(
        self, app: Application, finished: ProjectId
    ) -> None:
        with app.unit_of_work() as uow:
            export = uow.artifacts.latest(finished, ArtifactKind.EXPORT)
            assert export is not None
            path = uow.store.path_for(export)

        assert path.exists()
        toolkit = FFmpegToolkit(ProcessRunner(default_timeout_s=120))
        info = toolkit.probe(path)
        assert info.has_video
        assert info.duration_ms > 0

        streams = toolkit.runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv",
                str(path),
            ]
        ).stdout
        assert streams.count("audio") == 2, "German dub plus the original audio"
        assert "subtitle" in streams

    def test_the_export_matches_the_source_duration(
        self, app: Application, finished: ProjectId
    ) -> None:
        """A dub that drifts from the video is worse than no dub."""
        toolkit = FFmpegToolkit(ProcessRunner(default_timeout_s=120))
        with app.unit_of_work() as uow:
            export = uow.artifacts.latest(finished, ArtifactKind.EXPORT)
            master = uow.artifacts.latest(finished, ArtifactKind.MASTER_AUDIO)
            assert export is not None and master is not None
            exported = toolkit.probe(uow.store.path_for(export)).duration_ms
            original = toolkit.probe(uow.store.path_for(master)).duration_ms
        assert exported == pytest.approx(original, abs=1500)

    def test_subtitles_were_written_in_both_languages(
        self, app: Application, finished: ProjectId
    ) -> None:
        with app.unit_of_work() as uow:
            german = uow.artifacts.latest(finished, ArtifactKind.SUBTITLES_DE)
            english = uow.artifacts.latest(finished, ArtifactKind.SUBTITLES_EN)
            assert german is not None and english is not None
            content = uow.store.read_text(german)
        assert "-->" in content

    def test_every_generated_artifact_records_its_provenance(
        self, app: Application, finished: ProjectId
    ) -> None:
        """Reproducibility is not optional: an artifact with no provenance is untraceable."""
        with app.unit_of_work() as uow:
            artifacts = uow.artifacts.list_for_project(finished)
        assert artifacts
        for artifact in artifacts:
            assert artifact.provenance is not None, artifact.kind
            assert artifact.provenance.provider_id
            assert artifact.provenance.input_hash
            assert artifact.provenance.app_version
            assert artifact.content_hash

    def test_progress_events_were_recorded_for_the_browser(
        self, app: Application, finished: ProjectId
    ) -> None:
        with app.unit_of_work() as uow:
            events = uow.events.since(finished, after=0, limit=1000)
        kinds = {kind for _, kind, _ in events}
        assert {"stage_started", "stage_finished", "run_finished", "export_ready"} <= kinds
        sequences = [sequence for sequence, _, _ in events]
        assert sequences == sorted(sequences)


class TestPartialRegeneration:
    """Correcting one segment must redo only the work that depends on it."""

    @pytest.fixture
    def finished(self, app: Application) -> ProjectId:
        return run_full_pipeline(app)

    def test_editing_german_text_only_re_runs_from_synthesis(
        self, app: Application, finished: ProjectId
    ) -> None:
        segment = app.segments.list_for_project(finished)[0]
        _updated, stage = app.segments.edit_translation(segment.id, "Ein vollstaendig neuer Satz.")
        assert stage is Stage.SYNTHESIZE

        run = app.pipeline.regenerate(finished, changed=stage)
        assert Stage.ACQUIRE not in run.stages, "acquisition must not be repeated"
        assert Stage.TRANSCRIBE not in run.stages, "transcription must not be repeated"
        assert Stage.TRANSLATE not in run.stages, "the human edit must not be overwritten"
        assert Stage.EXPORT in run.stages

        app.worker().run_until_idle()
        assert app.segments.get(segment.id).translation == "Ein vollstaendig neuer Satz."

    def test_editing_english_text_re_runs_from_translation(
        self, app: Application, finished: ProjectId
    ) -> None:
        segment = app.segments.list_for_project(finished)[0]
        _, stage = app.segments.edit_source_text(segment.id, "A completely different sentence.")
        assert stage is Stage.TRANSLATE

        run = app.pipeline.regenerate(finished, changed=stage)
        assert Stage.TRANSLATE in run.stages
        assert Stage.ACQUIRE not in run.stages
        assert Stage.SEGMENT not in run.stages

        app.worker().run_until_idle()
        refreshed = app.segments.get(segment.id)
        assert refreshed.source_text == "A completely different sentence."
        assert refreshed.is_translated

    def test_a_human_translation_survives_a_full_re_run(
        self, app: Application, finished: ProjectId
    ) -> None:
        """The single most important guarantee of the review workflow."""
        segment = app.segments.list_for_project(finished)[0]
        app.segments.edit_translation(segment.id, "Von Hand geschrieben.")

        app.pipeline.start(finished)
        app.worker().run_until_idle()

        assert app.segments.get(segment.id).translation == "Von Hand geschrieben."

    def test_the_export_is_rebuilt_after_a_correction(
        self, app: Application, finished: ProjectId
    ) -> None:
        with app.unit_of_work() as uow:
            before = uow.artifacts.latest(finished, ArtifactKind.EXPORT)
            assert before is not None
            original_id = before.id

        segment = app.segments.list_for_project(finished)[0]
        _, stage = app.segments.edit_translation(segment.id, "Der korrigierte deutsche Satz.")
        app.pipeline.regenerate(finished, changed=stage)
        app.worker().run_until_idle()

        with app.unit_of_work() as uow:
            after = uow.artifacts.latest(finished, ArtifactKind.EXPORT)
            assert after is not None
            assert after.id != original_id
            assert uow.store.path_for(after).exists()

    def test_translation_revisions_are_kept(self, app: Application, finished: ProjectId) -> None:
        segment = app.segments.list_for_project(finished)[0]
        app.segments.edit_translation(segment.id, "Erste Korrektur.")
        app.segments.edit_translation(segment.id, "Zweite Korrektur.")

        history = app.segments.translation_history(segment.id)
        assert [text for _, text, _ in history][-1] == "Zweite Korrektur."
        assert "Erste Korrektur." in [text for _, text, _ in history]
        assert len(history) >= 3, "machine translation plus both corrections"


class TestResilience:
    def test_a_second_full_run_is_idempotent(self, app: Application) -> None:
        """Re-running everything must not duplicate segments or corrupt state."""
        project_id = run_full_pipeline(app)
        before = len(app.segments.list_for_project(project_id))

        app.pipeline.start(project_id)
        app.worker().run_until_idle()

        assert len(app.segments.list_for_project(project_id)) == before
        assert app.projects.get(project_id).state is ProjectState.REVIEW

    def test_cancelling_stops_the_run(self, app: Application) -> None:
        project = app.projects.create_from_url("https://youtu.be/dQw4w9WgXcQ")
        app.projects.request_analysis(project.id)
        app.worker().run_until_idle()

        run = app.pipeline.start(project.id)
        app.pipeline.cancel(run.id)
        executed = app.worker().run_until_idle()

        assert executed == 0
        assert app.projects.get(project.id).state is ProjectState.CANCELLED

    def test_a_cancelled_run_can_be_resumed(self, app: Application) -> None:
        project = app.projects.create_from_url("https://youtu.be/dQw4w9WgXcQ")
        app.projects.request_analysis(project.id)
        app.worker().run_until_idle()

        run = app.pipeline.start(project.id)
        app.pipeline.cancel(run.id)
        app.worker().run_until_idle()

        app.pipeline.resume(project.id)
        app.worker().run_until_idle()
        assert app.projects.get(project.id).state is ProjectState.REVIEW

    def test_starting_a_dub_before_analysis_is_refused(self, app: Application) -> None:
        project = app.projects.create_from_url("https://youtu.be/dQw4w9WgXcQ")
        with pytest.raises(DomainError, match="analyse the source"):
            app.pipeline.start(project.id)

    def test_deleting_a_project_removes_its_workspace(self, app: Application) -> None:
        project_id = run_full_pipeline(app)
        workspace = app.store.workspace(project_id)
        assert workspace.exists()

        app.projects.delete(project_id)
        assert not workspace.exists()
