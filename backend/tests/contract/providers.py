"""The list of implementations each contract suite runs against.

Every implementation of a port must pass its contract suite. Real providers are included
but marked ``real_provider``, so they are deselected by default and only run when
explicitly requested with ``make test-real``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.mark.structures import ParameterSet

from germandubi.config import Settings
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider
from germandubi.infrastructure.providers.fakes import (
    FakeTranslationProvider,
    FakeTTSProvider,
)
from germandubi.infrastructure.providers.piper import PiperTTSProvider


def _models_dir() -> Path:
    """Return the shared model cache, so contract runs do not re-download voices."""
    return Settings().models_dir


def translation_providers() -> list[ParameterSet]:
    """Return every translation provider, real ones marked for opt-in running."""
    return [
        pytest.param(FakeTranslationProvider(), id="fake"),
        pytest.param(
            ArgosTranslationProvider(),
            id="argos",
            marks=[
                pytest.mark.real_provider,
                pytest.mark.skipif(
                    not ArgosTranslationProvider().is_available(),
                    reason="argostranslate is not installed",
                ),
            ],
        ),
    ]


def tts_providers() -> list[ParameterSet]:
    """Return every TTS provider, real ones marked for opt-in running."""
    piper = PiperTTSProvider(voices_dir=_models_dir() / "piper")
    return [
        pytest.param(FakeTTSProvider(), id="fake"),
        pytest.param(
            piper,
            id="piper",
            marks=[
                pytest.mark.real_provider,
                pytest.mark.skipif(not piper.is_available(), reason="piper-tts is not installed"),
            ],
        ),
    ]
