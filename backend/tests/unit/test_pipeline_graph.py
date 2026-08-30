"""The pipeline stage graph, its execution order and the invalidation closure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from germandubi.domain.entities.pipeline import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    Job,
    JobStatus,
    PipelineRun,
    Stage,
    downstream_of,
)
from germandubi.domain.errors import DomainError, InvalidStateTransitionError
from germandubi.domain.value_objects.identifiers import ProjectId, RunId, new_id


@pytest.fixture
def project_id() -> ProjectId:
    return ProjectId(new_id())


def _deadline() -> datetime:
    """Return a lease deadline far enough ahead that it cannot expire during a test."""
    return datetime.now(UTC) + timedelta(minutes=5)


class TestStageGraph:
    def test_every_stage_declares_its_dependencies(self) -> None:
        assert set(STAGE_DEPENDENCIES) == set(Stage)

    def test_dependencies_only_reference_known_stages(self) -> None:
        for needs in STAGE_DEPENDENCIES.values():
            assert needs <= set(Stage)

    def test_execution_order_lists_every_stage_exactly_once(self) -> None:
        assert sorted(STAGE_ORDER) == sorted(Stage)

    def test_every_stage_follows_all_of_its_dependencies(self) -> None:
        position = {stage: index for index, stage in enumerate(STAGE_ORDER)}
        for stage, needs in STAGE_DEPENDENCIES.items():
            for dependency in needs:
                assert position[dependency] < position[stage], f"{dependency} must precede {stage}"

    def test_probe_is_the_only_stage_with_no_dependencies(self) -> None:
        roots = [s for s, needs in STAGE_DEPENDENCIES.items() if not needs]
        assert roots == [Stage.PROBE]

    def test_export_is_reachable_from_probe(self) -> None:
        assert Stage.EXPORT in downstream_of(Stage.PROBE)

    def test_every_stage_has_a_human_readable_label(self) -> None:
        assert all(stage.label for stage in Stage)


class TestInvalidation:
    def test_editing_a_translation_invalidates_everything_that_uses_it(self) -> None:
        affected = downstream_of(Stage.TRANSLATE)
        assert {
            Stage.SYNTHESIZE,
            Stage.FIT,
            Stage.ASSEMBLE,
            Stage.MIX,
            Stage.QA,
            Stage.EXPORT,
        } <= affected
        assert Stage.SUBTITLE in affected

    def test_invalidation_never_reaches_upstream_stages(self) -> None:
        affected = downstream_of(Stage.TRANSLATE)
        assert not affected & {Stage.PROBE, Stage.ACQUIRE, Stage.NORMALIZE, Stage.SEGMENT}

    def test_a_stage_does_not_invalidate_itself(self) -> None:
        assert Stage.TRANSLATE not in downstream_of(Stage.TRANSLATE)

    def test_separation_does_not_invalidate_the_translation_branch(self) -> None:
        """Re-running separation must not throw away German text or speech."""
        affected = downstream_of(Stage.SEPARATE)
        assert affected == {Stage.MIX, Stage.QA, Stage.EXPORT}

    def test_editing_english_invalidates_the_whole_german_branch(self) -> None:
        affected = downstream_of(Stage.SEGMENT)
        assert Stage.TRANSLATE in affected
        assert Stage.SEPARATE not in affected

    def test_the_last_stage_invalidates_nothing(self) -> None:
        assert downstream_of(Stage.EXPORT) == frozenset()

    def test_accepts_a_set_of_stages(self) -> None:
        combined = downstream_of({Stage.TRANSLATE, Stage.SEPARATE})
        assert combined == downstream_of(Stage.TRANSLATE) | downstream_of(Stage.SEPARATE) - {
            Stage.TRANSLATE
        }


class TestRun:
    def test_a_default_run_covers_the_whole_pipeline(self, project_id: ProjectId) -> None:
        assert PipelineRun.create(project_id).stages == STAGE_ORDER

    def test_a_partial_run_keeps_the_stages_in_execution_order(self, project_id: ProjectId) -> None:
        run = PipelineRun.create(project_id, stages=(Stage.EXPORT, Stage.TRANSLATE, Stage.MIX))
        assert run.stages == (Stage.TRANSLATE, Stage.MIX, Stage.EXPORT)

    def test_a_run_must_contain_at_least_one_stage(self, project_id: ProjectId) -> None:
        with pytest.raises(DomainError, match="at least one stage"):
            PipelineRun.create(project_id, stages=())


class TestJobLifecycle:
    @pytest.fixture
    def job(self, project_id: ProjectId) -> Job:
        return Job.create(run_id=RunId(new_id()), project_id=project_id, stage=Stage.TRANSLATE)

    def test_a_new_job_is_pending_and_claimable(self, job: Job) -> None:
        assert job.status is JobStatus.PENDING
        assert job.status.is_claimable

    def test_claiming_starts_an_attempt_and_takes_a_lease(self, job: Job) -> None:
        deadline = _deadline()
        claimed = job.transition_to(JobStatus.QUEUED).claimed(lease_expires_at=deadline)
        assert claimed.status is JobStatus.RUNNING
        assert claimed.attempt == 1
        assert claimed.lease_expires_at == deadline
        assert claimed.started_at is not None

    def test_success_releases_the_lease_and_completes_progress(self, job: Job) -> None:
        done = (
            job.transition_to(JobStatus.QUEUED)
            .transition_to(JobStatus.RUNNING)
            .transition_to(JobStatus.SUCCEEDED)
        )
        assert done.lease_expires_at is None
        assert done.progress == 1.0
        assert done.finished_at is not None

    def test_a_failed_job_must_record_a_reason(self, job: Job) -> None:
        running = job.transition_to(JobStatus.QUEUED).transition_to(JobStatus.RUNNING)
        with pytest.raises(DomainError, match="must record why"):
            running.transition_to(JobStatus.FAILED)

    def test_an_illegal_transition_is_refused(self, job: Job) -> None:
        with pytest.raises(InvalidStateTransitionError, match="cannot move job"):
            job.transition_to(JobStatus.SUCCEEDED)

    def test_transitioning_to_the_current_status_is_a_no_op(self, job: Job) -> None:
        assert job.transition_to(JobStatus.PENDING) is job

    def test_a_failed_job_can_be_retried_up_to_the_limit(self, job: Job) -> None:
        current = job.transition_to(JobStatus.QUEUED)
        for _ in range(3):
            current = current.claimed(lease_expires_at=_deadline()).transition_to(
                JobStatus.FAILED, error="boom"
            )
            if current.can_retry:
                current = current.transition_to(JobStatus.QUEUED)
        assert current.attempt == 3
        assert not current.can_retry

    def test_progress_is_clamped_into_the_unit_interval(self, job: Job) -> None:
        assert job.with_progress(1.5).progress == 1.0
        assert job.with_progress(-1.0).progress == 0.0
        assert job.with_progress(0.5, "124 / 192 segments").progress_detail == "124 / 192 segments"

    def test_a_successful_job_can_only_be_invalidated(self, job: Job) -> None:
        done = (
            job.transition_to(JobStatus.QUEUED)
            .transition_to(JobStatus.RUNNING)
            .transition_to(JobStatus.SUCCEEDED)
        )
        assert done.transition_to(JobStatus.INVALIDATED).status is JobStatus.INVALIDATED
        with pytest.raises(InvalidStateTransitionError):
            done.transition_to(JobStatus.RUNNING)
