"""English to German translation using Argos Translate.

Argos is the default local translation provider because it is the only credible option that
is CPU-only and small enough to install without a GPU stack. The port means swapping it for
a larger model, or an LLM with a duration-constrained prompt, touches nothing outside this
file (questions.md Q-C4).

The model is downloaded on first use and cached; nothing is sent over the network at
translation time.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Final

from germandubi.application.ports.providers import (
    ProviderInfo,
    ProviderKind,
    TranslationRequest,
    TranslationResult,
)
from germandubi.domain.errors import ProviderUnavailableError, TranslationError

__all__ = ["ArgosTranslationProvider"]

logger = logging.getLogger(__name__)

# Argos logs every tokenization and hypothesis at INFO, which buries the application's own
# progress output. Its logger is quietened here rather than globally.
logging.getLogger("argostranslate").setLevel(logging.WARNING)

_SOURCE: Final = "en"
_TARGET: Final = "de"


class ArgosTranslationProvider:
    """Translates segments with a locally installed Argos model."""

    def __init__(self, *, auto_install: bool = True) -> None:
        """Initialise the provider.

        Args:
            auto_install: Whether to download the English-German model on first use.
        """
        self.auto_install = auto_install
        self._translation: Any | None = None
        # Model loading is not thread-safe and the API process may call this concurrently.
        self._lock = threading.Lock()

    @property
    def info(self) -> ProviderInfo:
        """Return the provider's identity."""
        return ProviderInfo(
            id="argos",
            name="Argos Translate (English to German)",
            kind=ProviderKind.LOCAL,
            model_id="argos-en_de",
            deterministic=True,
            requires=("argostranslate",),
            notes="Runs locally on the CPU. The model is downloaded once, then cached.",
        )

    def is_available(self) -> bool:
        """Return whether the Argos package and its dependency stack are importable."""
        try:
            import argostranslate.translate  # noqa: F401
        except Exception:
            # Optional ML packages can be installed yet unusable because a transitive
            # dependency is incompatible with this Python version or platform. Provider
            # discovery must degrade to the fake/fallback provider instead of preventing
            # the application (or the default test suite) from starting.
            logger.debug("Argos Translate is installed but cannot be imported", exc_info=True)
            return False
        return True

    def _load(self) -> Any:
        """Return the loaded English-to-German translation, installing the model if needed.

        Raises:
            ProviderUnavailableError: If the package is missing or the model cannot be
                obtained.
        """
        with self._lock:
            if self._translation is not None:
                return self._translation
            try:
                # Bind the submodules directly rather than reaching through the parent
                # package. A half-present installation can leave the parent importable
                # while a submodule is missing; attribute access would then raise
                # AttributeError past this handler, while `from ... import` raises
                # ImportError and degrades to the fallback as intended.
                from argostranslate import package as argos_package
                from argostranslate import translate as argos_translate
            except Exception as exc:
                msg = (
                    "Argos Translate is unavailable. Install or repair the optional "
                    "translation extra: `uv sync --extra translate`."
                )
                raise ProviderUnavailableError(msg) from exc

            translation = self._find_installed(argos_translate)
            if translation is None and self.auto_install:
                self._install_model(argos_package)
                translation = self._find_installed(argos_translate)
            if translation is None:
                msg = (
                    "no English to German Argos model is installed and it could not be "
                    "downloaded. Check the network connection, or install the model "
                    "manually."
                )
                raise ProviderUnavailableError(msg)
            self._translation = translation
            return translation

    @staticmethod
    def _find_installed(translate_module: Any) -> Any | None:
        """Return the installed en-de translation, or ``None``."""
        languages = translate_module.get_installed_languages()
        source = next((lang for lang in languages if lang.code == _SOURCE), None)
        target = next((lang for lang in languages if lang.code == _TARGET), None)
        if source is None or target is None:
            return None
        try:
            return source.get_translation(target)
        except Exception:
            return None

    @staticmethod
    def _install_model(package_module: Any) -> None:
        """Download and install the English-to-German model.

        Raises:
            ProviderUnavailableError: If the model cannot be downloaded.
        """
        logger.info("downloading the Argos English to German model; this happens once")
        try:
            package_module.update_package_index()
            available = package_module.get_available_packages()
            wanted = next(
                (p for p in available if p.from_code == _SOURCE and p.to_code == _TARGET), None
            )
            if wanted is None:
                msg = "the Argos package index does not offer an English to German model"
                raise ProviderUnavailableError(msg)
            package_module.install_from_path(wanted.download())
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            msg = f"could not download the Argos English to German model: {exc}"
            raise ProviderUnavailableError(msg) from exc

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate one segment into German.

        Args:
            request: The text and its context. ``max_characters`` is best-effort: this
                model has no length control, so an over-long result is returned as-is and
                the duration-fitting stage decides what to do about it.

        Returns:
            The German rendering.

        Raises:
            TranslationError: If translation fails or returns nothing.
            ProviderUnavailableError: If the model is not installed.
        """
        text = request.text.strip()
        if not text:
            msg = "cannot translate empty text"
            raise TranslationError(msg)

        translation = self._load()
        try:
            german = str(translation.translate(text)).strip()
        except Exception as exc:
            msg = f"translation failed: {exc}"
            raise TranslationError(msg, text=text[:120]) from exc

        if not german:
            msg = "the translation model returned no German text"
            raise TranslationError(msg, text=text[:120])

        german = _apply_glossary(german, request.glossary)
        return TranslationResult(text=german, provider_id=self.info.id, model_id=self.info.model_id)

    def translate_batch(self, requests: list[TranslationRequest]) -> list[TranslationResult]:
        """Translate several segments.

        The model is loaded once for the whole batch, which dominates the per-segment cost.

        Args:
            requests: The segments to translate.

        Returns:
            One result per request, in order.
        """
        self._load()
        return [self.translate(request) for request in requests]


def _apply_glossary(german: str, glossary: dict[str, str]) -> str:
    """Force agreed terminology onto the model's output.

    A general translation model will not reliably keep a product name or a technical term
    consistent across hundreds of segments, so the glossary is applied afterwards rather
    than hoped for in a prompt this model does not accept.

    Matching is case-insensitive and on word boundaries, because the terms a glossary
    targets - loanwords, product names, proper nouns - are exactly the ones the model
    leaves untranslated but re-cases, turning "timing" into "Timing".

    This can only correct a term the model left recognizable. A term the model translated
    to a different German word is beyond post-hoc replacement; that needs a provider with
    real terminology control, and is tracked as question Q-C4.
    """
    result = german
    for english, replacement in glossary.items():
        if not english or english == replacement:
            continue
        result = re.sub(rf"\b{re.escape(english)}\b", replacement, result, flags=re.IGNORECASE)
    return result
