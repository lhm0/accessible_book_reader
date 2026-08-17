from __future__ import annotations

import shutil
import subprocess


CHANNEL_PINS = {
    "left": 12,
    "right": 13,
}


def resolve_pins(channel: str) -> list[int]:
    if channel == "both":
        return [CHANNEL_PINS["left"], CHANNEL_PINS["right"]]
    if channel in CHANNEL_PINS:
        return [CHANNEL_PINS[channel]]
    raise ValueError(f"Unbekannter LED-Kanal: {channel}")


def channel_label(channel: str) -> str:
    if channel == "both":
        return "LED-left und LED-right"
    if channel in CHANNEL_PINS:
        return f"LED-{channel}"
    raise ValueError(f"Unbekannter LED-Kanal: {channel}")


class LEDController:
    def __init__(self, pinctrl_path: str | None = None) -> None:
        self._pinctrl = pinctrl_path or shutil.which("pinctrl")
        if not self._pinctrl:
            raise RuntimeError(
                "Das Kommando 'pinctrl' wurde nicht gefunden. "
                "Dieses Skript ist fuer Raspberry Pi OS auf dem Pi 5 gedacht."
            )

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._pinctrl, *args],
            check=True,
            text=True,
            capture_output=True,
        )

    def set_channel(self, channel: str, is_on: bool) -> None:
        level = "dh" if is_on else "dl"
        for pin in resolve_pins(channel):
            self._run("set", str(pin), "op", level)

    def status_lines(self, channel: str) -> list[str]:
        return [self._run("get", str(pin)).stdout.strip() for pin in resolve_pins(channel)]
