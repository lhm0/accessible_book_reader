from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from abr.book.store import normalize_tag_id
from abr.hardware.pico_gateway_client import DEFAULT_DEVICE, DEFAULT_TIMEOUT, open_uart, read_lines, send_command


class NFCTagReader(Protocol):
    def read_tag_id(self) -> str | None: ...
    def start_tag_scan(self) -> None: ...
    def fetch_tag_scan(self) -> NFCTagScan: ...


@dataclass(frozen=True)
class NFCTag:
    uid: str
    technology: str
    reader_id: int


@dataclass(frozen=True)
class NFCTagScan:
    tags: tuple[NFCTag, ...] = ()

    @property
    def iso14443a_tags(self) -> tuple[NFCTag, ...]:
        return tuple(tag for tag in self.tags if tag.technology == "ISO14443A")

    @property
    def iso15693_tags(self) -> tuple[NFCTag, ...]:
        return tuple(tag for tag in self.tags if tag.technology == "ISO15693")

    @property
    def primary_tag(self) -> NFCTag | None:
        tags = self.iso14443a_tags
        return tags[0] if tags else None


@dataclass(frozen=True)
class NFCGatewayConfig:
    device: str = DEFAULT_DEVICE
    baud: int = 115200
    timeout: float = DEFAULT_TIMEOUT
    status_command: str = "STATUS"

    def __post_init__(self) -> None:
        if self.baud <= 0:
            raise ValueError("baud muss > 0 sein.")
        if self.timeout <= 0:
            raise ValueError("timeout muss > 0 sein.")


class GatewayNFCTagReader:
    def __init__(self, config: NFCGatewayConfig = NFCGatewayConfig()) -> None:
        self.config = config

    def read_tag_id(self) -> str | None:
        scan = self._read_scan(self.config.status_command)
        primary = scan.primary_tag
        if primary is not None:
            return primary.uid
        secondary_tags = scan.iso15693_tags
        return secondary_tags[0].uid if secondary_tags else None

    def start_tag_scan(self) -> None:
        self._read_lines("STATUS_START")

    def fetch_tag_scan(self) -> NFCTagScan:
        return self._read_scan("STATUS_FETCH")

    def _read_scan(self, command: str) -> NFCTagScan:
        return parse_tag_scan_from_status_lines(self._read_lines(command))

    def _read_lines(self, command: str) -> list[str]:
        fd = open_uart(self.config.device, self.config.baud)
        try:
            send_command(fd, command)
            lines = read_lines(fd, self.config.timeout)
        finally:
            os.close(fd)
        if not lines:
            raise RuntimeError(f"Keine Antwort auf {command} vom NFC-Gateway.")
        error = next((line for line in lines if line.startswith("ERR ")), None)
        if error is not None:
            raise RuntimeError(f"NFC-Gateway meldet: {error}")
        return lines


def parse_tag_id_from_status_lines(lines: list[str]) -> str | None:
    scan = parse_tag_scan_from_status_lines(lines)
    primary = scan.primary_tag
    if primary is not None:
        return primary.uid
    secondary_tags = scan.iso15693_tags
    return secondary_tags[0].uid if secondary_tags else None


def parse_tag_scan_from_status_lines(lines: list[str]) -> NFCTagScan:
    tags: list[NFCTag] = []
    seen: set[tuple[str, str, int]] = set()

    for line in lines:
        if not line.startswith("READER "):
            continue
        fields = _parse_reader_status_line(line)
        try:
            reader_id = int(fields.get("id", "0"))
        except ValueError:
            continue
        protocol_fields = (
            ("ISO14443A", "tag14443a", "uid14443a"),
            ("ISO15693", "tag15693", "uid15693"),
        )
        protocol_data_present = any(key in fields for _, key, _ in protocol_fields)
        for technology, present_key, uid_key in protocol_fields:
            uid = fields.get(uid_key)
            if fields.get(present_key) == "1" and uid and uid != "-":
                _append_tag(tags, seen, uid, technology, reader_id)
        if not protocol_data_present and fields.get("tag") == "1":
            uid = fields.get("uid")
            technology = fields.get("tech")
            if uid and uid != "-" and technology in {"ISO14443A", "ISO15693"}:
                _append_tag(tags, seen, uid, technology, reader_id)
    return NFCTagScan(tags=tuple(tags))


def _append_tag(
    tags: list[NFCTag],
    seen: set[tuple[str, str, int]],
    uid: str,
    technology: str,
    reader_id: int,
) -> None:
    normalized_uid = _normalize_gateway_uid(uid)
    key = (normalized_uid, technology, reader_id)
    if key not in seen:
        seen.add(key)
        tags.append(NFCTag(uid=normalized_uid, technology=technology, reader_id=reader_id))


def _parse_reader_status_line(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return fields


def _normalize_gateway_uid(uid: str) -> str:
    raw = str(uid).strip().upper()
    compact = raw.replace(":", "").replace("-", "").replace(" ", "")
    return normalize_tag_id(compact)
