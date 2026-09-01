"""Content and configuration hashing.

Two things in this application are keyed by hash. Artifacts are identified by the hash of
their **bytes**, which is what makes "this file is unchanged" cheap to answer. Pipeline
steps are keyed by the hash of their **inputs**, which is what makes the pipeline
idempotent: if a valid artifact already exists for the same input hash, the step is skipped
rather than recomputed (``docs/product/vision.md`` section 13).

The input hash must therefore cover everything that can change the output - text, provider,
model, and configuration - and nothing that cannot, such as wall-clock time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

__all__ = ["ContentHash", "hash_bytes", "hash_file", "hash_inputs", "hash_text"]

_ALGORITHM: Final = "sha256"
_CHUNK_SIZE: Final = 1024 * 1024

#: A hash rendered as ``sha256:<hex>``. The algorithm prefix is kept so that stored hashes
#: stay interpretable if the algorithm is ever changed.
ContentHash = str


def _render(digest: str) -> ContentHash:
    """Return a digest with its algorithm prefix."""
    return f"{_ALGORITHM}:{digest}"


def hash_bytes(payload: bytes) -> ContentHash:
    """Hash an in-memory payload.

    Args:
        payload: The bytes to hash.

    Returns:
        The prefixed hash.
    """
    return _render(hashlib.sha256(payload).hexdigest())


def hash_text(text: str) -> ContentHash:
    """Hash a string using its UTF-8 encoding.

    Args:
        text: The text to hash.

    Returns:
        The prefixed hash.
    """
    return hash_bytes(text.encode("utf-8"))


def hash_file(path: Path) -> ContentHash:
    """Hash a file's contents by streaming it.

    Media files are far too large to read into memory, so the file is consumed in chunks.

    Args:
        path: The file to hash.

    Returns:
        The prefixed hash.

    Raises:
        OSError: If the file cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return _render(digest.hexdigest())


def hash_inputs(**inputs: Any) -> ContentHash:
    """Hash the complete set of inputs that determine a pipeline step's output.

    The inputs are serialized as canonical JSON - sorted keys, no insignificant whitespace -
    so that the hash depends on the values and not on dictionary ordering or formatting.

    Args:
        **inputs: Every value that can change the output: source text, target language,
            provider id, model id, and the relevant configuration. Values must be
            JSON-serializable; anything else is rendered via ``repr``, which is stable for
            the enums and dataclasses used here.

    Returns:
        The prefixed hash.

    Example:
        >>> a = hash_inputs(text="Hello", provider="fake", model="v1")
        >>> b = hash_inputs(model="v1", provider="fake", text="Hello")
        >>> a == b
        True
    """
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=repr)
    return hash_text(canonical)
