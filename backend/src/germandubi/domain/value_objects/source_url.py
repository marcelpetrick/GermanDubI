"""Validation of user-supplied source URLs.

The URL is one of the two genuinely untrusted inputs to this application (the other is the
media it points at). A URL reaches ``yt-dlp``, which will happily follow it, so validation
happens here in the domain - before any acquisition code exists - and is enforced by tests.

The policy for ``0.x`` is an allowlist, not a denylist: only ``https`` and only known
YouTube hostnames. Everything else is refused. See ``SECURITY.md`` and ``docs/product/vision.md``
section 22.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import ParseResult, parse_qs, urlparse

from germandubi.domain.errors import SourceValidationError

__all__ = ["ALLOWED_HOSTS", "SourceUrl", "extract_youtube_video_id", "validate_source_url"]

#: Hostnames the application will hand to the downloader. Deliberately explicit.
ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)

_ALLOWED_SCHEME: Final = "https"
_YOUTUBE_ID: Final = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MAX_URL_LENGTH: Final = 2048


@dataclass(frozen=True, slots=True)
class SourceUrl:
    """A URL that has passed validation and may be handed to the downloader.

    Constructing this type is the only way to obtain a URL the acquisition layer accepts,
    so an unvalidated string cannot reach ``yt-dlp`` by accident.

    Attributes:
        value: The normalised URL string.
        video_id: The extracted YouTube video id, when the URL identifies a single video.
    """

    value: str
    video_id: str | None

    def __str__(self) -> str:
        """Return the validated URL string."""
        return self.value


def _reject(reason: str, url: str) -> SourceValidationError:
    """Build the rejection error, without echoing the full URL back into the message."""
    return SourceValidationError(reason, url=url[:_MAX_URL_LENGTH])


def _host_is_a_network_address(hostname: str) -> bool:
    """Return whether the hostname is a bare IP address rather than a name."""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _check_scheme_and_credentials(parsed: ParseResult, url: str) -> None:
    """Reject non-HTTPS URLs and URLs carrying embedded credentials.

    Raises:
        SourceValidationError: If the scheme is not ``https`` or credentials are present.
    """
    if parsed.scheme != _ALLOWED_SCHEME:
        msg = f"only {_ALLOWED_SCHEME} source URLs are accepted, got {parsed.scheme or 'none'!r}"
        raise _reject(msg, url)
    if parsed.username or parsed.password:
        msg = "source URLs must not contain embedded credentials"
        raise _reject(msg, url)


def _check_host(parsed: ParseResult, url: str) -> str:
    """Return the validated hostname.

    Raises:
        SourceValidationError: If the host is missing, an IP literal, or not allowlisted.
    """
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise _reject("source URL has no host", url)
    if _host_is_a_network_address(hostname):
        # A bare address can point at the loopback or a private network; the allowlist
        # already excludes it, but rejecting explicitly gives a clearer message.
        raise _reject("source URLs must name a host, not an IP address", url)
    if hostname not in ALLOWED_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_HOSTS))
        msg = f"host {hostname!r} is not supported; this version accepts: {allowed}"
        raise _reject(msg, url)
    return hostname


def extract_youtube_video_id(url: str) -> str | None:
    """Extract the eleven-character video id from a YouTube URL.

    Args:
        url: An already-validated YouTube URL.

    Returns:
        The video id, or ``None`` when the URL points at something other than a single
        video, such as a playlist or a channel.
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname.endswith("youtu.be"):
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
        return candidate if _YOUTUBE_ID.match(candidate) else None

    if parsed.path == "/watch":
        candidates = parse_qs(parsed.query).get("v", [])
        return candidates[0] if candidates and _YOUTUBE_ID.match(candidates[0]) else None

    for prefix in ("/embed/", "/v/", "/shorts/", "/live/"):
        if parsed.path.startswith(prefix):
            candidate = parsed.path[len(prefix) :].split("/", 1)[0]
            return candidate if _YOUTUBE_ID.match(candidate) else None

    return None


def validate_source_url(raw: str) -> SourceUrl:
    """Validate a user-supplied source URL against the allowlist policy.

    Args:
        raw: The URL as typed by the user.

    Returns:
        The validated :class:`SourceUrl`.

    Raises:
        SourceValidationError: If the URL is empty, over-long, malformed, not HTTPS,
            carries credentials, or does not name an allowlisted YouTube host.
    """
    url = raw.strip()
    if not url:
        raise _reject("no source URL was provided", url)
    if len(url) > _MAX_URL_LENGTH:
        msg = f"source URL is longer than {_MAX_URL_LENGTH} characters"
        raise _reject(msg, url)
    if any(char.isspace() or ord(char) < 32 for char in url):
        raise _reject("source URL contains whitespace or control characters", url)

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise _reject(f"source URL could not be parsed: {exc}", url) from exc

    _check_scheme_and_credentials(parsed, url)
    _check_host(parsed, url)

    return SourceUrl(value=url, video_id=extract_youtube_video_id(url))
