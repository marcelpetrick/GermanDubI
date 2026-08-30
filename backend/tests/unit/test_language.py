from germandubi.domain.value_objects.language import LanguageCode


def test_language_display_names_are_human_readable() -> None:
    assert LanguageCode.ENGLISH.display_name == "English"
    assert LanguageCode.GERMAN.display_name == "German"
