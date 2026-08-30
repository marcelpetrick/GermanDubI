from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.piper import PiperTTSProvider


@pytest.mark.parametrize(
    ("package", "probe"),
    [
        ("argostranslate.translate", ArgosTranslationProvider().is_available),
        ("piper", PiperTTSProvider(voices_dir=Path("unused")).is_available),
    ],
)
def test_broken_optional_dependency_is_reported_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    package: str,
    probe: Callable[[], bool],
) -> None:
    real_import = builtins.__import__

    def broken_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == package or name.startswith(f"{package}."):
            msg = "optional dependency is incompatible"
            raise SyntaxError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)

    assert probe() is False
