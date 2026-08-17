from __future__ import annotations

from abr.language_config import LANGUAGE_PROFILES
from hardware.control_panel_service import (
    PROJECT_ROOT,
    _build_page_speech_config,
    _build_parser,
    _build_system_audio_config,
)


def test_control_panel_uses_unchanged_german_tts_defaults() -> None:
    args = _build_parser().parse_args([])

    config = _build_page_speech_config(args, LANGUAGE_PROFILES["de"])

    assert config.language_code == "de"
    assert config.chapter_label == "Kapitel"
    assert config.google_tts_language_code == "de-DE"
    assert config.google_tts_voice_name == "de-DE-Standard-H"
    assert config.google_neural2_voice_name == "de-DE-Neural2-H"
    assert config.elevenlabs_language_code == "de"
    assert config.google_gemini_flash_prompt.startswith("Lies den folgenden deutschen Buchtext")


def test_control_panel_uses_us_english_tts_profile() -> None:
    args = _build_parser().parse_args([])

    config = _build_page_speech_config(args, LANGUAGE_PROFILES["en"])

    assert config.language_code == "en"
    assert config.chapter_label == "Chapter"
    assert config.google_tts_language_code == "en-US"
    assert config.google_tts_voice_name == "en-US-Standard-D"
    assert config.google_neural2_voice_name == "en-US-Neural2-D"
    assert config.elevenlabs_language_code == "en"
    assert config.google_gemini_flash_prompt.startswith("Read the following English book text")


def test_control_panel_selects_system_messages_for_active_language() -> None:
    german_config = _build_system_audio_config(LANGUAGE_PROFILES["de"])
    english_config = _build_system_audio_config(LANGUAGE_PROFILES["en"])

    assert german_config.root_dir == PROJECT_ROOT / "system_audio" / "messages" / "de"
    assert english_config.root_dir == PROJECT_ROOT / "system_audio" / "messages" / "en"


def test_explicit_voice_and_prompt_overrides_still_win_over_profile() -> None:
    args = _build_parser().parse_args(
        [
            "--google-standard-voice-name",
            "en-US-Standard-A",
            "--google-neural2-voice-name",
            "en-US-Neural2-A",
            "--google-gemini-flash-prompt",
            "Custom prompt",
        ]
    )

    config = _build_page_speech_config(args, LANGUAGE_PROFILES["en"])

    assert config.google_tts_voice_name == "en-US-Standard-A"
    assert config.google_neural2_voice_name == "en-US-Neural2-A"
    assert config.google_gemini_flash_prompt == "Custom prompt"
