from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import os
import subprocess
from typing import Protocol, Sequence


WIFI_CONNECTION_TYPES = {"802-11-wireless", "wifi"}


class CommandRunner(Protocol):
    def __call__(self, command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]: ...


def _run_command(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


@dataclass(frozen=True)
class WifiProfile:
    name: str
    uuid: str
    device: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.device)


def _split_nmcli_terse(line: str) -> list[str]:
    """Split nmcli's escaped terse format without losing literal colons."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


class WifiProfileManager:
    """Small NetworkManager adapter for the Wi-Fi profiles used by the reader."""

    def __init__(self, runner: CommandRunner = _run_command, interface: str = "wlan0") -> None:
        self._runner = runner
        self.interface = interface

    def profiles(self) -> list[WifiProfile]:
        result = self._runner(
            [
                "nmcli",
                "--terse",
                "--escape",
                "yes",
                "--fields",
                "NAME,UUID,TYPE,DEVICE",
                "connection",
                "show",
            ]
        )
        profiles: list[WifiProfile] = []
        for line in result.stdout.splitlines():
            fields = _split_nmcli_terse(line)
            if len(fields) != 4 or fields[2] not in WIFI_CONNECTION_TYPES:
                continue
            name, uuid, _connection_type, device = fields
            profiles.append(WifiProfile(name=name, uuid=uuid, device=device or None))
        return profiles

    def configure_autoconnect(self, profile: str) -> None:
        self._runner(
            [
                "nmcli",
                "connection",
                "modify",
                profile,
                "connection.autoconnect",
                "yes",
                "connection.autoconnect-retries",
                "0",
            ]
        )

    def configure_all(self) -> list[WifiProfile]:
        profiles = self.profiles()
        for profile in profiles:
            self.configure_autoconnect(profile.uuid)
        return profiles

    def add(
        self,
        name: str,
        ssid: str,
        password: str,
        priority: int = 0,
        activate: bool = False,
    ) -> None:
        if not password:
            raise ValueError("Das WLAN-Passwort darf nicht leer sein.")
        self._runner(
            [
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                self.interface,
                "con-name",
                name,
                "ssid",
                ssid,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ]
        )
        self.configure_autoconnect(name)
        self._runner(
            [
                "nmcli",
                "connection",
                "modify",
                name,
                "connection.autoconnect-priority",
                str(priority),
            ]
        )
        if activate:
            # The complete profile, including its secret, exists before activation.
            # This is essential when activation replaces the SSH transport itself.
            self._runner(["nmcli", "connection", "up", name, "ifname", self.interface])

    def switch(self, profile: str) -> None:
        self.configure_autoconnect(profile)
        self._runner(["nmcli", "connection", "up", profile, "ifname", self.interface])

    def automatic(self) -> list[WifiProfile]:
        profiles = self.configure_all()
        self._runner(["nmcli", "device", "connect", self.interface])
        return profiles


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gespeicherte WLAN-Profile des ABR ueber NetworkManager verwalten."
    )
    parser.add_argument("--interface", default="wlan0", help="WLAN-Interface (Standard: wlan0)")
    parser.add_argument(
        "--allow-ssh-disconnect",
        action="store_true",
        help="Verbindungswechsel trotz erkannter SSH-Sitzung erlauben",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="Gespeicherte WLAN-Profile anzeigen")

    add_parser = subparsers.add_parser("add", help="WPA/WPA2-Profil hinzufuegen und verbinden")
    add_parser.add_argument("name", help="Eindeutiger Profilname")
    add_parser.add_argument("ssid", help="Name des WLANs")
    add_parser.add_argument("--priority", type=int, default=0, help="Autoconnect-Prioritaet")
    add_parser.add_argument(
        "--activate",
        action="store_true",
        help="Neues Profil nach dem Speichern sofort aktivieren",
    )

    switch_parser = subparsers.add_parser("switch", help="Sofort zu einem gespeicherten Profil wechseln")
    switch_parser.add_argument("profile", help="Profilname oder UUID")

    subparsers.add_parser("configure", help="Autoconnect fuer alle gespeicherten WLANs einschalten")
    subparsers.add_parser("auto", help="Alle Profile konfigurieren und automatische Auswahl anstossen")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manager = WifiProfileManager(interface=args.interface)
    try:
        disruptive_command = args.command in {"switch", "auto"} or (
            args.command == "add" and args.activate
        )
        if (
            disruptive_command
            and os.environ.get("SSH_CONNECTION")
            and not args.allow_ssh_disconnect
        ):
            parser.error(
                "Dieser Befehl kann die aktive SSH-Verbindung trennen. "
                "Lokal am Pi ausfuehren oder bewusst --allow-ssh-disconnect vor dem Befehl angeben."
            )
        if args.command == "list":
            profiles = manager.profiles()
            if not profiles:
                print("Keine gespeicherten WLAN-Profile gefunden.")
            for profile in profiles:
                marker = "*" if profile.active else " "
                device = profile.device or "-"
                print(f"{marker} {profile.name}\t{profile.uuid}\t{device}")
        elif args.command == "add":
            password = getpass.getpass("WLAN-Passwort: ")
            manager.add(args.name, args.ssid, password, args.priority, args.activate)
            state = "gespeichert und aktiviert" if args.activate else "gespeichert"
            print(f"WLAN-Profil {args.name!r} wurde {state}.")
        elif args.command == "switch":
            manager.switch(args.profile)
            print(f"WLAN-Profil {args.profile!r} wurde aktiviert.")
        elif args.command == "configure":
            profiles = manager.configure_all()
            print(f"Autoconnect ist fuer {len(profiles)} WLAN-Profil(e) aktiviert.")
        elif args.command == "auto":
            profiles = manager.automatic()
            print(f"Automatische Auswahl aus {len(profiles)} WLAN-Profil(en) angestossen.")
    except FileNotFoundError:
        parser.error("nmcli wurde nicht gefunden; NetworkManager muss installiert sein.")
    except ValueError as exc:
        parser.error(str(exc))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        parser.error(f"NetworkManager-Aufruf fehlgeschlagen: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
