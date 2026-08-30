"""Sortable, opaque entity identifiers.

Identifiers are ULIDs rendered in Crockford base32: a 48-bit millisecond timestamp
followed by 80 bits of randomness. Two properties matter here. They sort lexicographically
in creation order, which makes ``ORDER BY id`` meaningful and keeps SQLite index locality
good; and they can be generated client-side without a round trip to the database.

The 26-character encoding is implemented here with the standard library only, so that the
domain layer keeps its no-third-party-imports rule.
"""

from __future__ import annotations

import secrets
import time
from typing import Final, NewType, Self

__all__ = [
    "ArtifactId",
    "ExportId",
    "JobId",
    "ProjectId",
    "RunId",
    "SegmentId",
    "Ulid",
    "new_id",
]

# Crockford base32: no I, L, O or U, so the encoding resists transcription mistakes.
_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE: Final = {char: index for index, char in enumerate(_ALPHABET)}
_ULID_LENGTH: Final = 26
_TIMESTAMP_BITS: Final = 48
_RANDOM_BITS: Final = 80


class Ulid(str):
    """A 26-character Crockford-base32 ULID.

    Subclassing :class:`str` keeps identifiers trivially serializable and usable as
    dictionary keys and SQLite primary keys, while still giving the type checker something
    more specific than ``str``.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Self:
        """Create a validated identifier.

        Args:
            value: The candidate 26-character ULID string. Case-insensitive.

        Returns:
            The normalised, upper-case identifier.

        Raises:
            ValueError: If ``value`` is not a syntactically valid ULID.
        """
        normalised = value.upper()
        if len(normalised) != _ULID_LENGTH or any(c not in _DECODE for c in normalised):
            msg = f"not a valid ULID: {value!r}"
            raise ValueError(msg)
        return super().__new__(cls, normalised)

    @classmethod
    def generate(cls, *, timestamp_ms: int | None = None) -> Self:
        """Generate a new identifier.

        Args:
            timestamp_ms: Unix time in milliseconds to embed. Defaults to now. Supplying it
                explicitly makes tests deterministic in their ordering.

        Returns:
            A freshly generated identifier.
        """
        moment = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
        value = (moment << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)
        digits = []
        for _ in range(_ULID_LENGTH):
            value, remainder = divmod(value, len(_ALPHABET))
            digits.append(_ALPHABET[remainder])
        return cls("".join(reversed(digits)))

    @property
    def timestamp_ms(self) -> int:
        """Return the Unix millisecond timestamp embedded in this identifier."""
        value = 0
        for char in self:
            value = value * len(_ALPHABET) + _DECODE[char]
        return value >> _RANDOM_BITS


def new_id() -> Ulid:
    """Return a freshly generated identifier.

    Returns:
        A new :class:`Ulid`.
    """
    return Ulid.generate()


# Distinct aliases so a segment identifier cannot silently be passed where a project
# identifier is expected.
ProjectId = NewType("ProjectId", Ulid)
RunId = NewType("RunId", Ulid)
JobId = NewType("JobId", Ulid)
SegmentId = NewType("SegmentId", Ulid)
ArtifactId = NewType("ArtifactId", Ulid)
ExportId = NewType("ExportId", Ulid)
