from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from germandubi.domain.entities.artifact import Artifact, ArtifactKind
from germandubi.domain.errors import DomainError, ResourceError
from germandubi.domain.value_objects.identifiers import ProjectId, new_id
from germandubi.infrastructure.artifacts.store import ArtifactStore, sanitize_filename


@pytest.fixture
def project_id() -> ProjectId:
    return ProjectId(new_id())


def test_workspace_allocation_recording_and_verification(
    tmp_path: Path, project_id: ProjectId
) -> None:
    store = ArtifactStore(tmp_path / "root")
    workspace = store.create_workspace(project_id)
    assert all((workspace / name).is_dir() for name in store.LAYOUT)

    artifact, path = store.allocate(
        project_id,
        ArtifactKind.TRANSCRIPT,
        "../../A strange 🔥 title.json",
        media_type="application/json",
    )
    recorded = store.write_text(artifact, '{"ok": true}')
    assert path.name == "A strange title.json"
    assert store.read_text(recorded) == '{"ok": true}'
    assert store.read_text_at(path) == '{"ok": true}'
    assert store.verify(recorded)
    assert store.content_hash(path) == recorded.content_hash

    path.write_text("changed")
    assert not store.verify(recorded)
    assert not store.verify(artifact)
    path.unlink()
    assert not store.verify(recorded)

    store.delete_workspace(project_id)
    assert not workspace.exists()


def test_missing_empty_and_escaping_artifacts_are_rejected(
    tmp_path: Path, project_id: ProjectId
) -> None:
    store = ArtifactStore(tmp_path / "root")
    artifact, path = store.allocate(project_id, ArtifactKind.TRANSCRIPT, "text.json")
    with pytest.raises(DomainError, match="bare name"):
        Artifact.create(project_id=project_id, kind=ArtifactKind.TRANSCRIPT, filename="../x")
    with pytest.raises(DomainError, match="inside the workspace"):
        replace(artifact, relative_path="../outside")
    with pytest.raises(ResourceError, match="was not written"):
        store.record(artifact)
    path.touch()
    with pytest.raises(ResourceError, match="is empty"):
        store.record(artifact)
    path.unlink()
    with pytest.raises(ResourceError, match="artifact file is missing"):
        store.read_text(artifact)
    with pytest.raises(ResourceError, match="file is missing"):
        store.read_text_at(tmp_path / "missing")
    with pytest.raises(DomainError, match="escapes"):
        store.resolve(project_id, "../../outside")


def test_stream_supports_full_and_bounded_ranges(tmp_path: Path, project_id: ProjectId) -> None:
    store = ArtifactStore(tmp_path / "root")
    path = store.workspace(project_id) / "media.bin"
    path.parent.mkdir(parents=True)
    payload = bytes(range(256)) * 600
    path.write_bytes(payload)
    assert b"".join(store.stream(path)) == payload
    assert b"".join(store.stream(path, start=10, end=19)) == payload[10:20]
    assert b"".join(store.stream(path, start=len(payload))) == b""


@pytest.mark.parametrize(
    ("name", "expected"),
    [("...", "fallback"), ("a" * 100, "a" * 80), ("  one   two  ", "one two")],
)
def test_filename_sanitization(name: str, expected: str) -> None:
    assert sanitize_filename(name, fallback="fallback") == expected
