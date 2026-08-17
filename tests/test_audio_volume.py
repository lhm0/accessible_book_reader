from __future__ import annotations

import subprocess

from abr.control.audio_volume import AudioVolumeConfig, AudioVolumeController


class _FakeAudioVolumeController(AudioVolumeController):
    def __init__(self) -> None:
        super().__init__(AudioVolumeConfig())
        self.read_percent = 57
        self.written_percents: list[int] = []

    def _read_current_percent(self) -> int | None:
        return self.read_percent

    def _write_percent(self, percent: int) -> None:
        self.written_percents.append(percent)


def test_audio_volume_controller_initializes_to_nearest_step() -> None:
    controller = _FakeAudioVolumeController()

    state = controller.initialize()

    assert controller.levels == (20, 29, 38, 47, 56, 64, 73, 82, 91, 100)
    assert state.level_index == 4
    assert state.level_count == 10
    assert state.percent == 56
    assert controller.written_percents == [56]


def test_audio_volume_controller_clamps_to_minimum_and_maximum() -> None:
    controller = _FakeAudioVolumeController()
    controller.initialize()

    min_state = controller.apply_delta(-99)
    max_state = controller.apply_delta(+99)

    assert min_state is not None
    assert max_state is not None
    assert min_state.percent == 20
    assert max_state.percent == 100
    assert controller.written_percents == [56, 20, 100]


def test_audio_volume_interrupt_request_changes_target_without_running_mixer() -> None:
    controller = _FakeAudioVolumeController()
    controller.initialize()

    requested = controller.request_delta(1)

    assert requested is not None
    assert requested.percent == 64
    assert controller.current_percent() == 64
    assert controller.written_percents == [56]

    applied = controller.apply_requested_volume()

    assert applied.percent == 64
    assert controller.written_percents == [56, 64]


class _FakeAutoDetectAudioVolumeController(AudioVolumeController):
    def __init__(self, config: AudioVolumeConfig) -> None:
        super().__init__(config)
        self.commands: list[tuple[str, ...]] = []

    def _resolve_mixer_command(self) -> str:
        return "/usr/bin/amixer"

    def _run_mixer_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        if args == ("scontrols",):
            return subprocess.CompletedProcess(
                ["/usr/bin/amixer", *args],
                0,
                stdout="Simple mixer control 'PCM',0\nSimple mixer control 'Mic',0\n",
                stderr="",
            )
        if args == ("get", "PCM"):
            return subprocess.CompletedProcess(
                ["/usr/bin/amixer", *args],
                0,
                stdout="  Front Left: Playback 42 [56%] [-20.00dB] [on]\n",
                stderr="",
            )
        if args == ("sset", "PCM", "56%"):
            return subprocess.CompletedProcess(
                ["/usr/bin/amixer", *args],
                0,
                stdout="ok\n",
                stderr="",
            )
        raise AssertionError(f"unerwartetes Kommando: {args}")


def test_audio_volume_controller_auto_detects_working_mixer_control() -> None:
    controller = _FakeAutoDetectAudioVolumeController(AudioVolumeConfig(mixer_control="auto"))

    state = controller.initialize()

    assert state.percent == 56
    assert controller.commands == [
        ("scontrols",),
        ("get", "PCM"),
        ("get", "PCM"),
        ("sset", "PCM", "56%"),
    ]


class _FakeMissingControlAudioVolumeController(AudioVolumeController):
    def _resolve_mixer_command(self) -> str:
        return "/usr/bin/amixer"

    def _run_mixer_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        if args == ("scontrols",):
            return subprocess.CompletedProcess(
                ["/usr/bin/amixer", *args],
                0,
                stdout="Simple mixer control 'PCM',0\nSimple mixer control 'Mic',0\n",
                stderr="",
            )
        raise AssertionError(f"unerwartetes Kommando: {args}")


def test_audio_volume_controller_reports_available_controls_for_missing_explicit_control() -> None:
    controller = _FakeMissingControlAudioVolumeController(AudioVolumeConfig(mixer_control="Master"))

    try:
        controller.initialize()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("RuntimeError erwartet")

    assert "ALSA-Mixer-Control nicht gefunden: Master." in message
    assert "PCM" in message
    assert "Mic" in message


class _FakeNoControlAudioVolumeController(AudioVolumeController):
    def __init__(self) -> None:
        super().__init__(AudioVolumeConfig(mixer_control="auto"))

    def _resolve_mixer_command(self) -> str:
        return "/usr/bin/amixer"

    def _run_mixer_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        if args == ("scontrols",):
            return subprocess.CompletedProcess(
                ["/usr/bin/amixer", *args],
                0,
                stdout="",
                stderr="",
            )
        raise AssertionError(f"unerwartetes Kommando: {args}")


def test_audio_volume_controller_falls_back_to_software_when_no_mixer_controls_exist() -> None:
    controller = _FakeNoControlAudioVolumeController()

    state = controller.initialize()
    changed_state = controller.apply_delta(-1)

    assert controller.uses_software_volume() is True
    assert state.percent == 100
    assert changed_state is not None
    assert changed_state.percent == 91
