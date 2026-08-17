from __future__ import annotations

import json

import pytest

from abr.language_config import (
    LANGUAGE_PROFILES,
    LanguageConfigStore,
    get_language_profile,
    main,
)


def test_missing_configuration_defaults_to_existing_german_values(tmp_path) -> None:
    profile = LanguageConfigStore(tmp_path / "device.json").load()

    assert profile == LANGUAGE_PROFILES["de"]
    assert profile.google_tts_language_code == "de-DE"
    assert profile.google_standard_voice_name == "de-DE-Standard-H"
    assert profile.google_neural2_voice_name == "de-DE-Neural2-H"
    assert profile.chapter_label == "Kapitel"


def test_us_english_profile_contains_explicit_us_values() -> None:
    profile = get_language_profile("en")

    assert profile.display_name == "English (United States)"
    assert profile.ocr_language == "en"
    assert profile.google_tts_language_code == "en-US"
    assert profile.google_standard_voice_name.startswith("en-US-")
    assert profile.google_neural2_voice_name.startswith("en-US-")
    assert profile.chapter_label == "Chapter"


def test_configuration_is_saved_atomically_with_private_permissions(tmp_path) -> None:
    path = tmp_path / "config" / "device.json"
    store = LanguageConfigStore(path)

    saved = store.save("en")

    assert saved == LANGUAGE_PROFILES["en"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1, "language": "en"}
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix(".json.tmp").exists()
    assert store.load() == LANGUAGE_PROFILES["en"]


def test_init_does_not_overwrite_existing_language(tmp_path) -> None:
    store = LanguageConfigStore(tmp_path / "device.json")
    store.save("en")

    assert store.ensure_exists() == LANGUAGE_PROFILES["en"]
    assert store.load() == LANGUAGE_PROFILES["en"]


def test_invalid_persisted_language_fails_loudly(tmp_path) -> None:
    path = tmp_path / "device.json"
    path.write_text('{"version": 1, "language": "fr"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="Nicht unterstuetzte Buchsprache"):
        LanguageConfigStore(path).load()


def test_cli_status_reports_default_without_creating_file(tmp_path, capsys) -> None:
    path = tmp_path / "device.json"

    assert main(["--config", str(path), "status"]) == 0

    output = capsys.readouterr().out
    assert "Aktive Buchsprache: Deutsch (de)" in output
    assert "de-DE-Standard-H" in output
    assert not path.exists()
