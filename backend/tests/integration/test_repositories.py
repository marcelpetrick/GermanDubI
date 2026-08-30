"""Repositories: round-tripping domain objects through SQLite."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from germandubi.domain.entities.artifact import ArtifactKind, Provenance
from germandubi.domain.entities.pipeline import Job, JobStatus, PipelineRun, Stage
from germandubi.domain.entities.project import (
    CaptionTrack,
    Project,
    ProjectState,
    SourceMedia,
)
from germandubi.domain.entities.segment import SpeechSegment, TextOrigin, Word
from germandubi.domain.errors import NotFoundError
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.domain.value_objects.language import LanguageCode
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.artifacts.store import ArtifactStore
from germandubi.infrastructure.db.repositories import (
    ArtifactRepository,
    EventRepository,
    JobRepository,
    ProjectRepository,
    SegmentRepository,
)


@pytest.fixture
def projects(session: Session) -> ProjectRepository:
    return ProjectRepository(session)


@pytest.fixture
def segments(session: Session) -> SegmentRepository:
    return SegmentRepository(session)


@pytest.fixture
def jobs(session: Session) -> JobRepository:
    return JobRepository(session)


@pytest.fixture
def saved(projects: ProjectRepository, project: Project, session: Session) -> Project:
    projects.add(project, created_with="0.1.0.dev1")
    session.flush()
    return project


def make_segments(project_id: ProjectId, count: int = 3) -> list[SpeechSegment]:
    return [
        SpeechSegment.create(
            project_id=project_id,
            ordinal=index,
            interval=TimeInterval(index * 3000, index * 3000 + 2500),
            source_text=f"Sentence number {index}.",
            source_origin=TextOrigin.ASR,
            words=(Word(index * 3000, index * 3000 + 500, "Sentence"),),
        )
        for index in range(count)
    ]


class TestProjectRepository:
    def test_round_trips_a_project(self, projects: ProjectRepository, saved: Project) -> None:
        loaded = projects.get(saved.id)
        assert loaded.id == saved.id
        assert loaded.source.locator == saved.source.locator
        assert loaded.source.video_id == "dQw4w9WgXcQ"
        assert loaded.state is ProjectState.NEW

    def test_round_trips_probe_results_including_caption_tracks(
        self, projects: ProjectRepository, saved: Project, session: Session
    ) -> None:
        media = SourceMedia(
            title="A talk about timing",
            duration_ms=1_234_567,
            uploader="Someone",
            captions=(
                CaptionTrack(language=LanguageCode.ENGLISH, automatic=True, format="vtt"),
                CaptionTrack(language=LanguageCode.ENGLISH, automatic=False, name="English"),
            ),
        )
        projects.save(saved.transition_to(ProjectState.PROBING).with_probe_result(media))
        session.flush()

        loaded = projects.get(saved.id)
        assert loaded.media is not None
        assert loaded.media.duration_ms == 1_234_567
        assert len(loaded.media.captions) == 2
        best = loaded.media.best_english_caption
        assert best is not None and best.automatic is False
        assert loaded.title == "A talk about timing"

    def test_lists_projects_newest_first(
        self, projects: ProjectRepository, project: Project, session: Session
    ) -> None:
        from germandubi.domain.entities.project import SourceRef
        from germandubi.domain.value_objects.source_url import validate_source_url

        projects.add(project)
        later = Project.create(
            SourceRef.from_url(validate_source_url("https://youtu.be/aaaaaaaaaaa"))
        )
        projects.add(later)
        session.flush()
        assert next(p.id for p in projects.list_all()) == later.id
        assert projects.count() == 2

    def test_find_returns_none_for_an_unknown_project(self, projects: ProjectRepository) -> None:
        assert projects.find(ProjectId(new_id())) is None

    def test_get_raises_for_an_unknown_project(self, projects: ProjectRepository) -> None:
        with pytest.raises(NotFoundError, match="no project"):
            projects.get(ProjectId(new_id()))

    def test_deleting_a_project_removes_its_segments(
        self,
        projects: ProjectRepository,
        segments: SegmentRepository,
        saved: Project,
        session: Session,
    ) -> None:
        segments.replace_all(saved.id, make_segments(saved.id))
        session.flush()
        projects.delete(saved.id)
        session.flush()
        assert segments.list_for_project(saved.id) == []


class TestSegmentRepository:
    def test_round_trips_segments_with_word_timing(
        self, segments: SegmentRepository, saved: Project, session: Session
    ) -> None:
        segments.replace_all(saved.id, make_segments(saved.id))
        session.flush()

        loaded = segments.list_for_project(saved.id)
        assert [s.ordinal for s in loaded] == [0, 1, 2]
        assert loaded[0].interval == TimeInterval(0, 2500)
        assert loaded[0].words[0].text == "Sentence"

    def test_round_trips_a_translation_and_its_fit(
        self, segments: SegmentRepository, saved: Project, session: Session
    ) -> None:
        from germandubi.domain.entities.segment import DurationFit

        segments.replace_all(saved.id, make_segments(saved.id, count=1))
        session.flush()
        original = segments.list_for_project(saved.id)[0]

        translated = original.with_translation(
            "Satz Nummer null.", origin=TextOrigin.MACHINE_TRANSLATION
        ).with_fit(DurationFit(target_ms=2500, generated_ms=2800), flags=frozenset({"long"}))
        segments.save(translated)
        session.flush()

        loaded = segments.get(original.id)
        assert loaded.translation == "Satz Nummer null."
        assert loaded.fit is not None
        assert loaded.fit.generated_ms == 2800
        assert loaded.flags == frozenset({"long"})

    def test_replacing_segments_clears_the_previous_set(
        self, segments: SegmentRepository, saved: Project, session: Session
    ) -> None:
        """Ordinals are unique per project, so a stale row would collide."""
        segments.replace_all(saved.id, make_segments(saved.id, count=5))
        session.flush()
        segments.replace_all(saved.id, make_segments(saved.id, count=2))
        session.flush()
        assert len(segments.list_for_project(saved.id)) == 2

    def test_keeps_every_translation_revision(
        self, segments: SegmentRepository, saved: Project, session: Session
    ) -> None:
        segments.replace_all(saved.id, make_segments(saved.id, count=1))
        session.flush()
        segment = segments.list_for_project(saved.id)[0]

        assert (
            segments.add_translation_revision(
                segment.id, text="Maschine", origin=TextOrigin.MACHINE_TRANSLATION
            )
            == 1
        )
        assert (
            segments.add_translation_revision(
                segment.id, text="Gekuerzt", origin=TextOrigin.DURATION_ADJUSTED
            )
            == 2
        )
        assert (
            segments.add_translation_revision(
                segment.id, text="Mensch", origin=TextOrigin.USER_EDIT
            )
            == 3
        )
        session.flush()

        history = segments.translation_revisions(segment.id)
        assert [text for _, text, _ in history] == ["Maschine", "Gekuerzt", "Mensch"]
        assert history[-1][2] == TextOrigin.USER_EDIT.value

    def test_tracks_the_current_speech_artifact(
        self,
        segments: SegmentRepository,
        saved: Project,
        session: Session,
        artifact_store: ArtifactStore,
    ) -> None:
        segments.replace_all(saved.id, make_segments(saved.id, count=1))
        session.flush()
        segment = segments.list_for_project(saved.id)[0]

        artifact, path = artifact_store.allocate(
            saved.id, ArtifactKind.SEGMENT_SPEECH, "seg0.wav", segment_id=str(segment.id)
        )
        path.write_bytes(b"audio")
        segments.set_speech_artifact(segment.id, artifact.id)
        session.flush()
        assert segments.speech_artifact_id(segment.id) == artifact.id

        segments.set_speech_artifact(segment.id, None)
        session.flush()
        assert segments.speech_artifact_id(segment.id) is None


class TestArtifactRepository:
    def test_round_trips_an_artifact_with_provenance(
        self, session: Session, saved: Project, artifact_store: ArtifactStore
    ) -> None:
        repository = ArtifactRepository(session)
        artifact, path = artifact_store.allocate(saved.id, ArtifactKind.TRANSCRIPT, "t.json")
        path.write_text("{}")
        recorded = artifact_store.record(artifact)
        provenance = Provenance(
            app_version="0.1.0.dev1",
            provider_id="fake_asr",
            input_hash="sha256:abc",
            model_id="tiny",
            parameters={"language": "en"},
        )
        repository.add(replace(recorded, provenance=provenance))
        session.flush()

        loaded = repository.get(recorded.id)
        assert loaded.content_hash == recorded.content_hash
        assert loaded.size_bytes == 2
        assert loaded.provenance is not None
        assert loaded.provenance.provider_id == "fake_asr"
        assert loaded.provenance.model_id == "tiny"
        assert loaded.provenance.parameters == {"language": "en"}

    def test_latest_ignores_superseded_artifacts(
        self, session: Session, saved: Project, artifact_store: ArtifactStore
    ) -> None:
        repository = ArtifactRepository(session)
        for index in range(2):
            artifact, path = artifact_store.allocate(
                saved.id, ArtifactKind.MIXED_AUDIO, f"mix{index}.wav"
            )
            path.write_bytes(b"x")
            if index == 1:
                repository.supersede(saved.id, ArtifactKind.MIXED_AUDIO)
            repository.add(artifact_store.record(artifact))
            session.flush()

        latest = repository.latest(saved.id, ArtifactKind.MIXED_AUDIO)
        assert latest is not None
        assert latest.relative_path.endswith("mix1.wav")

    def test_superseded_artifacts_stay_on_disk(
        self, session: Session, saved: Project, artifact_store: ArtifactStore
    ) -> None:
        """Processing is non-destructive: a previous result stays available."""
        repository = ArtifactRepository(session)
        artifact, path = artifact_store.allocate(saved.id, ArtifactKind.MIXED_AUDIO, "old.wav")
        path.write_bytes(b"x")
        repository.add(artifact_store.record(artifact))
        session.flush()
        repository.supersede(saved.id, ArtifactKind.MIXED_AUDIO)
        session.flush()
        assert path.exists()
        assert repository.latest(saved.id, ArtifactKind.MIXED_AUDIO) is None

    def test_returns_none_when_a_stage_has_produced_nothing(
        self, session: Session, saved: Project
    ) -> None:
        assert ArtifactRepository(session).latest(saved.id, ArtifactKind.EXPORT) is None


class TestJobRepositoryClaiming:
    @pytest.fixture
    def run(self, jobs: JobRepository, saved: Project, session: Session) -> PipelineRun:
        created = PipelineRun.create(saved.id, stages=(Stage.PROBE, Stage.ACQUIRE, Stage.NORMALIZE))
        job_list = [
            Job.create(run_id=created.id, project_id=saved.id, stage=stage)
            for stage in created.stages
        ]
        jobs.add_run(created, job_list)
        session.flush()
        return created

    def test_claims_the_first_stage_with_no_dependencies(
        self, jobs: JobRepository, run: PipelineRun
    ) -> None:
        claimed = jobs.claim_next(lease_seconds=60)
        assert claimed is not None
        assert claimed.stage is Stage.PROBE
        assert claimed.status is JobStatus.RUNNING
        assert claimed.attempt == 1

    def test_does_not_claim_a_stage_whose_dependency_is_unfinished(
        self, jobs: JobRepository, run: PipelineRun
    ) -> None:
        jobs.claim_next(lease_seconds=60)
        assert jobs.claim_next(lease_seconds=60) is None

    def test_claims_the_next_stage_once_its_dependency_succeeds(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        first = jobs.claim_next(lease_seconds=60)
        assert first is not None
        jobs.save_job(first.transition_to(JobStatus.SUCCEEDED))
        session.flush()

        second = jobs.claim_next(lease_seconds=60)
        assert second is not None
        assert second.stage is Stage.ACQUIRE

    def test_reclaims_a_job_whose_lease_expired(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        """A worker killed mid-stage must not strand its job in RUNNING forever."""
        claimed = jobs.claim_next(lease_seconds=60)
        assert claimed is not None
        session.flush()

        later = datetime.now(UTC) + timedelta(seconds=120)
        reclaimed = jobs.claim_next(lease_seconds=60, now=later)
        assert reclaimed is not None
        assert reclaimed.stage is claimed.stage
        assert reclaimed.attempt == 2

    def test_does_not_reclaim_a_job_whose_lease_is_still_valid(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        assert jobs.claim_next(lease_seconds=600) is not None
        session.flush()
        assert jobs.claim_next(lease_seconds=600) is None

    def test_a_cancelled_run_yields_no_work(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        jobs.cancel_run(run.id)
        session.flush()
        assert jobs.claim_next(lease_seconds=60) is None
        assert jobs.is_cancelled(run.id)

    def test_cancelling_marks_running_jobs_for_cooperative_stop(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        claimed = jobs.claim_next(lease_seconds=600)
        assert claimed is not None
        session.flush()
        jobs.cancel_run(run.id)
        session.flush()
        assert jobs.get_job(claimed.id).status is JobStatus.CANCEL_REQUESTED

    def test_pending_count_reflects_progress(
        self, jobs: JobRepository, run: PipelineRun, session: Session
    ) -> None:
        assert jobs.pending_count(run.id) == 3
        claimed = jobs.claim_next(lease_seconds=60)
        assert claimed is not None
        jobs.save_job(claimed.transition_to(JobStatus.SUCCEEDED))
        session.flush()
        assert jobs.pending_count(run.id) == 2

    def test_latest_run_is_the_most_recent(
        self, jobs: JobRepository, run: PipelineRun, saved: Project, session: Session
    ) -> None:
        second = PipelineRun.create(saved.id, stages=(Stage.TRANSLATE,))
        jobs.add_run(
            second,
            [Job.create(run_id=second.id, project_id=saved.id, stage=Stage.TRANSLATE)],
        )
        session.flush()
        latest = jobs.latest_run(saved.id)
        assert latest is not None
        assert latest.id == second.id

    def test_a_partial_run_does_not_wait_for_stages_it_does_not_contain(
        self, jobs: JobRepository, saved: Project, session: Session
    ) -> None:
        """Regenerating one segment re-runs only some stages; the rest ran in an earlier run."""
        partial = PipelineRun.create(saved.id, stages=(Stage.TRANSLATE, Stage.SYNTHESIZE))
        jobs.add_run(
            partial,
            [
                Job.create(run_id=partial.id, project_id=saved.id, stage=stage)
                for stage in partial.stages
            ],
        )
        session.flush()
        claimed = jobs.claim_next(lease_seconds=60)
        assert claimed is not None
        assert claimed.stage is Stage.TRANSLATE


class TestEventRepository:
    def test_assigns_monotonic_sequence_numbers(self, session: Session, saved: Project) -> None:
        events = EventRepository(session)
        first = events.append(saved.id, "stage_started", {"stage": "probe"})
        second = events.append(saved.id, "stage_finished", {"stage": "probe"})
        assert second > first
        assert events.latest_sequence(saved.id) == second

    def test_replays_only_events_after_a_sequence_number(
        self, session: Session, saved: Project
    ) -> None:
        """This is what makes an SSE reconnect lossless rather than a gap."""
        events = EventRepository(session)
        events.append(saved.id, "a", {})
        cursor = events.append(saved.id, "b", {})
        events.append(saved.id, "c", {"n": 3})

        replayed = events.since(saved.id, after=cursor)
        assert [kind for _, kind, _ in replayed] == ["c"]
        assert replayed[0][2] == {"n": 3}

    def test_latest_sequence_is_zero_for_a_project_with_no_events(
        self, session: Session, saved: Project
    ) -> None:
        assert EventRepository(session).latest_sequence(saved.id) == 0
