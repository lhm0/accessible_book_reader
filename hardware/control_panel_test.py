#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from abr.hardware.control_panel import (
    BUTTON_LABELS,
    CONTROL_PANEL_PINS,
    EC11Decoder,
    ENCODER_A_PIN,
    ENCODER_B_PIN,
    PIN_LABELS,
    PinctrlInputGPIO,
)


DEFAULT_DIRECTION_SIGN = -1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Einfacher GPIO-Test fuer das ABR-Bedienpanel mit EC11 und Tastern."
    )
    parser.add_argument(
        "--poll-interval-ms",
        type=float,
        default=10.0,
        help="Abfrageintervall in Millisekunden, Standard: 10.",
    )
    parser.add_argument(
        "--steps-per-detent",
        type=int,
        default=4,
        help="Quadratur-Teilschritte pro Rasterung des EC11, Standard: 4.",
    )
    parser.add_argument(
        "--show-releases",
        action="store_true",
        help="Zusatzlich losgelassene Taster melden.",
    )
    parser.add_argument(
        "--show-raw-encoder",
        action="store_true",
        help="A/B-Zustandswechsel des Encoders zusaetzlich ausgeben.",
    )
    parser.add_argument(
        "--invert-rotation",
        action="store_true",
        help="Drehrichtung invertieren, falls links/rechts vertauscht gemeldet wird.",
    )
    return parser


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _print_mapping() -> None:
    print("Aktive GPIO-Map des Bedienpanels:")
    for pin in CONTROL_PANEL_PINS:
        print(f"  BCM{pin}: {PIN_LABELS[pin]}")
    print("Alle Eingaben werden als active-low mit internem Pull-up gelesen.")
    print("Abbruch mit Ctrl-C.\n")


def main() -> int:
    args = _build_parser().parse_args()
    if args.poll_interval_ms <= 0:
        print("Fehler: --poll-interval-ms muss > 0 sein.", file=sys.stderr)
        return 1
    if args.steps_per_detent <= 0:
        print("Fehler: --steps-per-detent muss > 0 sein.", file=sys.stderr)
        return 1

    try:
        gpio = PinctrlInputGPIO()
        gpio.configure_inputs(CONTROL_PANEL_PINS)
        levels = gpio.read_levels(CONTROL_PANEL_PINS)
        decoder = EC11Decoder(steps_per_detent=args.steps_per_detent)
        decoder.update(levels[ENCODER_A_PIN], levels[ENCODER_B_PIN])

        _print_mapping()

        poll_interval_s = args.poll_interval_ms / 1000.0
        while True:
            current_levels = gpio.read_levels(CONTROL_PANEL_PINS)

            for pin, label in BUTTON_LABELS.items():
                was_pressed = not levels[pin]
                is_pressed = not current_levels[pin]
                if is_pressed and not was_pressed:
                    print(f"[{_timestamp()}] Taste gedrueckt: {label} (BCM{pin})")
                elif args.show_releases and was_pressed and not is_pressed:
                    print(f"[{_timestamp()}] Taste losgelassen: {label} (BCM{pin})")

            if args.show_raw_encoder:
                encoder_state = (int(current_levels[ENCODER_A_PIN]) << 1) | int(current_levels[ENCODER_B_PIN])
                previous_state = (int(levels[ENCODER_A_PIN]) << 1) | int(levels[ENCODER_B_PIN])
                if encoder_state != previous_state:
                    print(
                        f"[{_timestamp()}] Encoder Rohzustand: "
                        f"A={'hi' if current_levels[ENCODER_A_PIN] else 'lo'} "
                        f"B={'hi' if current_levels[ENCODER_B_PIN] else 'lo'} "
                        f"(0b{encoder_state:02b})"
                    )

            steps = decoder.update(current_levels[ENCODER_A_PIN], current_levels[ENCODER_B_PIN])
            steps *= DEFAULT_DIRECTION_SIGN
            if args.invert_rotation:
                steps *= -1
            if steps != 0:
                direction = "rechts" if steps > 0 else "links"
                magnitude = abs(steps)
                suffix = "" if magnitude == 1 else f" x{magnitude}"
                display_sign = DEFAULT_DIRECTION_SIGN * (-1 if args.invert_rotation else 1)
                display_position = decoder.position * display_sign
                print(
                    f"[{_timestamp()}] Encoder gedreht: {direction}{suffix} "
                    f"(Position {display_position})"
                )

            levels = current_levels
            time.sleep(poll_interval_s)
    except KeyboardInterrupt:
        print("\nBeendet.")
        return 0
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        message = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = exc.stderr.strip()
            if stderr:
                message = stderr
        print(f"Fehler: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
