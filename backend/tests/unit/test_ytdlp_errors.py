import pytest

from germandubi.infrastructure.providers.ytdlp import _explain


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("removed", "removed"),
        ("age-restricted", "age-restricted"),
        ("confirm your age", "age-restricted"),
        ("sign in", "signing in"),
        ("not available in your country", "blocked"),
        ("unable to download webpage", "could not be reached"),
        # Says both things it can mean, because the words alone do not distinguish them.
        ("ERROR: [youtube] abc: This video is not available", "germandubi doctor"),
    ],
)
def test_ytdlp_errors_are_classified_without_substring_collisions(
    message: str, expected: str
) -> None:
    assert expected in _explain(message)
