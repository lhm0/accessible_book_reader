from __future__ import annotations

from collections.abc import Sequence
import re
import shutil
import subprocess
from typing import Callable, Protocol


ENCODER_A_PIN = 5
ENCODER_B_PIN = 6

BUTTON_PINS = {
    "encoder_button": 16,
    "start_stop_nfc": 17,
    "book_summary": 22,
    "chapter_summary": 24,
}

PIN_LABELS = {
    ENCODER_A_PIN: "EC11 A",
    ENCODER_B_PIN: "EC11 B",
    BUTTON_PINS["encoder_button"]: "EC11 Taster",
    BUTTON_PINS["start_stop_nfc"]: "Start / Stop / NFC",
    BUTTON_PINS["book_summary"]: "Buch-Zusammenfassung",
    BUTTON_PINS["chapter_summary"]: "Kapitel-/Letzte-Seiten-Zusammenfassung",
}

BUTTON_LABELS = {
    pin: PIN_LABELS[pin]
    for pin in (
        BUTTON_PINS["encoder_button"],
        BUTTON_PINS["start_stop_nfc"],
        BUTTON_PINS["book_summary"],
        BUTTON_PINS["chapter_summary"],
    )
}

CONTROL_PANEL_PINS = [
    ENCODER_A_PIN,
    ENCODER_B_PIN,
    BUTTON_PINS["encoder_button"],
    BUTTON_PINS["start_stop_nfc"],
    BUTTON_PINS["book_summary"],
    BUTTON_PINS["chapter_summary"],
]

_PINCTRL_LINE_RE = re.compile(r"^\s*(?P<pin>\d+)\s*:.*?\b(?P<level>hi|lo)\b", re.IGNORECASE)
_LEVEL_RE = re.compile(r"\b(?P<level>hi|lo)\b", re.IGNORECASE)


class InputGPIO(Protocol):
    def configure_inputs(self, pins: Sequence[int]) -> None: ...

    def read_levels(self, pins: Sequence[int]) -> dict[int, bool]: ...

    def add_edge_callback(self, pin: int, callback: Callable[[int], None]) -> bool: ...

    def remove_edge_callback(self, pin: int) -> None: ...

    def close(self) -> None: ...


def pin_label(pin: int) -> str:
    try:
        return PIN_LABELS[pin]
    except KeyError as exc:
        raise ValueError(f"Unbekannter Control-Panel-Pin: {pin}") from exc


def button_label(pin: int) -> str:
    try:
        return BUTTON_LABELS[pin]
    except KeyError as exc:
        raise ValueError(f"Unbekannter Taster-Pin: {pin}") from exc


def parse_pinctrl_levels(output: str) -> dict[int, bool]:
    levels: dict[int, bool] = {}
    for line in output.splitlines():
        match = _PINCTRL_LINE_RE.search(line)
        if match:
            levels[int(match.group("pin"))] = match.group("level").lower() == "hi"
    return levels


def parse_single_pinctrl_level(output: str) -> bool:
    match = _LEVEL_RE.search(output)
    if not match:
        raise RuntimeError(f"Konnte keinen GPIO-Pegel aus pinctrl-Ausgabe lesen: {output.strip()!r}")
    return match.group("level").lower() == "hi"


class PinctrlInputGPIO:
    def __init__(self, pinctrl_path: str | None = None) -> None:
        self._pinctrl = pinctrl_path or shutil.which("pinctrl")
        if not self._pinctrl:
            raise RuntimeError(
                "Das Kommando 'pinctrl' wurde nicht gefunden. "
                "Dieses Skript ist fuer Raspberry Pi OS auf dem Pi 5 gedacht."
            )
        self._supports_multi_get: bool | None = None

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._pinctrl, *args],
            check=True,
            text=True,
            capture_output=True,
        )

    def configure_input_pullup(self, pin: int) -> None:
        self._run("set", str(pin), "ip", "pu")

    def configure_inputs(self, pins: Sequence[int]) -> None:
        for pin in pins:
            self.configure_input_pullup(pin)

    def read_level(self, pin: int) -> bool:
        return parse_single_pinctrl_level(self._run("get", str(pin)).stdout)

    def read_levels(self, pins: Sequence[int]) -> dict[int, bool]:
        ordered_pins = list(dict.fromkeys(pins))
        if self._supports_multi_get is not False:
            try:
                output = self._run("get", *(str(pin) for pin in ordered_pins)).stdout
                levels = parse_pinctrl_levels(output)
                if all(pin in levels for pin in ordered_pins):
                    self._supports_multi_get = True
                    return levels
            except subprocess.CalledProcessError:
                self._supports_multi_get = False

        self._supports_multi_get = False
        return {pin: self.read_level(pin) for pin in ordered_pins}

    def add_edge_callback(self, pin: int, callback: Callable[[int], None]) -> bool:
        del pin, callback
        return False

    def remove_edge_callback(self, pin: int) -> None:
        del pin

    def close(self) -> None:
        return None


class RPiGPIOInputGPIO:
    def __init__(self, gpio_module: object | None = None) -> None:
        if gpio_module is None:
            try:
                import RPi.GPIO as gpio_module  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Das Python-Modul 'RPi.GPIO' wurde nicht gefunden. "
                    "Auf dem Pi ist dafuer typischerweise das Paket 'rpi-lgpio' noetig."
                ) from exc

        self._gpio = gpio_module
        self._configured_pins: set[int] = set()
        self._edge_callback_pins: set[int] = set()
        self._setmode_done = False

    def _ensure_mode(self) -> None:
        if self._setmode_done:
            return
        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BCM)
        self._setmode_done = True

    def configure_input_pullup(self, pin: int) -> None:
        self._ensure_mode()
        self._gpio.setup(pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
        self._configured_pins.add(pin)

    def configure_inputs(self, pins: Sequence[int]) -> None:
        for pin in pins:
            self.configure_input_pullup(pin)

    def read_level(self, pin: int) -> bool:
        self._ensure_mode()
        return bool(self._gpio.input(pin))

    def read_levels(self, pins: Sequence[int]) -> dict[int, bool]:
        return {pin: self.read_level(pin) for pin in dict.fromkeys(pins)}

    def add_edge_callback(self, pin: int, callback: Callable[[int], None]) -> bool:
        self._ensure_mode()
        if pin not in self._configured_pins:
            raise RuntimeError(f"GPIO {pin} muss vor der Interrupt-Konfiguration als Eingang gesetzt sein.")
        self._gpio.add_event_detect(pin, self._gpio.BOTH, callback=callback)
        self._edge_callback_pins.add(pin)
        return True

    def remove_edge_callback(self, pin: int) -> None:
        if pin not in self._edge_callback_pins:
            return
        self._gpio.remove_event_detect(pin)
        self._edge_callback_pins.discard(pin)

    def close(self) -> None:
        if not self._configured_pins:
            return
        for pin in tuple(self._edge_callback_pins):
            self.remove_edge_callback(pin)
        self._gpio.cleanup(sorted(self._configured_pins))
        self._configured_pins.clear()


def create_input_gpio(backend: str = "auto") -> InputGPIO:
    if backend == "auto":
        try:
            return RPiGPIOInputGPIO()
        except RuntimeError:
            return PinctrlInputGPIO()
    if backend == "rpi-gpio":
        return RPiGPIOInputGPIO()
    if backend == "pinctrl":
        return PinctrlInputGPIO()
    raise ValueError(f"Unbekanntes GPIO-Backend: {backend}")


class EC11Decoder:
    _TRANSITIONS = {
        (0, 1): 1,
        (1, 3): 1,
        (3, 2): 1,
        (2, 0): 1,
        (1, 0): -1,
        (3, 1): -1,
        (2, 3): -1,
        (0, 2): -1,
    }

    def __init__(self, steps_per_detent: int = 4) -> None:
        if steps_per_detent <= 0:
            raise ValueError("steps_per_detent muss > 0 sein.")
        self.steps_per_detent = steps_per_detent
        self.position = 0
        self._partial_steps = 0
        self._last_state: int | None = None

    def update(self, a_high: bool, b_high: bool) -> int:
        state = (int(a_high) << 1) | int(b_high)
        if self._last_state is None:
            self._last_state = state
            return 0

        transition = (self._last_state, state)
        self._last_state = state
        delta = self._TRANSITIONS.get(transition, 0)
        if delta == 0:
            return 0

        self._partial_steps += delta
        emitted = 0

        while self._partial_steps >= self.steps_per_detent:
            emitted += 1
            self.position += 1
            self._partial_steps -= self.steps_per_detent

        while self._partial_steps <= -self.steps_per_detent:
            emitted -= 1
            self.position -= 1
            self._partial_steps += self.steps_per_detent

        return emitted
