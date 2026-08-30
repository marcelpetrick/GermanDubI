from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.errors import CaptionError, TranscriptionError
from germandubi.domain.transcript import Transcript, TranscriptCue, TranscriptSource
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.providers.fakes import FakeAlignmentProvider
from germandubi.worker.handlers.transcript import (
    _best_caption,
    _deserialize,
    _load_transcript,
    _serialize,
    handle_align,
    handle_transcribe,
)


def sample_transcript() -> Transcript:
    return Transcript.from_raw(
        [TranscriptCue(TimeInterval(0, 1000), "Hello")],
        source=TranscriptSource.MANUAL_CAPTIONS,
        provider_id="captions",
    )


class FailingCaptions:
    info = SimpleNamespace(name="captions")

    def transcribe(self, _audio: Path, *, language: str) -> Transcript:
        raise CaptionError(f"bad {language}")


class WorkingTranscription:
    info = SimpleNamespace(name="recognition")

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript

    def transcribe(self, _audio: Path, *, language: str) -> Transcript:
        assert language == "en"
        return self.transcript


class HandlerContext:
    def __init__(self, tmp_path: Path, providers: list[Any]) -> None:
        self.audio = tmp_path / "audio.wav"
        self.audio.touch()
        self.providers = iter(providers)
        self.registry = SimpleNamespace(
            transcription=lambda **_kwargs: next(self.providers),
            alignment=lambda: FakeAlignmentProvider(),
        )
        self.project = SimpleNamespace(id="project")
        self.uow = SimpleNamespace(
            artifacts=SimpleNamespace(list_for_project=lambda _project: []),
            store=SimpleNamespace(read_text_at=lambda path: path.read_text()),
        )
        self.root = tmp_path
        self.progress_updates: list[tuple[float, str]] = []
        self.published: list[ArtifactKind] = []
        self.events: list[str] = []
        self.checkpoints = 0

    def require(self, kind: ArtifactKind) -> Path:
        if kind is ArtifactKind.TRANSCRIPT:
            return self.root / "transcript" / "transcript.json"
        return self.audio

    def directory(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(exist_ok=True)
        return path

    def progress(self, fraction: float, detail: str) -> None:
        self.progress_updates.append((fraction, detail))

    def checkpoint(self) -> None:
        self.checkpoints += 1

    def publish(self, kind: ArtifactKind, _path: Path, **_kwargs: Any) -> None:
        self.published.append(kind)

    def event(self, kind: str, _payload: dict[str, object]) -> None:
        self.events.append(kind)

    def latest(self, _kind: ArtifactKind) -> None:
        return None


def test_transcription_falls_back_from_bad_captions(tmp_path: Path) -> None:
    transcript = sample_transcript()
    context = HandlerContext(tmp_path, [FailingCaptions(), WorkingTranscription(transcript)])
    handle_transcribe(context)  # type: ignore[arg-type]
    assert context.checkpoints == 2
    assert context.published == [ArtifactKind.TRANSCRIPT]
    assert context.events == ["transcript_ready"]
    assert _deserialize((tmp_path / "transcript" / "transcript.json").read_text()) == transcript


def test_transcription_rejects_an_empty_result(tmp_path: Path) -> None:
    empty = object.__new__(Transcript)
    object.__setattr__(empty, "source", TranscriptSource.ASR)
    object.__setattr__(empty, "cues", ())
    object.__setattr__(empty, "provider_id", "empty")
    object.__setattr__(empty, "model_id", None)
    object.__setattr__(empty, "language", "en")
    context = HandlerContext(tmp_path, [WorkingTranscription(empty)])
    with pytest.raises(TranscriptionError, match="no English speech"):
        handle_transcribe(context)  # type: ignore[arg-type]


def test_alignment_persists_word_timing_for_caption_transcript(tmp_path: Path) -> None:
    context = HandlerContext(tmp_path, [])
    path = context.directory("transcript") / "transcript.json"
    path.write_text(_serialize(sample_transcript()))
    handle_align(context)  # type: ignore[arg-type]
    assert context.published == [ArtifactKind.ALIGNMENT]
    assert context.progress_updates[-1][1].endswith("words")
    assert _load_transcript(context) == sample_transcript()  # type: ignore[arg-type]


def test_deserialize_reports_corrupt_persisted_data() -> None:
    with pytest.raises(TranscriptionError, match="could not be read"):
        _deserialize('{"source": "asr", "cues": [{"text": "missing timing"}]}')


def test_best_caption_prefers_manual_and_reports_automatic(tmp_path: Path) -> None:
    manual = SimpleNamespace(
        kind=ArtifactKind.SOURCE_CAPTIONS,
        provenance=SimpleNamespace(parameters={"automatic": "False"}),
    )
    automatic = SimpleNamespace(
        kind=ArtifactKind.SOURCE_CAPTIONS,
        provenance=SimpleNamespace(parameters={"automatic": "True"}),
    )
    store = SimpleNamespace(
        path_for=lambda artifact: tmp_path / ("manual" if artifact is manual else "auto")
    )
    context: Any = SimpleNamespace(
        project=SimpleNamespace(id="project"),
        uow=SimpleNamespace(
            artifacts=SimpleNamespace(list_for_project=lambda _project: [automatic, manual]),
            store=store,
        ),
    )
    assert _best_caption(context) == (tmp_path / "manual", False)
    context.uow.artifacts.list_for_project = lambda _project: [automatic]
    assert _best_caption(context) == (tmp_path / "auto", True)
