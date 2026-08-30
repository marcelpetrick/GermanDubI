from pathlib import Path

from germandubi.config import Settings


def test_optional_runtime_paths_are_resolved(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        frontend_dist=tmp_path / "frontend",
        fake_media_fixture=tmp_path / "fixture.mp4",
    )

    assert settings.frontend_dist == (tmp_path / "frontend").resolve()
    assert settings.fake_media_fixture == (tmp_path / "fixture.mp4").resolve()
