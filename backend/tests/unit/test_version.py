"""Tests for build identity resolution."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from germandubi.version import BuildInfo, build_info, parse_build_info, resolve_version

version_module = importlib.import_module("germandubi.version")

# PEP 440: release segment, optional .devN, optional +local
PEP440 = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-zA-Z0-9.]+)?$")


def test_resolve_version_returns_a_pep440_string() -> None:
    assert PEP440.match(resolve_version()), resolve_version()


def test_source_checkout_ignores_a_stale_generated_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(version_module, "_repository_root", lambda: tmp_path)
    monkeypatch.setattr(version_module, "_from_scm", lambda: "0.4.1.dev2+gnew1234")
    monkeypatch.setattr(version_module, "_from_generated_module", lambda: "0.4.1.dev1+gold1234")
    monkeypatch.setattr(version_module, "_from_installed_metadata", lambda: "0.4.0")

    assert resolve_version() == "0.4.1.dev2+gnew1234"


def test_build_info_is_consistent_with_the_version_string() -> None:
    info = build_info()
    assert info.version == resolve_version()
    if info.git_revision is not None:
        assert re.fullmatch(r"[0-9a-f]{7,40}", info.git_revision)


@pytest.mark.parametrize(
    ("version", "revision", "dirty", "expected"),
    [
        ("0.2.2.dev17+g1a2b3c4", "1a2b3c4", False, "0.2.2.dev17 (g1a2b3c4)"),
        ("0.2.2.dev17+g1a2b3c4.d20260830", "1a2b3c4", True, "0.2.2.dev17 (g1a2b3c4-dirty)"),
        ("0.2.1", None, False, "0.2.1"),
    ],
)
def test_display_drops_the_local_segment(
    version: str, revision: str | None, dirty: bool, expected: str
) -> None:
    assert BuildInfo(version=version, git_revision=revision, dirty=dirty).display == expected


@pytest.mark.parametrize(
    ("version", "revision", "dirty"),
    [
        ("0.2.2.dev17+g1a2b3c4", "1a2b3c4", False),
        ("0.2.2.dev17+g1a2b3c4.d20260830", "1a2b3c4", True),
        ("0.0.1.dev2+g82eee9de0", "82eee9de0", False),
    ],
)
def test_parse_build_info_reads_the_local_segment(version: str, revision: str, dirty: bool) -> None:
    parsed = parse_build_info(version)
    assert parsed is not None
    assert parsed.git_revision == revision
    assert parsed.dirty is dirty


def test_parse_build_info_returns_none_for_an_exact_release_version() -> None:
    """A tagged release has no local segment, so the revision must come from Git instead."""
    assert parse_build_info("0.3.0") is None


def test_version_sources_degrade_cleanly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        version_module.metadata,
        "version",
        lambda _name: (_ for _ in ()).throw(version_module.metadata.PackageNotFoundError),
    )
    assert version_module._from_installed_metadata() is None

    monkeypatch.setitem(__import__("sys").modules, "setuptools_scm", None)
    assert version_module._from_scm() is None

    monkeypatch.setattr(version_module, "_repository_root", lambda: tmp_path)
    monkeypatch.setattr(version_module, "_from_generated_module", lambda: None)
    monkeypatch.setattr(version_module, "_from_installed_metadata", lambda: None)
    assert resolve_version() == "0.0.0+unknown"


def test_release_revision_reads_loose_detached_and_packed_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    monkeypatch.setattr(version_module, "_repository_root", lambda: tmp_path)

    revision = "0123456789abcdef0123456789abcdef01234567"
    (git / "HEAD").write_text(revision)
    assert version_module._revision_from_git_directory() == revision[:12]
    (git / "HEAD").write_text("not-a-revision")
    assert version_module._revision_from_git_directory() is None

    (git / "HEAD").write_text("ref: refs/heads/main")
    ref = git / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    ref.write_text(revision)
    assert version_module._revision_from_git_directory() == revision[:12]
    ref.unlink()
    (git / "packed-refs").write_text(f"{revision} refs/heads/main\n")
    assert version_module._revision_from_git_directory() == revision[:12]
    (git / "packed-refs").write_text("# empty\n")
    assert version_module._revision_from_git_directory() is None
    (git / "HEAD").unlink()
    assert version_module._revision_from_git_directory() is None


def test_build_info_for_exact_release_uses_git_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_module, "resolve_version", lambda: "1.2.3")
    monkeypatch.setattr(version_module, "_revision_from_git_directory", lambda: "abcdef012345")
    assert build_info() == BuildInfo("1.2.3", "abcdef012345", False)
