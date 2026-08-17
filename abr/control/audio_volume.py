from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from threading import RLock


_PERCENT_RE = re.compile(r"\[(\d{1,3})%\]")
_SIMPLE_CONTROL_RE = re.compile(r"Simple mixer control '([^']+)'")
_PREFERRED_AUTO_CONTROLS = ("Master", "Speaker", "PCM", "Headphone", "Digital")


@dataclass(frozen=True)
class AudioVolumeConfig:
    mixer_command: str = "amixer"
    mixer_control: str = "auto"
    min_percent: int = 20
    max_percent: int = 100
    step_count: int = 10
    default_percent: int = 100

    def __post_init__(self) -> None:
        if self.min_percent < 0 or self.max_percent > 100 or self.min_percent >= self.max_percent:
            raise ValueError("Ungueltiger Lautstaerkebereich.")
        if self.step_count < 2:
            raise ValueError("step_count muss >= 2 sein.")
        if not self.min_percent <= self.default_percent <= self.max_percent:
            raise ValueError("default_percent muss innerhalb des Lautstaerkebereichs liegen.")
        if not self.mixer_control.strip():
            raise ValueError("mixer_control darf nicht leer sein.")


@dataclass(frozen=True)
class AudioVolumeState:
    level_index: int
    level_count: int
    percent: int


class AudioVolumeController:
    def __init__(self, config: AudioVolumeConfig = AudioVolumeConfig()) -> None:
        self.config = config
        self.levels = _build_volume_levels(
            self.config.min_percent,
            self.config.max_percent,
            self.config.step_count,
        )
        self._current_index: int | None = None
        self._current_percent = self.config.default_percent
        self._resolved_mixer_command: str | None = None
        self._resolved_mixer_control: str | None = None
        self._software_only = False
        self._lock = RLock()

    def initialize(self) -> AudioVolumeState:
        current_percent = self._read_current_percent()
        if current_percent is None:
            current_percent = self.config.default_percent
        return self.set_percent(current_percent)

    def apply_delta(self, delta: int) -> AudioVolumeState | None:
        state = self.request_delta(delta)
        if state is None:
            return None
        return self.apply_requested_volume()

    def request_delta(self, delta: int) -> AudioVolumeState | None:
        """Change only the in-memory target; safe for a GPIO edge callback."""
        if delta == 0:
            return None
        with self._lock:
            if self._current_index is None:
                self._current_index = _nearest_level_index(self.levels, self._current_percent)
            target_index = min(max(self._current_index + delta, 0), len(self.levels) - 1)
            self._current_index = target_index
            self._current_percent = self.levels[target_index]
            return self._state()

    def apply_requested_volume(self) -> AudioVolumeState:
        """Apply the current target to an ALSA mixer outside the GPIO callback."""
        with self._lock:
            percent = self._current_percent
        self._write_percent(percent)
        with self._lock:
            return self._state()

    def set_percent(self, percent: int) -> AudioVolumeState:
        target_index = _nearest_level_index(self.levels, percent)
        return self.set_level_index(target_index)

    def set_level_index(self, level_index: int) -> AudioVolumeState:
        if level_index < 0 or level_index >= len(self.levels):
            raise ValueError("level_index ausserhalb des gueltigen Bereichs.")
        with self._lock:
            percent = self.levels[level_index]
            self._current_index = level_index
            self._current_percent = percent
        self._write_percent(percent)
        with self._lock:
            return self._state()

    def current_percent(self) -> int:
        with self._lock:
            return self._current_percent

    def current_state(self) -> AudioVolumeState:
        with self._lock:
            if self._current_index is None:
                self._current_index = _nearest_level_index(self.levels, self._current_percent)
            return self._state()

    def uses_software_volume(self) -> bool:
        return self._software_only

    def _state(self) -> AudioVolumeState:
        assert self._current_index is not None
        return AudioVolumeState(
            level_index=self._current_index,
            level_count=len(self.levels),
            percent=self.levels[self._current_index],
        )

    def _read_current_percent(self) -> int | None:
        control = self._resolve_mixer_control()
        if control is None:
            return self._current_percent
        result = self._run_mixer_command("get", control)
        percents = [int(match.group(1)) for match in _PERCENT_RE.finditer(result.stdout)]
        if not percents:
            return None
        return round(sum(percents) / len(percents))

    def _write_percent(self, percent: int) -> None:
        control = self._resolve_mixer_control()
        if control is None:
            return
        self._run_mixer_command("sset", control, f"{percent}%")

    def _resolve_mixer_control(self) -> str | None:
        if self._resolved_mixer_control is not None or self._software_only:
            return self._resolved_mixer_control

        requested = self.config.mixer_control.strip()
        available_controls = self._list_mixer_controls()
        if requested.lower() != "auto":
            if requested not in available_controls:
                available_text = ", ".join(available_controls) if available_controls else "keine"
                raise RuntimeError(
                    f"ALSA-Mixer-Control nicht gefunden: {requested}. Verfuegbar: {available_text}."
                )
            self._resolved_mixer_control = requested
            return requested

        for control in _ordered_auto_controls(available_controls):
            try:
                result = self._run_mixer_command("get", control)
            except subprocess.CalledProcessError:
                continue
            if _PERCENT_RE.search(result.stdout):
                self._resolved_mixer_control = control
                return control

        self._software_only = True
        return None

    def _list_mixer_controls(self) -> tuple[str, ...]:
        result = self._run_mixer_command("scontrols")
        controls: list[str] = []
        for match in _SIMPLE_CONTROL_RE.finditer(result.stdout):
            control = match.group(1).strip()
            if control and control not in controls:
                controls.append(control)
        return tuple(controls)

    def _run_mixer_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._resolve_mixer_command(), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _resolve_mixer_command(self) -> str:
        if self._resolved_mixer_command is None:
            command = shutil.which(self.config.mixer_command)
            if not command:
                raise RuntimeError(f"Mixer-Kommando nicht gefunden: {self.config.mixer_command}")
            self._resolved_mixer_command = command
        return self._resolved_mixer_command


def _build_volume_levels(min_percent: int, max_percent: int, step_count: int) -> tuple[int, ...]:
    if step_count == 2:
        return (min_percent, max_percent)
    levels = [
        round(min_percent + ((max_percent - min_percent) * index) / (step_count - 1))
        for index in range(step_count)
    ]
    levels[0] = min_percent
    levels[-1] = max_percent
    return tuple(levels)


def _nearest_level_index(levels: tuple[int, ...], percent: int) -> int:
    return min(
        range(len(levels)),
        key=lambda index: (abs(levels[index] - percent), index),
    )


def _ordered_auto_controls(available_controls: tuple[str, ...]) -> tuple[str, ...]:
    preferred = [control for control in _PREFERRED_AUTO_CONTROLS if control in available_controls]
    others = [control for control in available_controls if control not in preferred]
    return tuple(preferred + others)
