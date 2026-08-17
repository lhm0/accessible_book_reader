from __future__ import annotations

from base64 import b64encode
import json
from pathlib import Path

from abr.tts.command_backend import (
    GoogleCloudTTSBackend,
    GoogleGeminiFlashTTSBackend,
    GoogleNeural2TTSBackend,
    SayBackend,
    _ssml_to_say_text,
    create_tts_backend,
)


def test_ssml_to_say_text_converts_breaks_to_pause_markers() -> None:
    rendered = _ssml_to_say_text(
        '<speak>Bitte warten.<break time="700ms"/>Scan startet.<break time="900ms"/>Jetzt.</speak>'
    )

    assert rendered == "Bitte warten.\nScan startet.\n\nJetzt."


def test_say_backend_can_render_ssml_to_wav(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(command: list[str], check: bool = False, **_: object) -> None:
        calls.append(command)
        if command[0] == "/usr/bin/say":
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_bytes(b"AIFF")
            return
        if command[0] == "/usr/bin/afconvert":
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_bytes(b"WAVE")
            return
        raise AssertionError(f"Unerwartetes Kommando: {command}")

    monkeypatch.setattr("abr.tts.command_backend.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "abr.tts.command_backend.shutil.which",
        lambda name: "/usr/bin/afconvert" if name == "afconvert" else None,
    )

    backend = SayBackend("/usr/bin/say", voice="Anna", speed=1.0, playback_binary="/usr/bin/afplay")
    output_path = tmp_path / "buch_loeschen.wav"

    backend.synthesize_to_file(
        '<speak>Buch löschen.<break time="700ms"/>Achtung.</speak>',
        output_path,
        input_type="ssml",
    )

    assert output_path.exists()
    assert output_path.read_bytes() == b"WAVE"
    assert len(calls) == 2
    assert calls[0][0] == "/usr/bin/say"
    assert calls[1][0] == "/usr/bin/afconvert"
    assert calls[0][-1] == "Buch löschen.\nAchtung."


def test_google_backend_keeps_existing_standard_voice_path(monkeypatch) -> None:
    monkeypatch.setattr("abr.tts.command_backend.shutil.which", lambda _: None)

    backend = create_tts_backend(
        "google",
        google_tts_voice_name="de-DE-Standard-H",
        google_tts_language_code="de-DE",
    )

    assert type(backend) is GoogleCloudTTSBackend
    assert backend.voice_name == "de-DE-Standard-H"


def test_google_standard_enhanced_uses_same_standard_voice_backend(monkeypatch) -> None:
    monkeypatch.setattr("abr.tts.command_backend.shutil.which", lambda _: None)

    backend = create_tts_backend(
        "google-standard-enhanced",
        google_tts_voice_name="de-DE-Standard-H",
        google_tts_language_code="de-DE",
    )

    assert type(backend) is GoogleCloudTTSBackend
    assert backend.voice_name == "de-DE-Standard-H"


def test_google_neural2_backend_is_separate_and_opt_in(monkeypatch) -> None:
    monkeypatch.setattr("abr.tts.command_backend.shutil.which", lambda _: None)

    backend = create_tts_backend(
        "google-neural2",
        google_tts_language_code="de-DE",
    )

    assert type(backend) is GoogleNeural2TTSBackend
    assert backend.voice_name == "de-DE-Neural2-H"


def test_google_gemini_flash_backend_sends_model_prompt_and_plain_text(monkeypatch, tmp_path: Path) -> None:
    requests = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"audioContent": b64encode(b"WAVE").decode("ascii")}).encode("utf-8")

    monkeypatch.setattr("abr.tts.command_backend.shutil.which", lambda _: None)
    monkeypatch.setattr("abr.tts.command_backend._get_google_quota_project", lambda: "test-project")
    monkeypatch.setattr(
        "abr.tts.command_backend.urllib.request.urlopen",
        lambda request: requests.append(request) or _Response(),
    )
    backend = create_tts_backend(
        "google-gemini-flash",
        speed=0.85,
        google_tts_language_code="de-DE",
        google_gemini_flash_voice_name="Charon",
        google_gemini_flash_prompt="Lies wie ein ruhiger Hoerbuchsprecher.",
    )
    assert type(backend) is GoogleGeminiFlashTTSBackend
    monkeypatch.setattr(backend, "_get_access_token", lambda: "token")

    output_path = backend.synthesize_to_file("Ein kurzer Buchtext.", tmp_path / "gemini.wav")

    payload = json.loads(requests[0].data.decode("utf-8"))
    assert payload["input"]["text"] == "Ein kurzer Buchtext."
    assert payload["input"]["prompt"].endswith("85 Prozent des normalen Tempos.")
    assert payload["voice"] == {
        "languageCode": "de-DE",
        "name": "Charon",
        "modelName": "gemini-2.5-flash-tts",
    }
    assert payload["audioConfig"] == {"audioEncoding": "LINEAR16"}
    assert requests[0].headers["X-goog-user-project"] == "test-project"
    assert output_path.read_bytes() == b"WAVE"
