"""Behaviour every TTS provider must exhibit.

A provider that passes this suite can be swapped in without changing the pipeline. These
assertions are the actual interface, more precisely than the Protocol can express.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from germandubi.application.ports.providers import (
    ProviderInfo,
    SynthesisRequest,
    TTSProvider,
)
from germandubi.domain.errors import SynthesisError
from tests.contract.providers import tts_providers

GERMAN = "Entscheidend beim Synchronisieren ist die Zeitabstimmung."


@pytest.fixture(params=tts_providers())
def provider(request: pytest.FixtureRequest) -> TTSProvider:
    provider: TTSProvider = request.param
    return provider


class TestIdentity:
    def test_declares_a_stable_identity(self, provider: TTSProvider) -> None:
        info = provider.info
        assert isinstance(info, ProviderInfo)
        assert info.id and info.name

    def test_declares_whether_it_uses_the_network(self, provider: TTSProvider) -> None:
        assert provider.info.kind is not None

    def test_offers_at_least_one_voice(self, provider: TTSProvider) -> None:
        assert provider.available_voices()

    def test_reports_availability_without_raising(self, provider: TTSProvider) -> None:
        assert isinstance(provider.is_available(), bool)


class TestSynthesis:
    def test_produces_audio_with_a_positive_duration(
        self, provider: TTSProvider, tmp_path: Path
    ) -> None:
        result = provider.synthesize(
            SynthesisRequest(
                text=GERMAN, voice=provider.available_voices()[0], destination=tmp_path / "a.wav"
            )
        )
        assert result.audio_path.exists()
        assert result.audio_path.stat().st_size > 0
        assert result.duration_ms > 0
        assert result.sample_rate > 0

    def test_the_reported_duration_matches_the_written_file(
        self, provider: TTSProvider, tmp_path: Path
    ) -> None:
        """Duration fitting trusts this number; if it lies, the timeline drifts."""
        result = provider.synthesize(
            SynthesisRequest(
                text=GERMAN, voice=provider.available_voices()[0], destination=tmp_path / "a.wav"
            )
        )
        with wave.open(str(result.audio_path), "rb") as handle:
            actual = round(handle.getnframes() * 1000 / handle.getframerate())
        assert result.duration_ms == pytest.approx(actual, abs=50)

    def test_populates_provenance(self, provider: TTSProvider, tmp_path: Path) -> None:
        result = provider.synthesize(
            SynthesisRequest(
                text=GERMAN, voice=provider.available_voices()[0], destination=tmp_path / "a.wav"
            )
        )
        assert result.provider_id == provider.info.id
        assert result.model_id

    def test_longer_text_produces_longer_audio(self, provider: TTSProvider, tmp_path: Path) -> None:
        voice = provider.available_voices()[0]
        short = provider.synthesize(
            SynthesisRequest(text="Ja.", voice=voice, destination=tmp_path / "short.wav")
        )
        long = provider.synthesize(
            SynthesisRequest(text=GERMAN * 3, voice=voice, destination=tmp_path / "long.wav")
        )
        assert long.duration_ms > short.duration_ms

    def test_a_faster_speaking_rate_shortens_the_audio(
        self, provider: TTSProvider, tmp_path: Path
    ) -> None:
        """Rate control is the first, least damaging way to fit German into its slot."""
        voice = provider.available_voices()[0]
        normal = provider.synthesize(
            SynthesisRequest(text=GERMAN, voice=voice, destination=tmp_path / "n.wav")
        )
        faster = provider.synthesize(
            SynthesisRequest(
                text=GERMAN, voice=voice, destination=tmp_path / "f.wav", speaking_rate=1.3
            )
        )
        assert faster.duration_ms < normal.duration_ms

    def test_creates_missing_parent_directories(
        self, provider: TTSProvider, tmp_path: Path
    ) -> None:
        target = tmp_path / "deep" / "nested" / "a.wav"
        assert provider.synthesize(
            SynthesisRequest(text=GERMAN, voice=provider.available_voices()[0], destination=target)
        ).audio_path.exists()


class TestRejection:
    @pytest.mark.parametrize("text", ["", "   ", "\n"])
    def test_refuses_empty_text(self, provider: TTSProvider, tmp_path: Path, text: str) -> None:
        with pytest.raises(SynthesisError, match="empty"):
            provider.synthesize(
                SynthesisRequest(
                    text=text,
                    voice=provider.available_voices()[0],
                    destination=tmp_path / "a.wav",
                )
            )

    @pytest.mark.parametrize("rate", [0.0, -1.0])
    def test_refuses_a_non_positive_speaking_rate(
        self, provider: TTSProvider, tmp_path: Path, rate: float
    ) -> None:
        with pytest.raises(SynthesisError, match="positive"):
            provider.synthesize(
                SynthesisRequest(
                    text=GERMAN,
                    voice=provider.available_voices()[0],
                    destination=tmp_path / "a.wav",
                    speaking_rate=rate,
                )
            )
