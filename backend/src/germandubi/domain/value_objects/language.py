"""Language identity.

``0.x`` supports exactly one direction: English to German. The enum exists so that the
direction is stated explicitly in signatures and persisted data rather than assumed, and so
that adding a pair later is a contained change instead of an audit of every string literal.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = ["SOURCE_LANGUAGE", "SUPPORTED_PAIRS", "TARGET_LANGUAGE", "LanguageCode"]


class LanguageCode(StrEnum):
    """An ISO 639-1 language code known to the application."""

    ENGLISH = "en"
    GERMAN = "de"

    @property
    def display_name(self) -> str:
        """Return the English name of the language, for UI labels."""
        return {LanguageCode.ENGLISH: "English", LanguageCode.GERMAN: "German"}[self]


SOURCE_LANGUAGE: Final = LanguageCode.ENGLISH
TARGET_LANGUAGE: Final = LanguageCode.GERMAN

#: The language pairs this version can actually dub. See questions.md section A.
SUPPORTED_PAIRS: Final[frozenset[tuple[LanguageCode, LanguageCode]]] = frozenset(
    {(LanguageCode.ENGLISH, LanguageCode.GERMAN)}
)
