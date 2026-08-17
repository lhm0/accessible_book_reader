from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
from typing import Iterable


DEFAULT_DEVICE = "/dev/ttyAMA0"
DEFAULT_TIMEOUT = 2.0
END_MARKERS = ("END", "PONG")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UART-Client fuer das RP2040-PN532-Gateway auf dem Raspberry Pi 5."
    )
    parser.add_argument(
        "command",
        nargs="*",
        default=["STATUS"],
        help="Gateway-Kommando, z. B. STATUS, STATUS_START, STATUS_FETCH, DIAG, PING, REINIT 1",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"UART-Geraet, Standard: {DEFAULT_DEVICE}",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Baudrate, Standard: 115200",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lese-Timeout in Sekunden, Standard: 2.0",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Nur Rohantwort ausgeben, ohne Zusatzlogik",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def baudrate_to_termios(baudrate: int) -> int:
    mapping = {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
    }
    if baudrate not in mapping:
        raise ValueError(f"Nicht unterstuetzte Baudrate: {baudrate}")
    return mapping[baudrate]


def configure_uart(fd: int, baudrate: int) -> None:
    attrs = termios.tcgetattr(fd)

    attrs[0] = 0
    attrs[1] = 0
    attrs[2] &= ~termios.CSIZE
    attrs[2] |= termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[2] &= ~termios.PARENB
    attrs[2] &= ~termios.CSTOPB
    if hasattr(termios, "CRTSCTS"):
        attrs[2] &= ~termios.CRTSCTS
    attrs[3] = 0

    speed = baudrate_to_termios(baudrate)
    attrs[4] = speed
    attrs[5] = speed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIFLUSH)


def open_uart(device: str, baudrate: int) -> int:
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY)
    configure_uart(fd, baudrate)
    return fd


def send_command(fd: int, command: str) -> None:
    os.write(fd, (command.strip() + "\n").encode("ascii"))


def read_lines(fd: int, timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    lines: list[str] = []

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        readable, _, _ = select.select([fd], [], [], max(0.0, remaining))
        if not readable:
            break

        try:
            chunk = os.read(fd, 1024)
        except BlockingIOError:
            continue
        if not chunk:
            continue

        buffer.extend(chunk)
        while b"\n" in buffer:
            raw_line, _, rest = buffer.partition(b"\n")
            buffer = bytearray(rest)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            lines.append(line)
            if line in END_MARKERS or line.startswith("ERR "):
                return lines

    if buffer:
        lines.append(buffer.decode("utf-8", errors="replace").strip())
    return [line for line in lines if line]


def print_pretty(lines: Iterable[str]) -> None:
    for line in lines:
        print(line)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    command = " ".join(args.command).strip().upper()

    try:
        fd = open_uart(args.device, args.baud)
    except OSError as exc:
        print(f"Konnte UART {args.device} nicht oeffnen: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        send_command(fd, command)
        lines = read_lines(fd, args.timeout)
    finally:
        os.close(fd)

    if not lines:
        print("Keine Antwort vom Gateway innerhalb des Timeouts.", file=sys.stderr)
        return 2

    if args.raw:
        sys.stdout.write("\n".join(lines) + "\n")
        return 0

    print_pretty(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
