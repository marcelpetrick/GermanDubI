"""Source URL validation - the application's main untrusted input."""

from __future__ import annotations

import pytest

from germandubi.domain.errors import SourceValidationError
from germandubi.domain.value_objects.source_url import (
    extract_youtube_video_id,
    validate_source_url,
)

VALID = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
]

REJECTED = [
    pytest.param("", "no source URL", id="empty"),
    pytest.param("   ", "no source URL", id="whitespace-only"),
    pytest.param("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "only https", id="plain-http"),
    pytest.param("ftp://youtube.com/x", "only https", id="ftp"),
    pytest.param("file:///etc/passwd", "only https", id="file-scheme"),
    pytest.param("https://evil.example.com/watch?v=x", "not supported", id="foreign-host"),
    pytest.param("https://youtube.com.evil.test/watch?v=x", "not supported", id="suffix-spoof"),
    pytest.param("https://127.0.0.1/watch?v=x", "not an IP address", id="loopback-ip"),
    pytest.param("https://169.254.169.254/latest/meta-data", "not an IP address", id="link-local"),
    pytest.param("https://10.0.0.5/watch?v=x", "not an IP address", id="private-range"),
    pytest.param("https://[::1]/watch?v=x", "not an IP address", id="ipv6-loopback"),
    pytest.param("https://localhost/watch?v=x", "not supported", id="localhost"),
    pytest.param("https://user:pw@www.youtube.com/watch?v=x", "credentials", id="credentials"),
    pytest.param("https://www.youtube.com/watch?v=x\nX-Injected: 1", "whitespace", id="crlf"),
    pytest.param("https://" + "a" * 3000, "longer than", id="over-long"),
]


class TestAcceptance:
    @pytest.mark.parametrize("url", VALID)
    def test_accepts_supported_youtube_urls(self, url: str) -> None:
        assert validate_source_url(url).value == url

    def test_trims_surrounding_whitespace(self) -> None:
        assert validate_source_url("  https://youtu.be/dQw4w9WgXcQ  ").video_id == "dQw4w9WgXcQ"

    def test_is_case_insensitive_about_the_host(self) -> None:
        assert validate_source_url("https://WWW.YouTube.com/watch?v=dQw4w9WgXcQ").video_id


class TestRejection:
    @pytest.mark.parametrize(("url", "reason"), REJECTED)
    def test_rejects_unsupported_or_dangerous_urls(self, url: str, reason: str) -> None:
        with pytest.raises(SourceValidationError, match=reason):
            validate_source_url(url)

    def test_the_rejection_error_does_not_echo_an_unbounded_url(self) -> None:
        with pytest.raises(SourceValidationError) as caught:
            validate_source_url("https://" + "a" * 5000)
        assert len(caught.value.details["url"]) <= 2048


class TestVideoIdExtraction:
    @pytest.mark.parametrize("url", VALID)
    def test_extracts_the_id_from_every_supported_form(self, url: str) -> None:
        assert extract_youtube_video_id(url) == "dQw4w9WgXcQ"

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/@somechannel",
            "https://www.youtube.com/watch?v=too-short",
        ],
    )
    def test_returns_none_when_the_url_is_not_a_single_video(self, url: str) -> None:
        assert extract_youtube_video_id(url) is None

    def test_a_playlist_url_is_still_accepted_but_carries_no_video_id(self) -> None:
        """Accepting it lets the probe report a useful error instead of a validation error."""
        assert validate_source_url("https://www.youtube.com/playlist?list=PL123").video_id is None
