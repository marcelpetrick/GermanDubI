"""Application-level error taxonomy.

Infrastructure exceptions are wrapped in these types with domain context, so that the UI
and the retry logic behave stably even when a third-party library changes its exception
types (``docs/product/vision.md`` section 59).

Every error carries a stable ``code`` used by the HTTP layer and the frontend, and an
optional ``details`` mapping for machine-readable context. Error messages are shown to the
user, so they state what went wrong and, where possible, what to do about it.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AlignmentError",
    "CancelledError",
    "CaptionError",
    "ConfigurationError",
    "DomainError",
    "DurationFitError",
    "ExportError",
    "GermanDubIError",
    "InvalidStateTransitionError",
    "MediaProcessingError",
    "MixError",
    "NotFoundError",
    "ProviderUnavailableError",
    "ResourceError",
    "SeparationError",
    "SourceAcquisitionError",
    "SourceValidationError",
    "SynthesisError",
    "TranscriptionError",
    "TranslationError",
]


class GermanDubIError(Exception):
    """Base class for every error this application raises deliberately.

    Attributes:
        code: Stable machine-readable identifier, used by the HTTP error model.
        message: Human-readable explanation, shown to the user.
        details: Additional machine-readable context.
    """

    code = "internal_error"

    def __init__(self, message: str, /, **details: Any) -> None:
        """Initialise the error.

        Args:
            message: Human-readable explanation.
            **details: Machine-readable context attached to the error.
        """
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details

    def __str__(self) -> str:
        """Return the human-readable message."""
        return self.message


class DomainError(GermanDubIError):
    """A domain invariant was violated."""

    code = "domain_error"


class InvalidStateTransitionError(DomainError):
    """A lifecycle transition was requested that the state machine does not allow."""

    code = "invalid_state_transition"


class NotFoundError(GermanDubIError):
    """A referenced entity does not exist."""

    code = "not_found"


class ConfigurationError(GermanDubIError):
    """The application or a provider is misconfigured."""

    code = "configuration_error"


class ResourceError(GermanDubIError):
    """A required resource - disk space, memory, a model file - is unavailable."""

    code = "resource_error"


class ProviderUnavailableError(ResourceError):
    """A provider implementation is not installed or cannot be initialised."""

    code = "provider_unavailable"


class CancelledError(GermanDubIError):
    """Work stopped because cancellation was requested."""

    code = "cancelled"


# --- Pipeline stage errors -------------------------------------------------------------


class SourceValidationError(GermanDubIError):
    """The requested source is not acceptable, for example a disallowed URL."""

    code = "source_validation_error"


class SourceAcquisitionError(GermanDubIError):
    """The source media could not be downloaded or read."""

    code = "source_acquisition_error"


class MediaProcessingError(GermanDubIError):
    """An FFmpeg operation failed or produced unusable output."""

    code = "media_processing_error"


class CaptionError(GermanDubIError):
    """Captions were unavailable, malformed or unusable."""

    code = "caption_error"


class TranscriptionError(GermanDubIError):
    """Automatic speech recognition failed."""

    code = "transcription_error"


class AlignmentError(GermanDubIError):
    """Word-level alignment failed or produced implausible timing."""

    code = "alignment_error"


class TranslationError(GermanDubIError):
    """English to German translation failed."""

    code = "translation_error"


class SeparationError(GermanDubIError):
    """Voice/background separation failed."""

    code = "separation_error"


class SynthesisError(GermanDubIError):
    """German speech synthesis failed."""

    code = "synthesis_error"


class DurationFitError(GermanDubIError):
    """Synthesized speech could not be fitted into its timeline interval."""

    code = "duration_fit_error"


class MixError(GermanDubIError):
    """Assembling or mixing the German audio track failed."""

    code = "mix_error"


class ExportError(GermanDubIError):
    """Muxing or writing the final output file failed."""

    code = "export_error"
