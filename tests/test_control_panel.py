from __future__ import annotations

import pytest

from abr.hardware.control_panel import (
    EC11Decoder,
    RPiGPIOInputGPIO,
    parse_pinctrl_levels,
    parse_single_pinctrl_level,
)


class _FakeRPiGPIOModule:
    BCM = 11
    IN = 1
    PUD_UP = 22
    BOTH = 33

    def __init__(self) -> None:
        self.callbacks = {}
        self.cleaned = []

    def setwarnings(self, enabled) -> None:
        del enabled

    def setmode(self, mode) -> None:
        assert mode == self.BCM

    def setup(self, pin, mode, *, pull_up_down) -> None:
        assert mode == self.IN
        assert pull_up_down == self.PUD_UP

    def input(self, pin) -> bool:
        del pin
        return True

    def add_event_detect(self, pin, edge, *, callback) -> None:
        assert edge == self.BOTH
        self.callbacks[pin] = callback

    def remove_event_detect(self, pin) -> None:
        self.callbacks.pop(pin, None)

    def cleanup(self, pins) -> None:
        self.cleaned = list(pins)


def test_parse_pinctrl_levels_reads_multiple_lines() -> None:
    output = "\n".join(
        [
            "5: ip    pu | hi // GPIO5 = input",
            "6: ip    pu | lo // GPIO6 = input",
            "16: ip   pu | hi // GPIO16 = input",
        ]
    )

    assert parse_pinctrl_levels(output) == {
        5: True,
        6: False,
        16: True,
    }


def test_parse_single_pinctrl_level_reads_hi_and_lo() -> None:
    assert parse_single_pinctrl_level("17: ip pu | hi // GPIO17 = input") is True
    assert parse_single_pinctrl_level("17: ip pu | lo // GPIO17 = input") is False


def test_parse_single_pinctrl_level_rejects_missing_level() -> None:
    with pytest.raises(RuntimeError):
        parse_single_pinctrl_level("17: ip pu // GPIO17 = input")


def test_ec11_decoder_emits_negative_step_for_first_gray_sequence() -> None:
    decoder = EC11Decoder()

    for a_high, b_high in (
        (True, True),
        (False, True),
        (False, False),
        (True, False),
        (True, True),
    ):
        emitted = decoder.update(a_high, b_high)

    assert emitted == -1
    assert decoder.position == -1


def test_ec11_decoder_emits_positive_step_for_reverse_gray_sequence() -> None:
    decoder = EC11Decoder()

    for a_high, b_high in (
        (True, True),
        (True, False),
        (False, False),
        (False, True),
        (True, True),
    ):
        emitted = decoder.update(a_high, b_high)

    assert emitted == 1
    assert decoder.position == 1


def test_ec11_decoder_ignores_incomplete_sequence() -> None:
    decoder = EC11Decoder()

    for a_high, b_high in (
        (True, True),
        (False, True),
        (True, True),
    ):
        emitted = decoder.update(a_high, b_high)

    assert emitted == 0
    assert decoder.position == 0


def test_rpi_gpio_backend_registers_and_removes_edge_callback() -> None:
    gpio_module = _FakeRPiGPIOModule()
    gpio = RPiGPIOInputGPIO(gpio_module=gpio_module)
    observed: list[int] = []
    gpio.configure_inputs((5, 6))

    assert gpio.add_edge_callback(5, observed.append) is True
    gpio_module.callbacks[5](5)
    assert observed == [5]

    gpio.close()

    assert gpio_module.callbacks == {}
    assert gpio_module.cleaned == [5, 6]
