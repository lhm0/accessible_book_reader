from __future__ import annotations

from html import unescape
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from base64 import b64decode
from pathlib import Path

from abr.google_cloud_auth import (
    get_google_access_token as _shared_get_google_access_token,
    get_google_quota_project as _shared_get_google_quota_project,
    get_google_quota_project_from_adc as _shared_get_google_quota_project_from_adc,
)
from abr.tts.base import TTSBackend


class EspeakBackend(TTSBackend):
    def __init__(self, binary: str, playback_binary: str | None = None, speed: float = 1.0) -> None:
        self.binary = binary
        self.playback_binary = playback_binary
        self.speed = speed

    def speak(self, text: str) -> None:
        if self.playback_binary:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                output_path = Path(handle.name)
            try:
                self.synthesize_to_file(text, output_path)
                subprocess.run([self.playback_binary, str(output_path)], check=True)
            finally:
                output_path.unlink(missing_ok=True)
            return
        subprocess.run([self.binary, text], check=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        _ensure_text_input_type("eSpeak", input_type)
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([self.binary, "-s", str(_words_per_minute(self.speed)), "-w", str(output_path), text], check=True)
        return output_path

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("eSpeak playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)


class SayBackend(TTSBackend):
    def __init__(
        self,
        binary: str,
        voice: str | None = None,
        speed: float = 1.0,
        playback_binary: str | None = None,
    ) -> None:
        self.binary = binary
        self.voice = voice
        self.speed = speed
        self.playback_binary = playback_binary

    def speak(self, text: str) -> None:
        subprocess.run(self._build_command(text), check=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        if input_type == "text":
            rendered_text = text
        elif input_type == "ssml":
            rendered_text = _ssml_to_say_text(text)
        else:
            raise RuntimeError(f"Unbekannter TTS-Eingabetyp: {input_type}")
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() in {".aiff", ".aif"}:
            command = self._build_command(rendered_text)
            command[1:1] = ["-o", str(output_path)]
            subprocess.run(command, check=True)
            return output_path

        afconvert_binary = shutil.which("afconvert")
        if not afconvert_binary:
            raise RuntimeError("macOS `say` kann ohne `afconvert` nur `.aiff` ausgeben.")

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as handle:
            temp_aiff_path = Path(handle.name)
        try:
            command = self._build_command(rendered_text)
            command[1:1] = ["-o", str(temp_aiff_path)]
            subprocess.run(command, check=True)
            subprocess.run(
                [
                    afconvert_binary,
                    str(temp_aiff_path),
                    "-o",
                    str(output_path),
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16",
                ],
                check=True,
            )
        finally:
            temp_aiff_path.unlink(missing_ok=True)
        return output_path

    def _build_command(self, text: str) -> list[str]:
        command = [self.binary, "-r", str(_words_per_minute(self.speed))]
        if self.voice:
            command.extend(["-v", self.voice])
        command.append(text)
        return command

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".aiff"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("macOS `say` playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)


class PiperBackend(TTSBackend):
    def __init__(
        self,
        binary: str,
        model_path: Path,
        playback_binary: str | None = None,
        speed: float = 1.0,
    ) -> None:
        self.binary = binary
        self.model_path = Path(model_path).expanduser().resolve()
        self.playback_binary = playback_binary
        self.speed = speed

    def speak(self, text: str) -> None:
        if not self.playback_binary:
            raise RuntimeError("Piper playback requested but no playback command is available.")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            self.synthesize_to_file(text, output_path)
            subprocess.run([self.playback_binary, str(output_path)], check=True)
        finally:
            output_path.unlink(missing_ok=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        _ensure_text_input_type("Piper", input_type)
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                self.binary,
                "--model",
                str(self.model_path),
                "--output_file",
                str(output_path),
                "--length-scale",
                str(_piper_length_scale(self.speed)),
            ],
            input=text.encode("utf-8"),
            check=True,
        )
        return output_path

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("Piper playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)


class OpenAIBackend(TTSBackend):
    API_URL = "https://api.openai.com/v1/audio/speech"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        speed: float = 1.0,
        playback_binary: str | None = None,
        instructions: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.speed = speed
        self.playback_binary = playback_binary
        self.instructions = instructions

    def speak(self, text: str) -> None:
        if not self.playback_binary:
            raise RuntimeError("OpenAI playback requested but no playback command is available.")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            self.synthesize_to_file(text, output_path)
            subprocess.run([self.playback_binary, str(output_path)], check=True)
        finally:
            output_path.unlink(missing_ok=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        _ensure_text_input_type("OpenAI TTS", input_type)
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response_format = _response_format_from_path(output_path)
        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": response_format,
            "speed": max(0.25, min(4.0, self.speed)),
        }
        if self.instructions:
            payload["instructions"] = self.instructions

        request = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                audio_bytes = response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI TTS request failed: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI TTS request failed: {exc.reason}") from exc

        output_path.write_bytes(audio_bytes)
        return output_path

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("OpenAI playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)


class ElevenLabsBackend(TTSBackend):
    API_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={output_format}"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        playback_binary: str | None = None,
        language_code: str | None = None,
        speed: float = 1.0,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.playback_binary = playback_binary
        self.language_code = language_code
        self.speed = speed

    def speak(self, text: str) -> None:
        if not self.playback_binary:
            raise RuntimeError("ElevenLabs playback requested but no playback command is available.")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            self.synthesize_to_file(text, output_path)
            subprocess.run([self.playback_binary, str(output_path)], check=True)
        finally:
            output_path.unlink(missing_ok=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        _ensure_text_input_type("ElevenLabs TTS", input_type)
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_format = _elevenlabs_output_format_from_path(output_path)
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "speed": max(0.7, min(1.2, self.speed)),
            },
        }
        if self.language_code:
            payload["language_code"] = self.language_code

        api_url = self.API_URL_TEMPLATE.format(voice_id=self.voice_id, output_format=output_format)
        request = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                audio_bytes = response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ElevenLabs TTS request failed: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ElevenLabs TTS request failed: {exc.reason}") from exc

        output_path.write_bytes(audio_bytes)
        return output_path

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".mp3"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("ElevenLabs playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)


class GoogleCloudTTSBackend(TTSBackend):
    API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def __init__(
        self,
        voice_name: str,
        language_code: str = "de-DE",
        speed: float = 1.0,
        playback_binary: str | None = None,
    ) -> None:
        self.voice_name = voice_name
        self.language_code = language_code
        self.speed = speed
        self.playback_binary = playback_binary
        self._cached_token: str | None = None
        self._cached_token_expires_at: float | None = None

    def speak(self, text: str) -> None:
        if not self.playback_binary:
            raise RuntimeError("Google Cloud TTS playback requested but no playback command is available.")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            self.synthesize_to_file(text, output_path)
            subprocess.run([self.playback_binary, str(output_path)], check=True)
        finally:
            output_path.unlink(missing_ok=True)

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        token = self._get_access_token()
        quota_project = _get_google_quota_project()
        audio_encoding = _google_audio_encoding_from_path(output_path)
        if input_type == "text":
            synthesis_input = {"text": text}
        elif input_type == "ssml":
            synthesis_input = {"ssml": text}
        else:
            raise RuntimeError(f"Unbekannter TTS-Eingabetyp: {input_type}")
        payload = {
            "input": synthesis_input,
            "voice": {
                "languageCode": self.language_code,
                "name": self.voice_name,
            },
            "audioConfig": {
                "audioEncoding": audio_encoding,
                "speakingRate": max(0.25, min(2.0, self.speed)),
            },
        }
        request = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
                **({"x-goog-user-project": quota_project} if quota_project else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Cloud TTS request failed: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google Cloud TTS request failed: {exc.reason}") from exc

        audio_content = response_payload.get("audioContent")
        if not audio_content:
            raise RuntimeError("Google Cloud TTS returned no audio content.")
        output_path.write_bytes(b64decode(audio_content))
        return output_path

    def supports_file_playback(self) -> bool:
        return self.playback_binary is not None

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        if not self.playback_binary:
            raise RuntimeError("Google Cloud TTS playback requested but no playback command is available.")
        subprocess.run([self.playback_binary, str(audio_path)], check=True)

    def _get_access_token(self) -> str:
        now = time.monotonic()
        if (
            self._cached_token
            and self._cached_token_expires_at is not None
            and now < self._cached_token_expires_at - 60.0
        ):
            return self._cached_token

        token, expires_in_sec = _get_google_access_token()
        self._cached_token = token
        self._cached_token_expires_at = now + expires_in_sec
        return token


class GoogleNeural2TTSBackend(GoogleCloudTTSBackend):
    """Opt-in Neural2 path kept separate from the established Google backend."""

    DEFAULT_VOICE_NAME = "de-DE-Neural2-H"

    def __init__(
        self,
        voice_name: str = DEFAULT_VOICE_NAME,
        language_code: str = "de-DE",
        speed: float = 1.0,
        playback_binary: str | None = None,
    ) -> None:
        super().__init__(
            voice_name=voice_name,
            language_code=language_code,
            speed=speed,
            playback_binary=playback_binary,
        )


class GoogleGeminiFlashTTSBackend(GoogleCloudTTSBackend):
    """Opt-in Gemini TTS path; the established Google backend remains unchanged."""

    DEFAULT_MODEL_NAME = "gemini-2.5-flash-tts"
    DEFAULT_VOICE_NAME = "Charon"
    DEFAULT_PROMPT = (
        "Lies den folgenden deutschen Buchtext ruhig, klar und natuerlich vor. "
        "Beruecksichtige Bedeutung, Satzstruktur und Dialoge. Verwende eine warme, "
        "zurueckhaltende Hoerbuchintonation ohne uebertriebene Schauspielerei. "
        "Setze an Absatz- und Kapitelgrenzen gut wahrnehmbare Pausen."
    )
    MAX_INPUT_BYTES = 4000

    def __init__(
        self,
        voice_name: str = DEFAULT_VOICE_NAME,
        language_code: str = "de-DE",
        speed: float = 1.0,
        playback_binary: str | None = None,
        model_name: str = DEFAULT_MODEL_NAME,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        super().__init__(
            voice_name=voice_name,
            language_code=language_code,
            speed=speed,
            playback_binary=playback_binary,
        )
        self.model_name = model_name
        self.prompt = prompt

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        _ensure_text_input_type("Google Gemini Flash TTS", input_type)
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("Google Gemini Flash TTS benoetigt nichtleeren Text.")
        effective_prompt = self._effective_prompt()
        self._validate_input_size("Text", normalized_text)
        self._validate_input_size("Prompt", effective_prompt)

        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        token = self._get_access_token()
        quota_project = _get_google_quota_project()
        payload = {
            "input": {
                "text": normalized_text,
                "prompt": effective_prompt,
            },
            "voice": {
                "languageCode": self.language_code,
                "name": self.voice_name,
                "modelName": self.model_name,
            },
            "audioConfig": {
                "audioEncoding": _google_audio_encoding_from_path(output_path),
            },
        }
        request = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
                **({"x-goog-user-project": quota_project} if quota_project else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Gemini Flash TTS request failed: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google Gemini Flash TTS request failed: {exc.reason}") from exc

        audio_content = response_payload.get("audioContent")
        if not audio_content:
            raise RuntimeError("Google Gemini Flash TTS returned no audio content.")
        output_path.write_bytes(b64decode(audio_content))
        return output_path

    def _effective_prompt(self) -> str:
        if self.speed == 1.0:
            return self.prompt
        percent = round(max(0.25, min(2.0, self.speed)) * 100)
        return f"{self.prompt} Sprich mit ungefaehr {percent} Prozent des normalen Tempos."

    def _validate_input_size(self, label: str, value: str) -> None:
        size = len(value.encode("utf-8"))
        if size > self.MAX_INPUT_BYTES:
            raise RuntimeError(
                f"Google Gemini Flash TTS: {label} ist mit {size} Byte groesser "
                f"als das Limit von {self.MAX_INPUT_BYTES} Byte."
            )


def create_tts_backend(
    name: str,
    model_path: str | None = None,
    voice: str | None = None,
    require_playback: bool = False,
    speed: float = 1.0,
    openai_model: str | None = None,
    openai_instructions: str | None = None,
    elevenlabs_voice_id: str | None = None,
    elevenlabs_model_id: str | None = None,
    elevenlabs_language_code: str | None = None,
    google_tts_voice_name: str | None = None,
    google_tts_language_code: str | None = None,
    google_neural2_voice_name: str | None = None,
    google_gemini_flash_voice_name: str | None = None,
    google_gemini_flash_prompt: str | None = None,
) -> TTSBackend:
    normalized = name.strip().lower()
    playback_binary = shutil.which("afplay") or shutil.which("aplay") or shutil.which("paplay")

    if normalized in {"auto", "piper"}:
        piper_binary = shutil.which("piper")
        if piper_binary and model_path and playback_binary:
            return PiperBackend(piper_binary, Path(model_path), playback_binary, speed=speed)
        if piper_binary and model_path and not require_playback:
            return PiperBackend(piper_binary, Path(model_path), playback_binary=None, speed=speed)
        if normalized == "piper":
            raise RuntimeError("Piper requested but `piper`, a playback command, or `--tts-model` is missing.")

    if normalized in {"auto", "espeak"}:
        espeak_binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak_binary:
            return EspeakBackend(espeak_binary, playback_binary=playback_binary, speed=speed)
        if normalized == "espeak":
            raise RuntimeError("eSpeak requested but neither `espeak-ng` nor `espeak` is installed.")

    if normalized in {"auto", "say"}:
        say_binary = shutil.which("say")
        if say_binary:
            return SayBackend(say_binary, voice=voice, speed=speed, playback_binary=playback_binary)
        if normalized == "say":
            raise RuntimeError("`say` requested but the macOS `say` command is not available.")

    if normalized == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OpenAI TTS requested but `OPENAI_API_KEY` is not set.")
        return OpenAIBackend(
            api_key=api_key,
            model=openai_model or "gpt-4o-mini-tts",
            voice=voice or "alloy",
            speed=speed,
            playback_binary=playback_binary,
            instructions=openai_instructions,
        )

    if normalized == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise RuntimeError("ElevenLabs TTS requested but `ELEVENLABS_API_KEY` is not set.")
        if not elevenlabs_voice_id:
            raise RuntimeError("ElevenLabs TTS requested but `--elevenlabs-voice-id` is missing.")
        return ElevenLabsBackend(
            api_key=api_key,
            voice_id=elevenlabs_voice_id,
            model_id=elevenlabs_model_id or "eleven_multilingual_v2",
            playback_binary=playback_binary,
            language_code=elevenlabs_language_code,
            speed=speed,
        )

    if normalized in {"google", "google-standard-enhanced"}:
        if not google_tts_voice_name:
            raise RuntimeError("Google Cloud TTS requested but `--google-tts-voice-name` is missing.")
        return GoogleCloudTTSBackend(
            voice_name=google_tts_voice_name,
            language_code=google_tts_language_code or "de-DE",
            speed=speed,
            playback_binary=playback_binary,
        )

    if normalized == "google-neural2":
        return GoogleNeural2TTSBackend(
            voice_name=google_neural2_voice_name or GoogleNeural2TTSBackend.DEFAULT_VOICE_NAME,
            language_code=google_tts_language_code or "de-DE",
            speed=speed,
            playback_binary=playback_binary,
        )

    if normalized == "google-gemini-flash":
        return GoogleGeminiFlashTTSBackend(
            voice_name=google_gemini_flash_voice_name or GoogleGeminiFlashTTSBackend.DEFAULT_VOICE_NAME,
            language_code=google_tts_language_code or "de-DE",
            speed=speed,
            playback_binary=playback_binary,
            prompt=google_gemini_flash_prompt or GoogleGeminiFlashTTSBackend.DEFAULT_PROMPT,
        )

    raise RuntimeError("No compatible TTS backend available.")


def _piper_length_scale(speed: float) -> float:
    safe_speed = max(speed, 0.1)
    return round(1.0 / safe_speed, 3)


def _words_per_minute(speed: float, base_wpm: int = 175) -> int:
    safe_speed = max(speed, 0.1)
    return max(80, int(base_wpm * safe_speed))


def _response_format_from_path(output_path: Path) -> str:
    extension_map = {
        ".mp3": "mp3",
        ".wav": "wav",
        ".flac": "flac",
        ".aac": "aac",
        ".opus": "opus",
        ".pcm": "pcm",
    }
    response_format = extension_map.get(output_path.suffix.lower())
    if not response_format:
        raise RuntimeError(
            f"Unsupported OpenAI audio format for `{output_path.suffix}`. Use one of: {', '.join(extension_map)}."
        )
    return response_format


def _elevenlabs_output_format_from_path(output_path: Path) -> str:
    extension_map = {
        ".mp3": "mp3_44100_128",
    }
    response_format = extension_map.get(output_path.suffix.lower())
    if not response_format:
        raise RuntimeError("ElevenLabs currently expects an `.mp3` output path in this workflow.")
    return response_format


def _ensure_text_input_type(backend_name: str, input_type: str) -> None:
    if input_type == "text":
        return
    if input_type == "ssml":
        raise RuntimeError(f"{backend_name} unterstuetzt in diesem Projekt aktuell kein SSML.")
    raise RuntimeError(f"Unbekannter TTS-Eingabetyp: {input_type}")


def _ssml_to_say_text(ssml: str) -> str:
    try:
        root = ET.fromstring(ssml)
    except ET.ParseError as exc:
        raise RuntimeError(f"Ungueltiges SSML fuer `say`: {exc}") from exc

    if _xml_local_name(root.tag) != "speak":
        raise RuntimeError("SSML fuer `say` muss mit <speak> beginnen.")

    parts: list[str] = []

    def _append_text(value: str | None) -> None:
        if value:
            parts.append(unescape(value))

    def _visit(node: ET.Element) -> None:
        _append_text(node.text)
        for child in node:
            local_name = _xml_local_name(child.tag)
            if local_name == "break":
                parts.append(_say_pause_marker_from_break(child.attrib.get("time")))
            else:
                _visit(child)
            _append_text(child.tail)

    _visit(root)
    rendered = "".join(parts)
    rendered = re.sub(r"[ \t\r\f\v]+", " ", rendered)
    rendered = re.sub(r" *\n *", "\n", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    rendered = rendered.strip()
    if not rendered:
        raise RuntimeError("SSML fuer `say` ergibt keinen sprechbaren Text.")
    return rendered


def _say_pause_marker_from_break(time_value: str | None) -> str:
    seconds = _parse_ssml_break_time(time_value)
    if seconds is None:
        return "\n"
    if seconds < 0.35:
        return ", "
    if seconds < 0.8:
        return "\n"
    return "\n\n"


def _parse_ssml_break_time(time_value: str | None) -> float | None:
    if not time_value:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s)\s*", time_value, flags=re.IGNORECASE)
    if not match:
        return None
    magnitude = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "ms":
        return magnitude / 1000.0
    return magnitude


def _xml_local_name(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def _google_audio_encoding_from_path(output_path: Path) -> str:
    extension_map = {
        ".wav": "LINEAR16",
        ".mp3": "MP3",
    }
    response_format = extension_map.get(output_path.suffix.lower())
    if not response_format:
        raise RuntimeError("Google Cloud TTS currently expects a `.wav` or `.mp3` output path in this workflow.")
    return response_format


def _get_google_access_token() -> tuple[str, float]:
    return _shared_get_google_access_token()


def _get_google_quota_project() -> str | None:
    return _shared_get_google_quota_project()


def _get_google_quota_project_from_adc() -> str | None:
    return _shared_get_google_quota_project_from_adc()
