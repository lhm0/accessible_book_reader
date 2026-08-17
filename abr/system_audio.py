from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from abr.audio_playback import play_audio_file
from abr.tts import TTSBackend, create_tts_backend

DEFAULT_SYSTEM_AUDIO_ROOT = Path("system_audio/messages")
DEFAULT_SYSTEM_TTS_BACKEND = "google"
DEFAULT_SYSTEM_GOOGLE_VOICE = "de-DE-Standard-A"
DEFAULT_SYSTEM_GOOGLE_LANGUAGE = "de-DE"
DEFAULT_SYSTEM_TTS_SPEED = 0.9


@dataclass(frozen=True)
class SystemAudioConfig:
    root_dir: Path = DEFAULT_SYSTEM_AUDIO_ROOT
    tts_backend: str = DEFAULT_SYSTEM_TTS_BACKEND
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_speed: float = DEFAULT_SYSTEM_TTS_SPEED
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_instructions: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_language_code: str = "de"
    google_tts_voice_name: str = DEFAULT_SYSTEM_GOOGLE_VOICE
    google_tts_language_code: str = DEFAULT_SYSTEM_GOOGLE_LANGUAGE

    def __post_init__(self) -> None:
        if self.tts_speed <= 0:
            raise ValueError("tts_speed muss > 0 sein.")


def create_system_tts_backend(
    config: SystemAudioConfig = SystemAudioConfig(),
    *,
    require_playback: bool = False,
) -> TTSBackend:
    return create_tts_backend(
        config.tts_backend,
        model_path=str(config.tts_model) if config.tts_model is not None else None,
        voice=config.tts_voice,
        require_playback=require_playback,
        speed=config.tts_speed,
        openai_model=config.openai_tts_model,
        openai_instructions=config.openai_tts_instructions,
        elevenlabs_voice_id=config.elevenlabs_voice_id,
        elevenlabs_model_id=config.elevenlabs_model_id,
        elevenlabs_language_code=config.elevenlabs_language_code,
        google_tts_voice_name=config.google_tts_voice_name,
        google_tts_language_code=config.google_tts_language_code,
    )


def synthesize_system_message(
    text: str,
    filename: str | Path,
    *,
    use_ssml: bool = False,
    config: SystemAudioConfig = SystemAudioConfig(),
) -> Path:
    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("text darf nicht leer sein.")

    backend = create_system_tts_backend(config)
    output_path = resolve_system_message_path(
        filename,
        root_dir=config.root_dir,
        default_suffix=_default_audio_suffix(config.tts_backend),
    )
    backend.synthesize_to_file(
        normalized_text,
        output_path,
        input_type="ssml" if use_ssml else "text",
    )
    return output_path


def play_system_message(
    message_name_or_path: str | Path,
    *,
    config: SystemAudioConfig = SystemAudioConfig(),
    volume_percent: int = 100,
    volume_provider: Callable[[], int] | None = None,
) -> Path:
    audio_path = resolve_system_message_path(
        message_name_or_path,
        root_dir=config.root_dir,
        default_suffix=_default_audio_suffix(config.tts_backend),
    )
    if not audio_path.exists():
        raise RuntimeError(f"Audio-Botschaft nicht gefunden: {audio_path}")

    play_audio_file(audio_path, volume_percent=volume_percent, volume_provider=volume_provider)
    return audio_path


def resolve_system_message_path(
    message_name_or_path: str | Path,
    *,
    root_dir: Path,
    default_suffix: str,
) -> Path:
    root_dir = root_dir.expanduser().resolve()
    input_path = Path(message_name_or_path).expanduser()
    if input_path.is_absolute():
        resolved_path = input_path.resolve()
    else:
        candidate = root_dir / input_path
        if candidate.suffix == "":
            candidate = candidate.with_suffix(default_suffix)
        resolved_path = candidate.resolve()
        try:
            resolved_path.relative_to(root_dir)
        except ValueError as exc:
            raise ValueError(f"Dateiname liegt ausserhalb von {root_dir}: {message_name_or_path}") from exc

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def _default_audio_suffix(tts_backend: str) -> str:
    normalized = tts_backend.strip().lower()
    if normalized == "say":
        return ".aiff"
    if normalized == "elevenlabs":
        return ".mp3"
    return ".wav"
