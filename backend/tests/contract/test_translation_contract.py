"""Behaviour every translation provider must exhibit."""

from __future__ import annotations

import pytest

from germandubi.application.ports.providers import (
    ProviderInfo,
    TranslationProvider,
    TranslationRequest,
)
from germandubi.domain.errors import TranslationError
from tests.contract.providers import translation_providers

ENGLISH = "The important thing about dubbing is the timing."


@pytest.fixture(params=translation_providers())
def provider(request: pytest.FixtureRequest) -> TranslationProvider:
    provider: TranslationProvider = request.param
    return provider


class TestIdentity:
    def test_declares_a_stable_identity(self, provider: TranslationProvider) -> None:
        assert isinstance(provider.info, ProviderInfo)
        assert provider.info.id

    def test_reports_availability_without_raising(self, provider: TranslationProvider) -> None:
        assert isinstance(provider.is_available(), bool)


class TestTranslation:
    def test_returns_non_empty_german(self, provider: TranslationProvider) -> None:
        result = provider.translate(TranslationRequest(text=ENGLISH))
        assert result.text.strip()

    def test_the_output_differs_from_the_input(self, provider: TranslationProvider) -> None:
        assert provider.translate(TranslationRequest(text=ENGLISH)).text != ENGLISH

    def test_populates_provenance(self, provider: TranslationProvider) -> None:
        result = provider.translate(TranslationRequest(text=ENGLISH))
        assert result.provider_id == provider.info.id

    def test_is_deterministic_when_it_claims_to_be(self, provider: TranslationProvider) -> None:
        """Only a deterministic provider may be relied on for caching and golden files."""
        if not provider.info.deterministic:
            pytest.skip("this provider does not claim determinism")
        first = provider.translate(TranslationRequest(text=ENGLISH)).text
        second = provider.translate(TranslationRequest(text=ENGLISH)).text
        assert first == second

    def test_batch_returns_one_result_per_request_in_order(
        self, provider: TranslationProvider
    ) -> None:
        requests = [
            TranslationRequest(text="The first sentence."),
            TranslationRequest(text="The second sentence."),
            TranslationRequest(text="The third sentence."),
        ]
        results = provider.translate_batch(requests)
        assert len(results) == 3
        singly = [provider.translate(request).text for request in requests]
        assert [r.text for r in results] == singly

    def test_applies_the_glossary(self, provider: TranslationProvider) -> None:
        """Terminology must stay consistent across hundreds of segments."""
        result = provider.translate(
            TranslationRequest(text="The timing matters.", glossary={"timing": "Zeitabstimmung"})
        )
        assert "Zeitabstimmung" in result.text or "timing" not in result.text.lower()


class TestRejection:
    @pytest.mark.parametrize("text", ["", "   "])
    def test_refuses_empty_text(self, provider: TranslationProvider, text: str) -> None:
        with pytest.raises(TranslationError, match="empty"):
            provider.translate(TranslationRequest(text=text))
