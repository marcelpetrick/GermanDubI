"""Mapping application errors onto HTTP responses.

Every failure leaves through here, so the browser sees one error shape with a stable code
rather than a mix of FastAPI defaults and stack traces. Status codes are chosen from what
the client can do about the failure, not from where in the code it happened.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from germandubi.domain.errors import (
    CancelledError,
    ConfigurationError,
    DomainError,
    GermanDubIError,
    NotFoundError,
    ProviderUnavailableError,
    ResourceError,
    SourceValidationError,
)

__all__ = ["install_error_handlers"]

logger = logging.getLogger(__name__)

#: How each error class is reported. Anything unlisted is a bug and becomes a 500.
_STATUS_BY_TYPE: Final[list[tuple[type[GermanDubIError], int]]] = [
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (SourceValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ProviderUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (ConfigurationError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (ResourceError, status.HTTP_409_CONFLICT),
    (CancelledError, status.HTTP_409_CONFLICT),
    # DomainError last: it is the base of several of the above.
    (DomainError, status.HTTP_409_CONFLICT),
]


def _status_for(error: GermanDubIError) -> int:
    """Return the HTTP status that best describes what the client can do about an error."""
    for error_type, code in _STATUS_BY_TYPE:
        if isinstance(error, error_type):
            return code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def install_error_handlers(app: FastAPI) -> None:
    """Register the application's error handlers.

    Args:
        app: The FastAPI application.
    """

    @app.exception_handler(GermanDubIError)
    async def handle_known_error(_request: Request, exc: Exception) -> JSONResponse:
        """Return the standard error shape for an error this application raised."""
        assert isinstance(exc, GermanDubIError)  # noqa: S101 - guaranteed by the handler type
        code = _status_for(exc)
        if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.exception("unhandled application error", exc_info=exc)
        else:
            logger.info("%s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        """Return a generic error, without leaking internals to the browser."""
        logger.exception("unexpected error handling a request", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "internal_error",
                "message": "something went wrong. Check the server log for details.",
                "details": {},
            },
        )
