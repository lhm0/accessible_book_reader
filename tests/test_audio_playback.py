from __future__ import annotations

from io import BytesIO
from pathlib import Path
import subprocess
import wave

from abr.audio_playback import (
    DEFAULT_APLAY_BUFFER_TIME_US,
    DEFAULT_APLAY_PERIOD_TIME_US,
    DEFAULT_STREAM_MAX_AHEAD_SECONDS,
    AudioPlaybackHandle,
    _compute_playback_lead_sleep,
    _stream_wav_to_pipe,
    play_audio_file,
)


class _RecordingPipe(BytesIO):
    def close(self) -> None:
        self.was_closed = True


def test_stream_wav_to_pipe_applies_updated_volume_per_chunk(tmp_path: Path) -> None:
    wav_path = tmp_path / "sample.wav"
    with wave.open(str(wav_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(
            (1000).to_bytes(2, byteorder="little", signed=True)
            + (1000).to_bytes(2, byteorder="little", signed=True)
        )

    requested_volumes = iter([100, 50])
    pipe = _RecordingPipe()
    errors: list[BaseException] = []

    _stream_wav_to_pipe(
        wav_path,
        pipe,
        lambda: next(requested_volumes),
        errors,
        frames_per_chunk=1,
    )

    assert errors == []
    assert pipe.getvalue() == (
        (1000).to_bytes(2, byteorder="little", signed=True)
        + (500).to_bytes(2, byteorder="little", signed=True)
    )


def test_compute_playback_lead_sleep_limits_prefetch_ahead() -> None:
    assert _compute_playback_lead_sleep(
        streamed_duration=1.0,
        elapsed=0.95,
        max_ahead_seconds=0.1,
    ) == 0.0
    assert round(
        _compute_playback_lead_sleep(
            streamed_duration=1.0,
            elapsed=0.2,
            max_ahead_seconds=0.1,
        ),
        6,
    ) == 0.7


def test_dynamic_playback_keeps_scheduler_safety_buffer() -> None:
    assert DEFAULT_STREAM_MAX_AHEAD_SECONDS == 0.25
    assert DEFAULT_APLAY_BUFFER_TIME_US == 300_000
    assert DEFAULT_APLAY_PERIOD_TIME_US == 50_000


def test_play_audio_file_includes_stderr_output_in_error(monkeypatch, tmp_path: Path) -> None:
    from abr import audio_playback as audio_playback_module

    class _FakeHandle:
        def __init__(self) -> None:
            self.stderr_output = "audio open error: Device or resource busy"

        def wait(self) -> int:
            return 1

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFF")
    original = audio_playback_module.start_audio_playback
    audio_playback_module.start_audio_playback = lambda *args, **kwargs: _FakeHandle()
    try:
        try:
            play_audio_file(audio_path)
        except RuntimeError as exc:
            message = str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("RuntimeError expected")
    finally:
        audio_playback_module.start_audio_playback = original

    assert "Audio-Wiedergabe fehlgeschlagen (1)" in message
    assert "Device or resource busy" in message


def test_audio_playback_handle_wait_reads_stderr_from_process(tmp_path: Path) -> None:
    process = subprocess.Popen(
        [
            "sh",
            "-c",
            "printf 'audio open error: No such file or directory' >&2; exit 1",
        ],
        stderr=subprocess.PIPE,
    )
    handle = AudioPlaybackHandle(process=process)

    return_code = handle.wait()

    assert return_code == 1
    assert handle.stderr_output == "audio open error: No such file or directory"
