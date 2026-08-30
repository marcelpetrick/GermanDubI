"""Project lifecycle and the language-pair constraint."""

from __future__ import annotations

import pytest

from germandubi.domain.entities.project import (
    CaptionTrack,
    Project,
    ProjectState,
    QualityProfile,
    SourceKind,
    SourceMedia,
    SourceRef,
)
from germandubi.domain.errors import DomainError, InvalidStateTransitionError
from germandubi.domain.value_objects.language import LanguageCode
from germandubi.domain.value_objects.source_url import validate_source_url


@pytest.fixture
def source() -> SourceRef:
    return SourceRef.from_url(validate_source_url("https://youtu.be/dQw4w9WgXcQ"))


@pytest.fixture
def project(source: SourceRef) -> Project:
    return Project.create(source)


class TestCreation:
    def test_a_new_project_starts_in_the_new_state(self, project: Project) -> None:
        assert project.state is ProjectState.NEW

    def test_defaults_to_english_to_german(self, project: Project) -> None:
        assert project.source_language is LanguageCode.ENGLISH
        assert project.target_language is LanguageCode.GERMAN

    def test_defaults_to_the_balanced_quality_profile(self, project: Project) -> None:
        assert project.quality is QualityProfile.BALANCED

    def test_rejects_an_unsupported_language_pair(self, project: Project) -> None:
        with pytest.raises(DomainError, match="unsupported language pair"):
            Project(
                id=project.id,
                source=project.source,
                source_language=LanguageCode.GERMAN,
                target_language=LanguageCode.ENGLISH,
            )

    def test_a_youtube_source_carries_the_video_id(self, source: SourceRef) -> None:
        assert source.kind is SourceKind.YOUTUBE
        assert source.video_id == "dQw4w9WgXcQ"

    def test_a_local_source_must_be_an_absolute_path(self) -> None:
        assert SourceRef.from_local_file("/media/clip.mp4").kind is SourceKind.LOCAL_FILE
        with pytest.raises(DomainError, match="must be absolute"):
            SourceRef.from_local_file("relative/clip.mp4")


class TestLifecycle:
    def test_the_happy_path_reaches_complete(self, project: Project) -> None:
        media = SourceMedia(title="A talk", duration_ms=90_000)
        current = project.transition_to(ProjectState.PROBING).with_probe_result(media)
        assert current.state is ProjectState.READY
        assert current.title == "A talk"
        current = current.transition_to(ProjectState.PROCESSING)
        current = current.transition_to(ProjectState.REVIEW)
        assert current.transition_to(ProjectState.COMPLETE).state is ProjectState.COMPLETE

    def test_a_failed_project_can_be_retried(self, project: Project) -> None:
        failed = project.transition_to(ProjectState.PROBING).transition_to(
            ProjectState.FAILED, error="network unreachable"
        )
        assert failed.error == "network unreachable"
        assert failed.transition_to(ProjectState.PROBING).state is ProjectState.PROBING

    def test_a_cancelled_project_can_be_resumed(self, project: Project) -> None:
        cancelled = (
            project.transition_to(ProjectState.PROBING)
            .transition_to(ProjectState.READY)
            .transition_to(ProjectState.PROCESSING)
            .transition_to(ProjectState.CANCELLED)
        )
        assert cancelled.transition_to(ProjectState.PROCESSING).state is ProjectState.PROCESSING

    def test_a_complete_project_can_be_edited_again(self, project: Project) -> None:
        complete = (
            project.transition_to(ProjectState.PROBING)
            .transition_to(ProjectState.READY)
            .transition_to(ProjectState.PROCESSING)
            .transition_to(ProjectState.REVIEW)
            .transition_to(ProjectState.COMPLETE)
        )
        assert complete.transition_to(ProjectState.PROCESSING).state is ProjectState.PROCESSING

    def test_an_illegal_transition_is_refused_with_the_allowed_set(self, project: Project) -> None:
        with pytest.raises(InvalidStateTransitionError, match="allowed:"):
            project.transition_to(ProjectState.COMPLETE)

    def test_failing_requires_a_reason(self, project: Project) -> None:
        with pytest.raises(DomainError, match="must record why"):
            project.transition_to(ProjectState.FAILED)

    def test_recovering_from_failure_clears_the_error(self, project: Project) -> None:
        failed = project.transition_to(ProjectState.PROBING).transition_to(
            ProjectState.FAILED, error="boom"
        )
        assert failed.transition_to(ProjectState.PROBING).error is None

    def test_transitioning_to_the_current_state_is_a_no_op(self, project: Project) -> None:
        assert project.transition_to(ProjectState.NEW) is project

    @pytest.mark.parametrize(
        ("state", "busy"),
        [
            (ProjectState.PROBING, True),
            (ProjectState.PROCESSING, True),
            (ProjectState.READY, False),
            (ProjectState.REVIEW, False),
        ],
    )
    def test_busy_states_are_the_ones_the_worker_owns(
        self, state: ProjectState, busy: bool
    ) -> None:
        assert state.is_busy is busy


class TestSourceMedia:
    def test_prefers_manual_captions_over_automatic_ones(self) -> None:
        media = SourceMedia(
            title="t",
            duration_ms=1000,
            captions=(
                CaptionTrack(language=LanguageCode.ENGLISH, automatic=True),
                CaptionTrack(language=LanguageCode.ENGLISH, automatic=False),
            ),
        )
        best = media.best_english_caption
        assert best is not None
        assert best.automatic is False

    def test_ignores_captions_in_other_languages(self) -> None:
        media = SourceMedia(
            title="t",
            duration_ms=1000,
            captions=(CaptionTrack(language=LanguageCode.GERMAN, automatic=False),),
        )
        assert media.best_english_caption is None

    def test_reports_no_captions_when_there_are_none(self) -> None:
        assert SourceMedia(title="t", duration_ms=1000).best_english_caption is None

    def test_display_title_falls_back_to_the_source_locator(self, project: Project) -> None:
        assert project.display_title == "https://youtu.be/dQw4w9WgXcQ"
