from __future__ import annotations

import signal
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from germandubi.composition import Application, build_application
from germandubi.config import Settings
from germandubi.domain.entities.pipeline import JobStatus, Stage
from germandubi.domain.entities.project import ProjectState
from germandubi.domain.errors import CancelledError, DomainError
from germandubi.worker.handlers import HANDLERS


@pytest.fixture
def application(tmp_path: Path) -> Iterator[Application]:
    fixture = tmp_path / "fixture.mp4"
    fixture.touch()
    app = build_application(
        Settings(
            data_dir=tmp_path / "data",
            transcription_provider="fake",
            translation_provider="fake",
            tts_provider="fake",
            separation_provider="fake",
            worker_poll_interval_s=0.001,
        ),
        fixture=fixture,
    )
    yield app
    app.dispose()


def queued_probe(application: Application) -> tuple[Any, Any]:
    project = application.projects.create_from_url("https://www.youtube.com/watch?v=abcdefghijk")
    run = application.projects.request_analysis(project.id)
    return project, run


def test_worker_retries_then_permanently_fails(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run = queued_probe(application)

    def fail(_context: Any) -> None:
        raise DomainError("provider failed")

    monkeypatch.setitem(HANDLERS, Stage.PROBE, fail)
    worker = application.worker()
    assert worker.run_once()
    assert worker.run_once()
    assert worker.run_once()
    assert not worker.run_once()

    progress = application.pipeline.progress(run.id)
    assert progress.failed and progress.finished
    assert progress.jobs[0].status is JobStatus.FAILED
    assert progress.jobs[0].attempt == 3
    assert application.projects.get(project.id).state is ProjectState.FAILED
    with application.unit_of_work() as uow:
        kinds = [kind for _, kind, _ in uow.events.since(project.id, after=0)]
    assert kinds.count("stage_retrying") == 2
    assert "stage_failed" in kinds


def test_worker_wraps_unexpected_errors(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run = queued_probe(application)

    def crash(_context: Any) -> None:
        raise RuntimeError("surprise")

    monkeypatch.setitem(HANDLERS, Stage.PROBE, crash)
    worker = application.worker()
    for _ in range(3):
        assert worker.run_once()
    job = application.pipeline.progress(run.id).jobs[0]
    assert job.error == "unexpected error: surprise"
    assert application.projects.get(project.id).state is ProjectState.FAILED


def test_worker_records_cancellation(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run = queued_probe(application)

    def cancel(_context: Any) -> None:
        raise CancelledError("stop")

    monkeypatch.setitem(HANDLERS, Stage.PROBE, cancel)
    assert application.worker().run_once()
    assert application.pipeline.progress(run.id).jobs[0].status is JobStatus.CANCELLED
    with application.unit_of_work() as uow:
        kinds = [kind for _, kind, _ in uow.events.since(project.id, after=0)]
    assert "stage_cancelled" in kinds


def test_worker_fails_a_job_without_a_registered_handler(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project, run = queued_probe(application)
    monkeypatch.delitem(HANDLERS, Stage.PROBE)
    assert application.worker().run_once()
    job = application.pipeline.progress(run.id).jobs[0]
    assert job.status is JobStatus.FAILED
    assert job.error == "no handler for stage probe"


def test_success_reports_progress_and_finishes_run(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run = queued_probe(application)

    def succeed(context: Any) -> None:
        context.report(0.5, "halfway")

    monkeypatch.setitem(HANDLERS, Stage.PROBE, succeed)
    assert application.worker().run_once()
    progress = application.pipeline.progress(run.id)
    assert progress.finished and progress.fraction == 1.0
    with application.unit_of_work() as uow:
        kinds = [kind for _, kind, _ in uow.events.since(project.id, after=0)]
    assert "stage_progress" in kinds and "run_finished" in kinds


def test_worker_lifecycle_helpers(
    application: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = application.worker()
    handlers: dict[int, Any] = {}

    def capture(kind: int, callback: Any) -> None:
        handlers[kind] = callback

    monkeypatch.setattr(signal, "signal", capture)
    worker.install_signal_handlers()
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert worker.stopping

    worker.stopping = False
    outcomes = iter([True, True, False])
    monkeypatch.setattr(worker, "run_once", lambda: next(outcomes))
    assert worker.run_until_idle() == 2

    calls = iter([True, False])
    monkeypatch.setattr(worker, "run_once", lambda: next(calls))

    def stop_after_sleep(_seconds: float) -> None:
        worker.stopping = True

    monkeypatch.setattr(time, "sleep", stop_after_sleep)
    worker.run_forever()
