from __future__ import annotations

from pathlib import Path

from abr.system_audio import SystemAudioConfig, play_system_message, synthesize_system_message
from abr.tts.base import TTSBackend


class _RecordingBackend(TTSBackend):
    def __init__(self) -> None:
        self.synth_calls: list[tuple[str, Path, str]] = []

    def speak(self, text: str) -> None:
        raise NotImplementedError

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        self.synth_calls.append((text, output_path, input_type))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return output_path

    def supports_file_playback(self) -> bool:
        return True


def test_synthesize_system_message_writes_under_configured_root(tmp_path: Path) -> None:
    from abr import system_audio as system_audio_module

    backend = _RecordingBackend()
    original = system_audio_module.create_system_tts_backend
    system_audio_module.create_system_tts_backend = lambda config, require_playback=False: backend
    try:
        output_path = synthesize_system_message(
            "Scan gestartet.",
            "scan_start",
            config=SystemAudioConfig(root_dir=tmp_path / "system_audio"),
        )
    finally:
        system_audio_module.create_system_tts_backend = original

    assert output_path == (tmp_path / "system_audio" / "scan_start.wav").resolve()
    assert output_path.read_text(encoding="utf-8") == "Scan gestartet."
    assert backend.synth_calls == [("Scan gestartet.", output_path, "text")]


def test_synthesize_system_message_can_forward_ssml(tmp_path: Path) -> None:
    from abr import system_audio as system_audio_module

    backend = _RecordingBackend()
    original = system_audio_module.create_system_tts_backend
    system_audio_module.create_system_tts_backend = lambda config, require_playback=False: backend
    try:
        output_path = synthesize_system_message(
            '<speak>Bitte warten.<break time="700ms"/>Scan startet.</speak>',
            "scan_start_ssml",
            use_ssml=True,
            config=SystemAudioConfig(root_dir=tmp_path / "system_audio"),
        )
    finally:
        system_audio_module.create_system_tts_backend = original

    assert output_path == (tmp_path / "system_audio" / "scan_start_ssml.wav").resolve()
    assert backend.synth_calls == [
        ('<speak>Bitte warten.<break time="700ms"/>Scan startet.</speak>', output_path, "ssml")
    ]


def test_play_system_message_uses_audio_playback_helper(tmp_path: Path) -> None:
    from abr import system_audio as system_audio_module

    audio_path = (tmp_path / "system_audio" / "warnung.wav").resolve()
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_text("Warnung", encoding="utf-8")

    recorded_calls: list[tuple[Path, int, object]] = []
    original = system_audio_module.play_audio_file
    system_audio_module.play_audio_file = lambda path, volume_percent=100, volume_provider=None: recorded_calls.append(
        (path, volume_percent, volume_provider)
    )
    try:
        played_path = play_system_message(
            "warnung",
            config=SystemAudioConfig(root_dir=tmp_path / "system_audio"),
            volume_percent=64,
        )
    finally:
        system_audio_module.play_audio_file = original

    assert played_path == audio_path
    assert recorded_calls == [(audio_path, 64, None)]


def test_play_system_message_uses_configured_language_directory(tmp_path: Path) -> None:
    from abr import system_audio as system_audio_module

    german_path = (tmp_path / "messages" / "de" / "fehler.wav").resolve()
    english_path = (tmp_path / "messages" / "en" / "fehler.wav").resolve()
    german_path.parent.mkdir(parents=True)
    english_path.parent.mkdir(parents=True)
    german_path.write_text("Deutsch", encoding="utf-8")
    english_path.write_text("English", encoding="utf-8")

    recorded_paths: list[Path] = []
    original = system_audio_module.play_audio_file
    system_audio_module.play_audio_file = lambda path, **kwargs: recorded_paths.append(path)
    try:
        played_path = play_system_message(
            "fehler",
            config=SystemAudioConfig(root_dir=tmp_path / "messages" / "en"),
        )
    finally:
        system_audio_module.play_audio_file = original

    assert played_path == english_path
    assert recorded_paths == [english_path]


def test_synthesize_system_message_rejects_path_escape(tmp_path: Path) -> None:
    try:
        synthesize_system_message(
            "Hallo",
            "../ausbruch",
            config=SystemAudioConfig(root_dir=tmp_path / "system_audio"),
        )
    except ValueError as exc:
        assert "ausserhalb" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Pfad-Ausbruch wurde nicht blockiert.")
