from pathlib import Path
import json

from abr.tts.command_backend import (
    GoogleCloudTTSBackend,
    _elevenlabs_output_format_from_path,
    _get_google_quota_project_from_adc,
    _google_audio_encoding_from_path,
    _response_format_from_path,
)


def test_response_format_from_path_wav() -> None:
    assert _response_format_from_path(Path("speech.wav")) == "wav"


def test_response_format_from_path_mp3() -> None:
    assert _response_format_from_path(Path("speech.mp3")) == "mp3"


def test_elevenlabs_output_format_from_path_mp3() -> None:
    assert _elevenlabs_output_format_from_path(Path("speech.mp3")) == "mp3_44100_128"


def test_google_audio_encoding_from_path_wav() -> None:
    assert _google_audio_encoding_from_path(Path("speech.wav")) == "LINEAR16"


def test_google_audio_encoding_from_path_mp3() -> None:
    assert _google_audio_encoding_from_path(Path("speech.mp3")) == "MP3"


def test_get_google_quota_project_from_adc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_dir = tmp_path / ".config" / "gcloud"
    config_dir.mkdir(parents=True)
    (config_dir / "application_default_credentials.json").write_text(
        '{"quota_project_id": "project-123"}',
        encoding="utf-8",
    )

    assert _get_google_quota_project_from_adc() == "project-123"


def test_google_backend_reuses_cached_access_token(monkeypatch) -> None:
    backend = GoogleCloudTTSBackend("de-DE-Standard-H")
    issued_tokens = iter([("token-1", 3300.0), ("token-2", 3300.0)])

    monkeypatch.setattr("abr.tts.command_backend._get_google_access_token", lambda: next(issued_tokens))
    monkeypatch.setattr("abr.tts.command_backend._get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.tts.command_backend.urllib.request.urlopen", lambda request: None)

    assert backend._get_access_token() == "token-1"
    assert backend._get_access_token() == "token-1"


def test_google_backend_refreshes_expired_cached_access_token(monkeypatch) -> None:
    backend = GoogleCloudTTSBackend("de-DE-Standard-H")
    issued_tokens = iter([("token-1", 30.0), ("token-2", 3300.0)])

    monkeypatch.setattr("abr.tts.command_backend._get_google_access_token", lambda: next(issued_tokens))

    assert backend._get_access_token() == "token-1"
    assert backend._get_access_token() == "token-2"


def test_google_backend_sends_ssml_payload(monkeypatch, tmp_path: Path) -> None:
    backend = GoogleCloudTTSBackend("de-DE-Standard-A")
    captured_request = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"audioContent": "UklGRg=="}).encode("utf-8")

    def _fake_urlopen(request):
        captured_request["body"] = request.data.decode("utf-8")
        captured_request["headers"] = dict(request.header_items())
        return _FakeResponse()

    monkeypatch.setattr("abr.tts.command_backend._get_google_access_token", lambda: ("token-1", 3300.0))
    monkeypatch.setattr("abr.tts.command_backend._get_google_quota_project", lambda: None)
    monkeypatch.setattr("abr.tts.command_backend.urllib.request.urlopen", _fake_urlopen)

    output_path = tmp_path / "warnung.wav"
    backend.synthesize_to_file(
        '<speak>Bitte warten.<break time="500ms"/>Scan startet.</speak>',
        output_path,
        input_type="ssml",
    )

    body = json.loads(captured_request["body"])
    assert body["input"] == {
        "ssml": '<speak>Bitte warten.<break time="500ms"/>Scan startet.</speak>'
    }
    assert output_path.exists()
