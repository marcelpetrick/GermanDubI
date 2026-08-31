import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from germandubi.config import Settings


def test_optional_runtime_paths_are_resolved(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        frontend_dist=tmp_path / "frontend",
        fake_media_fixture=tmp_path / "fixture.mp4",
    )

    assert settings.frontend_dist == (tmp_path / "frontend").resolve()
    assert settings.fake_media_fixture == (tmp_path / "fixture.mp4").resolve()


class TestDeviceSelection:
    """Which compute device the model providers use."""

    def test_an_explicit_device_is_honoured(self, tmp_path: Path) -> None:
        assert Settings(data_dir=tmp_path, device="cuda").resolved_device() == "cuda"
        assert Settings(data_dir=tmp_path, device="cpu").resolved_device() == "cpu"

    def test_auto_uses_the_gpu_when_one_is_usable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
        monkeypatch.setitem(sys.modules, "torch", module)
        assert Settings(data_dir=tmp_path, device="auto").resolved_device() == "cuda"

    def test_auto_falls_back_to_the_cpu_without_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        monkeypatch.setitem(sys.modules, "torch", module)
        assert Settings(data_dir=tmp_path, device="auto").resolved_device() == "cpu"

    def test_a_broken_driver_is_a_slow_run_rather_than_a_failed_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Detection must never be the reason a dub does not happen."""

        def explode() -> bool:
            raise RuntimeError("CUDA driver version is insufficient")

        module = SimpleNamespace(cuda=SimpleNamespace(is_available=explode))
        monkeypatch.setitem(sys.modules, "torch", module)
        assert Settings(data_dir=tmp_path, device="auto").resolved_device() == "cpu"

    def test_torch_absent_means_the_cpu(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "torch", None)
        assert Settings(data_dir=tmp_path, device="auto").resolved_device() == "cpu"
