import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from germandubi.composition import configure_logging
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


class TestTheServerLog:
    """The log has to be findable, because an error message points a user at it.

    "Check the server log for details" was true and useless: the log went to the terminal's
    stderr and nowhere else, so a user who had closed or scrolled past that terminal had
    nothing to check.
    """

    def test_it_defaults_to_a_file_inside_the_data_directory(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path)
        assert settings.resolved_log_file == tmp_path / "logs" / "germandubi.log"

    def test_an_explicit_path_is_honoured_and_resolved(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path, log_file=tmp_path / "sub" / ".." / "own.log")
        assert settings.resolved_log_file == tmp_path / "own.log"

    def test_it_can_be_turned_off(self, tmp_path: Path) -> None:
        assert Settings(data_dir=tmp_path, log_file=Path("none")).resolved_log_file is None

    def test_the_directory_is_created_with_the_others(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        settings.ensure_directories()
        assert settings.logs_dir.is_dir()

    def test_configured_logging_writes_to_it(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        try:
            configure_logging(settings)
            logging.getLogger("germandubi.test").error("a failure worth keeping")
            logging.shutdown()
            destination = settings.resolved_log_file
            assert destination is not None
            assert "a failure worth keeping" in destination.read_text(encoding="utf-8")
        finally:
            # Leave the process's logging as the rest of the suite expects to find it.
            logging.basicConfig(force=True)

    def test_an_unwritable_destination_does_not_stop_the_server(self, tmp_path: Path) -> None:
        """A read-only volume is a nuisance, not a reason to refuse to dub anything."""
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        settings = Settings(data_dir=tmp_path / "data", log_file=blocked / "server.log")
        try:
            configure_logging(settings)
            logging.getLogger("germandubi.test").error("still logging to the console")
        finally:
            logging.basicConfig(force=True)
