from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSBackend(ABC):
    @abstractmethod
    def speak(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        *,
        input_type: str = "text",
    ) -> Path:
        raise NotImplementedError

    def supports_file_playback(self) -> bool:
        return False

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        raise RuntimeError("This TTS backend does not support file playback.")
