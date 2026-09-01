"""The worker must not lock the database out while a stage runs.

Adding a second video during a dub returned `500 Internal Server Error` with
`sqlite3.OperationalError: database is locked`. The worker opened one transaction, wrote a
`stage_started` event into it -- taking SQLite's write lock -- and only then ran the stage.
Transcribing a 40-minute source held that lock for 123 seconds, against the API's
10-second busy timeout.

It then came back in a second form. Moving the stage out of that transaction was not
enough, because reporting progress *flushed*: a handler that announces "using
faster-whisper" and then recognises speech took the write lock with the announcement and
held it for the recognition. Both shapes are covered below.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from germandubi.composition import Application, build_application
from germandubi.config import Settings
from germandubi.domain.entities.pipeline import Stage
from germandubi.domain.errors import ResourceError
from germandubi.worker.context import StageContext
from germandubi.worker.handlers import HANDLERS
from tests.fixtures.media import make_narration_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")

VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
SECOND_URL = "https://www.youtube.com/watch?v=Wo0KujQEJ_s"


@pytest.fixture
def application(tmp_path: Path) -> Iterator[Application]:
    clip = make_narration_video(tmp_path / "clip.mp4", seconds=3)
    settings = Settings(
        data_dir=tmp_path / "data",
        transcription_provider="fake",
        translation_provider="fake",
        tts_provider="fake",
        separation_provider="fake",
    )
    wired = build_application(settings, fixture=clip)
    yield wired
    wired.dispose()


def test_a_project_can_be_created_while_a_stage_is_running(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact failure: a second URL added during a long stage.

    The stand-in handler blocks the way speech recognition does -- slow work with nothing
    written until it finishes -- which is when the lock used to be held and is not any more.
    """
    running = threading.Event()
    finish = threading.Event()

    def slow_stage(_context: StageContext) -> None:
        running.set()
        assert finish.wait(timeout=30), "the test never released the stage"

    monkeypatch.setitem(HANDLERS, Stage.PROBE, slow_stage)

    first = application.projects.create_from_url(VALID_URL)
    application.projects.request_analysis(first.id)

    worker = application.worker()
    thread = threading.Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert running.wait(timeout=30), "the stage never started"

    try:
        started = time.monotonic()
        second = application.projects.create_from_url(SECOND_URL)
        elapsed = time.monotonic() - started
    finally:
        finish.set()
        thread.join(timeout=30)

    assert second.id != first.id
    # It must not merely succeed eventually: waiting out a busy timeout is the symptom.
    assert elapsed < 5, f"creating a project waited {elapsed:.1f}s on the running stage"


def test_progress_from_a_running_stage_does_not_block_readers(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stage that reports progress still leaves the database readable."""
    reported = threading.Event()
    finish = threading.Event()

    def reporting_stage(context: StageContext) -> None:
        context.report(0.5, "halfway")
        context.checkpoint()
        reported.set()
        assert finish.wait(timeout=30), "the test never released the stage"

    monkeypatch.setitem(HANDLERS, Stage.PROBE, reporting_stage)

    project = application.projects.create_from_url(VALID_URL)
    application.projects.request_analysis(project.id)

    worker = application.worker()
    thread = threading.Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert reported.wait(timeout=30), "the stage never reported"

    try:
        # A checkpoint commits what the stage has written, so this must see the progress
        # rather than block on it.
        listed = application.projects.list_projects()
    finally:
        finish.set()
        thread.join(timeout=30)

    assert any(item.id == project.id for item in listed)


def test_a_project_can_be_created_while_a_stage_that_reported_progress_runs(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Announcing a step and then doing it must not hold the write lock for the doing.

    This is the shape of every real handler and the second time this defect appeared.
    `handle_transcribe` reports "using faster-whisper" and only then recognises speech;
    reporting used to flush rather than commit, so the write lock was taken by the
    announcement and held for the two minutes that followed. Adding a second video during
    that window waited out the busy timeout and failed with a bare 500.

    Deliberately no checkpoint: a stage inside one long model call has nowhere to put one,
    which is why the release cannot be left to the checkpoint.
    """
    reported = threading.Event()
    finish = threading.Event()

    def announce_then_work(context: StageContext) -> None:
        context.progress(0.1, "using faster-whisper (small)")
        reported.set()
        assert finish.wait(timeout=30), "the test never released the stage"

    monkeypatch.setitem(HANDLERS, Stage.PROBE, announce_then_work)

    first = application.projects.create_from_url(VALID_URL)
    application.projects.request_analysis(first.id)

    worker = application.worker()
    thread = threading.Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert reported.wait(timeout=30), "the stage never reported progress"

    try:
        started = time.monotonic()
        second = application.projects.create_from_url(SECOND_URL)
        elapsed = time.monotonic() - started
    finally:
        finish.set()
        thread.join(timeout=30)

    assert second.id != first.id
    assert elapsed < 5, f"creating a project waited {elapsed:.1f}s behind a progress report"


def test_progress_is_visible_to_another_connection_before_the_stage_ends(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uncommitted progress report is invisible, so the bar did not move.

    The same flush that held the lock also kept the update inside the worker's transaction,
    where the API could not read it. The processing screen only advanced at checkpoints.
    """
    reported = threading.Event()
    finish = threading.Event()

    def announce_then_work(context: StageContext) -> None:
        context.progress(0.42, "halfway through the model")
        reported.set()
        assert finish.wait(timeout=30), "the test never released the stage"

    monkeypatch.setitem(HANDLERS, Stage.PROBE, announce_then_work)

    project = application.projects.create_from_url(VALID_URL)
    application.projects.request_analysis(project.id)

    worker = application.worker()
    thread = threading.Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert reported.wait(timeout=30), "the stage never reported progress"

    try:
        with application.unit_of_work() as uow:
            details = [
                payload.get("detail")
                for _sequence, kind, payload in uow.events.since(project.id, 0)
                if kind == "stage_progress"
            ]
    finally:
        finish.set()
        thread.join(timeout=30)

    assert "halfway through the model" in details


def test_a_newly_added_url_is_inspected_before_a_running_dub_continues(
    application: Application,
) -> None:
    """Strict age order put a new project's probe behind fifteen stages of the old one.

    Nothing was broken by that -- the queue was fair -- but pasting a URL did nothing
    visible for minutes, which a user cannot tell apart from a hang.
    """
    first = application.projects.create_from_url(VALID_URL)
    worker = application.worker()
    application.projects.request_analysis(first.id)
    worker.run_until_idle()
    application.pipeline.start(first.id)

    second = application.projects.create_from_url(SECOND_URL)
    application.projects.request_analysis(second.id)

    with application.unit_of_work() as uow:
        claimed = uow.jobs.claim_next(lease_seconds=900)

    assert claimed is not None
    assert claimed.stage is Stage.PROBE
    assert str(claimed.project_id) == str(second.id)


def test_cancelling_terminates_the_running_subprocess(application: Application) -> None:
    """Stop must reach the tool doing the work, not just the loop around it.

    `ProcessRunner` was constructed without its `cancelled` callback, so cancelling never
    terminated the ffmpeg, yt-dlp or Demucs process actually running. A stage would notice
    only at its next checkpoint, and one that spends minutes inside a single external call
    has no checkpoint to reach.
    """
    project = application.projects.create_from_url(VALID_URL)
    application.projects.request_analysis(project.id)

    with application.unit_of_work() as uow:
        run = uow.jobs.latest_run(project.id)
    assert run is not None

    worker = application.worker()
    # The worker wires the probe when it starts a stage; drive one job so that happens.
    started = threading.Event()

    def slow_stage(context: StageContext) -> None:
        started.set()
        # A long external command, exactly what cancellation has to interrupt.
        context.registry.runner.run(["sleep", "60"], timeout_s=120)

    original = HANDLERS[Stage.PROBE]
    HANDLERS[Stage.PROBE] = slow_stage
    try:
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        assert started.wait(timeout=30), "the stage never started"
        time.sleep(1)  # let the subprocess actually start

        application.pipeline.cancel_latest(project.id)

        # Without cancellation reaching the process this waits the full 60 seconds.
        thread.join(timeout=25)
        assert not thread.is_alive(), "cancelling did not stop the running subprocess"
    finally:
        HANDLERS[Stage.PROBE] = original


def test_reset_removes_every_project_and_its_workspace(application: Application) -> None:
    first = application.projects.create_from_url(VALID_URL)
    second = application.projects.create_from_url(SECOND_URL)
    workspaces = [
        application.store.workspace(first.id),
        application.store.workspace(second.id),
    ]
    assert all(path.exists() for path in workspaces)

    removed = application.projects.delete_all()

    assert removed == 2
    assert application.projects.list_projects() == []
    # Files, not just rows: a clear that leaves workspaces behind frees nothing.
    assert not any(path.exists() for path in workspaces)


def test_reset_on_an_empty_installation_is_harmless(application: Application) -> None:
    assert application.projects.delete_all() == 0


class TestResumability:
    """`checkpoint()` commits, so a stage must be safe to run again after failing part-way.

    This is the contract that keeps the write lock short. A handler which assumed its
    writes would roll back would meet its own partial output on the retry, and the pipeline
    retries every stage twice by default.
    """

    def test_a_stage_that_fails_after_a_checkpoint_keeps_what_it_committed(
        self, application: Application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = application.projects.create_from_url(VALID_URL)
        seen: list[str] = []

        def half_finished(context: StageContext) -> None:
            context.event("partial_work", {"step": "one"})
            context.checkpoint()  # commits
            seen.append("committed")
            raise RuntimeError("stopped after doing half the work")

        monkeypatch.setitem(HANDLERS, Stage.PROBE, half_finished)
        application.projects.request_analysis(project.id)
        application.worker().run_once()

        assert seen == ["committed"]
        with application.unit_of_work() as uow:
            kinds = [kind for _sequence, kind, _payload in uow.events.since(project.id, 0)]
        # Committed before the failure, so it survives: that is what a retry will meet.
        assert "partial_work" in kinds

    def test_a_resumable_handler_reaches_the_same_result_as_an_uninterrupted_one(
        self, application: Application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pattern every handler must follow: look for your own output first."""
        produced: list[int] = []
        attempt = {"count": 0}

        def resumable(context: StageContext) -> None:
            attempt["count"] += 1
            for index in range(4):
                if index in produced:
                    continue  # already done on the earlier attempt
                produced.append(index)
                context.checkpoint()
                if attempt["count"] == 1 and index == 1:
                    raise RuntimeError("interrupted half way")

        monkeypatch.setitem(HANDLERS, Stage.PROBE, resumable)
        project = application.projects.create_from_url(SECOND_URL)
        application.projects.request_analysis(project.id)
        worker = application.worker()

        worker.run_once()  # fails after two items, having committed them
        worker.run_once()  # the retry resumes

        assert produced == [0, 1, 2, 3], "a resumed stage must not redo or skip work"
        assert attempt["count"] == 2


class TestSingleWorker:
    """One worker per data directory, and a long stage that is not mistaken for a dead one."""

    def test_a_second_worker_is_refused(self, application: Application) -> None:
        """Two workers would claim different jobs of one run and share a workspace."""
        first = application.worker()
        second = application.worker()

        with (
            first.exclusive(),
            pytest.raises(ResourceError, match="another worker is already running"),
            second.exclusive(),
        ):
            pass

    def test_the_slot_is_released_when_the_holder_finishes(self, application: Application) -> None:
        worker = application.worker()
        with worker.exclusive():
            pass

        # A crashed worker must not lock its successor out; flock releases on close.
        with worker.exclusive():
            pass

    def test_a_checkpoint_pushes_the_lease_out(
        self, application: Application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stage legitimately longer than its lease must not be reclaimed underneath it.

        Separation of a long source takes minutes, against a lease measured in the same
        minutes, so the lease has to mean "still alive" rather than "expected to be quick".
        """
        project = application.projects.create_from_url(VALID_URL)
        leases: list[object] = []

        def slow(context: StageContext) -> None:
            with application.unit_of_work() as uow:
                leases.append(uow.jobs.get_job(context.job.id).lease_expires_at)
            time.sleep(1.1)
            context.checkpoint()  # renews
            with application.unit_of_work() as uow:
                leases.append(uow.jobs.get_job(context.job.id).lease_expires_at)

        monkeypatch.setitem(HANDLERS, Stage.PROBE, slow)
        application.projects.request_analysis(project.id)
        application.worker().run_once()

        assert len(leases) == 2
        assert leases[1] > leases[0], "the checkpoint should have extended the lease"
