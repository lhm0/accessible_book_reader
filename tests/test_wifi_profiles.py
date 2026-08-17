from __future__ import annotations

import subprocess

from abr.wifi_profiles import WifiProfileManager, _split_nmcli_terse, main


class RecordingRunner:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[list[str]] = []

    def __call__(self, command, *, check=True):
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=self.output, stderr="")


def test_profiles_only_returns_wifi_connections() -> None:
    runner = RecordingRunner(
        "Zuhause:111:802-11-wireless:wlan0\n"
        "Mobil:222:wifi:\n"
        "Kabel:333:802-3-ethernet:eth0\n"
    )

    profiles = WifiProfileManager(runner).profiles()

    assert [(item.name, item.uuid, item.active) for item in profiles] == [
        ("Zuhause", "111", True),
        ("Mobil", "222", False),
    ]


def test_configure_all_enables_unlimited_retries_for_every_wifi_profile() -> None:
    runner = RecordingRunner("Zuhause:111:802-11-wireless:wlan0\nMobil:222:wifi:\n")

    WifiProfileManager(runner).configure_all()

    assert runner.commands[1][-4:] == ["connection.autoconnect", "yes", "connection.autoconnect-retries", "0"]
    assert runner.commands[1][3] == "111"
    assert runner.commands[2][3] == "222"


def test_switch_keeps_profile_available_for_future_autoconnect() -> None:
    runner = RecordingRunner()

    WifiProfileManager(runner, interface="wlan9").switch("Mobil")

    assert runner.commands[0][3] == "Mobil"
    assert runner.commands[1] == ["nmcli", "connection", "up", "Mobil", "ifname", "wlan9"]


def test_add_stores_password_before_activating_profile() -> None:
    runner = RecordingRunner()

    WifiProfileManager(runner).add(
        "Handy", "Example Hotspot", "secret-password", 10, activate=True
    )

    add_command = runner.commands[0]
    assert add_command[-2:] == ["wifi-sec.psk", "secret-password"]
    assert runner.commands[-1] == ["nmcli", "connection", "up", "Handy", "ifname", "wlan0"]
    assert runner.commands.index(runner.commands[-1]) > runner.commands.index(add_command)


def test_add_does_not_change_active_network_by_default() -> None:
    runner = RecordingRunner()

    WifiProfileManager(runner).add("Handy", "Example Hotspot", "secret-password")

    assert all(command[1:3] != ["connection", "up"] for command in runner.commands)


def test_automatic_configures_profiles_before_connecting_device() -> None:
    runner = RecordingRunner("Zuhause:111:802-11-wireless:\n")

    WifiProfileManager(runner).automatic()

    assert runner.commands[-1] == ["nmcli", "device", "connect", "wlan0"]


def test_nmcli_terse_parser_preserves_escaped_colons_and_backslashes() -> None:
    assert _split_nmcli_terse(r"Mein\:WLAN:abc:802-11-wireless:wlan0") == [
        "Mein:WLAN",
        "abc",
        "802-11-wireless",
        "wlan0",
    ]
    assert _split_nmcli_terse(r"Netz\\Name:abc:wifi:")[0] == r"Netz\Name"


def test_switch_is_rejected_inside_ssh_session(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SSH_CONNECTION", "192.0.2.1 1234 192.0.2.2 22")

    try:
        main(["switch", "Mobil"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("SSH-Sicherung hat den Wechsel nicht abgelehnt")

    assert "SSH-Verbindung trennen" in capsys.readouterr().err
