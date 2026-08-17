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

from abr.hardware.led_control import LEDController, channel_label, resolve_pins


DEFAULT_CHANNEL = "both"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Schaltet die beiden LED-MOSFET-Kanaele des ABR-Testaufbaus."
    )
    parser.add_argument(
        "command",
        choices=("on", "off", "pulse", "status"),
        help="Gewuenschte Aktion fuer den LED-Ausgang.",
    )
    parser.add_argument(
        "--channel",
        choices=("left", "right", "both"),
        default=DEFAULT_CHANNEL,
        help="Zu schaltender LED-Kanal, Standard: both.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=1.0,
        help="Dauer fuer 'pulse' in Sekunden, Standard: 1.0.",
    )
    return parser

def main() -> int:
    args = _build_parser().parse_args()

    try:
        controller = LEDController()
        pins = resolve_pins(args.channel)
        label = channel_label(args.channel)

        if args.command == "on":
            controller.set_channel(args.channel, True)
            print(f"{label} eingeschaltet ({', '.join(f'BCM{pin}' for pin in pins)}).")
            return 0

        if args.command == "off":
            controller.set_channel(args.channel, False)
            print(f"{label} ausgeschaltet ({', '.join(f'BCM{pin}' for pin in pins)}).")
            return 0

        if args.command == "pulse":
            if args.seconds < 0:
                raise RuntimeError("--seconds muss >= 0 sein.")
            controller.set_channel(args.channel, True)
            time.sleep(args.seconds)
            controller.set_channel(args.channel, False)
            print(f"{label} fuer {args.seconds:g} s gepulst ({', '.join(f'BCM{pin}' for pin in pins)}).")
            return 0

        for line in controller.status_lines(args.channel):
            print(line)
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
