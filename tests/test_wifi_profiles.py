from __future__ import annotations

import subprocess
import pytest

from abr.wifi_profiles import WifiProfileManager, WifiReconnectMonitor, _split_nmcli_terse, main


class RecordingRunner:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[list[str]] = []

    def __call__(self, command, *, check=True):
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=self.output, stderr="")


class RecoveryRunner:
    def __init__(self):
        self.state = 30
        self.profiles = "Bad:111:wifi:\nGood:222:wifi:\n"
        self.attempts = []
        self.working = set()
        self.scan_connects = False
        self.state_error = None
        self.scans = 0

    def __call__(self, command, *, check=True):
        output, code = "", 0
        if "GENERAL.STATE" in command:
            if self.state_error:
                raise self.state_error
            output = f"{self.state} (state)"
        elif "NAME,UUID,TYPE,DEVICE" in command:
            output = self.profiles
        elif "rescan" in command:
            self.scans += 1
            if self.scan_connects:
                self.state = 100
        elif "up" in command:
            uuid = command[command.index("uuid") + 1]
            self.attempts.append(uuid)
            if uuid in self.working:
                self.state = 100
            else:
                code = 4
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, stdout=output, stderr="unreachable" if code else "")


def test_recovery_cycles_until_hotspot_appears_and_recovers_again_after_loss():
    runner = RecoveryRunner()
    monitor = WifiReconnectMonitor(WifiProfileManager(runner))
    for _ in range(6):
        monitor.step()
    assert runner.attempts == ["111", "222"] * 3
    runner.working.add("222")
    monitor.step()
    monitor.step()
    assert runner.state == 100
    attempts = list(runner.attempts)
    monitor.step()
    assert runner.attempts == attempts
    runner.state = 30
    monitor.step()
    monitor.step()
    assert runner.state == 100
    assert runner.attempts[-2:] == ["111", "222"]


@pytest.mark.parametrize("state", [10, 20, 40, 50, 60, 70, 80, 90, 100, 110])
def test_recovery_leaves_connected_busy_or_unavailable_device_alone(state):
    runner = RecoveryRunner()
    runner.state = state
    WifiReconnectMonitor(WifiProfileManager(runner)).step()
    assert runner.attempts == []
    assert runner.scans == 0


def test_recovery_does_not_get_stuck_in_repeated_networkmanager_activation():
    runner = RecoveryRunner()
    runner.state = 60
    now = [0.0]
    monitor = WifiReconnectMonitor(WifiProfileManager(runner), clock=lambda: now[0])
    monitor.step()
    now[0] = 121
    monitor.step()
    now[0] = 242
    monitor.step()
    assert runner.attempts == ["111", "222"]


def test_recovery_preserves_connection_established_during_scan():
    runner = RecoveryRunner()
    runner.scan_connects = True
    WifiReconnectMonitor(WifiProfileManager(runner)).step()
    assert runner.attempts == []


def test_recovery_picks_up_new_profiles_and_handles_deleted_profile():
    runner = RecoveryRunner()
    runner.profiles = ""
    monitor = WifiReconnectMonitor(WifiProfileManager(runner))
    monitor.step()
    runner.profiles = "New:333:wifi:\n"
    monitor.step()
    runner.profiles = "Replacement:444:wifi:\n"
    monitor.step()
    assert runner.attempts == ["333", "444"]


@pytest.mark.parametrize("error", [
    subprocess.CalledProcessError(1, ["nmcli"]),
    subprocess.TimeoutExpired(["nmcli"], 120),
])
def test_recovery_loop_survives_networkmanager_errors(error):
    runner = RecoveryRunner()
    runner.state_error = error
    monitor = WifiReconnectMonitor(WifiProfileManager(runner))
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        runner.state_error = None
        if len(sleeps) == 2:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        monitor.run(sleep=sleep)
    assert sleeps == [10, 10]
    assert runner.attempts == ["111"]


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


def test_configure_all_limits_individual_retries_for_every_wifi_profile() -> None:
    runner = RecordingRunner("Zuhause:111:802-11-wireless:wlan0\nMobil:222:wifi:\n")

    WifiProfileManager(runner).configure_all()

    assert runner.commands[1][-4:] == ["connection.autoconnect", "yes", "connection.autoconnect-retries", "1"]
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

    assert runner.commands[-1] == ["nmcli", "connection", "up", "ifname", "wlan0"]


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
