"""Ports: the interfaces the application owns and providers implement.

No application or domain code may depend on a specific model implementation. Everything
goes through one of these Protocols, so a provider can be replaced when it becomes
obsolete, changes license, or breaks on a new CUDA version, without rewriting the
application (``vision.md`` section 3.5).

Every implementation must pass the shared contract suite in ``backend/tests/contract``.
"""

from germandubi.application.ports.providers import (
    AcquisitionProvider,
    AcquisitionRequest,
    AcquisitionResult,
    AlignmentProvider,
    MediaToolkit,
    ProbeProvider,
    Provider,
    ProviderInfo,
    ProviderKind,
    SeparationProvider,
    SeparationResult,
    SynthesisRequest,
    SynthesisResult,
    TranscriptionProvider,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TTSProvider,
)

__all__ = [
    "AcquisitionProvider",
    "AcquisitionRequest",
    "AcquisitionResult",
    "AlignmentProvider",
    "MediaToolkit",
    "ProbeProvider",
    "Provider",
    "ProviderInfo",
    "ProviderKind",
    "SeparationProvider",
    "SeparationResult",
    "SynthesisRequest",
    "SynthesisResult",
    "TTSProvider",
    "TranscriptionProvider",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
]
