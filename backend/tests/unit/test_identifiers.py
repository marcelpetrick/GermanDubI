"""ULID identifiers: validity, ordering and the embedded timestamp."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from germandubi.domain.value_objects.identifiers import Ulid, new_id


class TestGeneration:
    def test_generated_ids_are_twenty_six_characters(self) -> None:
        assert len(new_id()) == 26

    def test_generated_ids_are_unique(self) -> None:
        assert len({new_id() for _ in range(2000)}) == 2000

    def test_ids_sort_in_creation_order(self) -> None:
        """Lexicographic order must match time order; ORDER BY id depends on it."""
        earlier = Ulid.generate(timestamp_ms=1_700_000_000_000)
        later = Ulid.generate(timestamp_ms=1_700_000_001_000)
        assert earlier < later

    @given(st.integers(min_value=0, max_value=2**48 - 1))
    def test_the_embedded_timestamp_round_trips(self, timestamp_ms: int) -> None:
        assert Ulid.generate(timestamp_ms=timestamp_ms).timestamp_ms == timestamp_ms


class TestValidation:
    def test_accepts_a_well_formed_id(self) -> None:
        generated = new_id()
        assert Ulid(str(generated)) == generated

    def test_normalises_to_upper_case(self) -> None:
        generated = new_id()
        assert Ulid(str(generated).lower()) == generated

    @pytest.mark.parametrize(
        "bad",
        ["", "too-short", "0" * 25, "0" * 27, "I" * 26, "0" * 25 + "U"],
        ids=["empty", "short", "25-chars", "27-chars", "excluded-letter-I", "excluded-letter-U"],
    )
    def test_rejects_malformed_ids(self, bad: str) -> None:
        with pytest.raises(ValueError, match="not a valid ULID"):
            Ulid(bad)

    def test_ids_are_usable_as_plain_strings(self) -> None:
        """Subclassing str is what keeps identifiers trivially serializable."""
        generated = new_id()
        assert isinstance(generated, str)
        lookup: dict[str, int] = {generated: 1}
        assert lookup[str(generated)] == 1
