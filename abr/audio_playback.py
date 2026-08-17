from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import BinaryIO, Callable
import shutil
import subprocess
import tempfile
import time
import wave

DEFAULT_STREAM_FRAMES_PER_CHUNK = 1024
# Keep enough PCM queued to survive short Raspberry-Pi scheduler stalls while
# retaining a clearly sub-second response to EC11 volume changes.
DEFAULT_STREAM_MAX_AHEAD_SECONDS = 0.25
DEFAULT_APLAY_BUFFER_TIME_US = 300_000
DEFAULT_APLAY_PERIOD_TIME_US = 50_000
_PLAYBACK_LOCK = Lock()


@dataclass
class AudioPlaybackHandle:
    process: subprocess.Popen[bytes]
    cleanup_path: Path | None = None
    streamer_thread: Thread | None = None
    streamer_error: list[BaseException] | None = None
    release_callback: Callable[[], None] | None = None
    stderr_output: str | None = None
    _released: bool = False

    def wait(self) -> int:
        try:
            return_code = self.process.wait()
            if self.streamer_thread is not None:
                self.streamer_thread.join()
            self.stderr_output = _read_process_stderr(self.process, existing=self.stderr_output)
            if self.streamer_error:
                raise RuntimeError(f"Audio-Streaming fehlgeschlagen: {self.streamer_error[0]}")
            return return_code
        finally:
            self._cleanup()
            self._release_lock()

    def stop(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1.0)
            if self.streamer_thread is not None:
                self.streamer_thread.join(timeout=1.0)
            self.stderr_output = _read_process_stderr(self.process, existing=self.stderr_output)
        finally:
            self._cleanup()
            self._release_lock()

    def _cleanup(self) -> None:
        if self.cleanup_path is not None:
            self.cleanup_path.unlink(missing_ok=True)
            self.cleanup_path = None

    def _release_lock(self) -> None:
        if not self._released and self.release_callback is not None:
            self.release_callback()
            self._released = True


def detect_playback_binary() -> str | None:
    return shutil.which("afplay") or shutil.which("aplay") or shutil.which("paplay")


def play_audio_file(
    audio_path: Path,
    *,
    volume_percent: int = 100,
    volume_provider: Callable[[], int] | None = None,
) -> None:
    handle = start_audio_playback(
        audio_path,
        volume_percent=volume_percent,
        volume_provider=volume_provider,
    )
    return_code = handle.wait()
    if return_code != 0:
        detail = f": {handle.stderr_output}" if handle.stderr_output else ""
        raise RuntimeError(f"Audio-Wiedergabe fehlgeschlagen ({return_code}): {audio_path}{detail}")


def start_audio_playback(
    audio_path: Path,
    *,
    volume_percent: int = 100,
    volume_provider: Callable[[], int] | None = None,
) -> AudioPlaybackHandle:
    playback_binary = detect_playback_binary()
    if playback_binary is None:
        raise RuntimeError("Keine lokale Audio-Wiedergabe verfuegbar.")
    _PLAYBACK_LOCK.acquire()
    resolved_audio_path = audio_path.expanduser().resolve()
    try:
        if _supports_dynamic_streaming(playback_binary, resolved_audio_path, volume_provider):
            handle = _start_streaming_wav_playback(
                playback_binary,
                resolved_audio_path,
                volume_provider=volume_provider or (lambda: volume_percent),
            )
            handle.release_callback = _PLAYBACK_LOCK.release
            return handle

        prepared_path, cleanup_path = prepare_audio_file(resolved_audio_path, volume_percent=volume_percent)
        process = subprocess.Popen([playback_binary, str(prepared_path)], stderr=subprocess.PIPE)
        return AudioPlaybackHandle(
            process=process,
            cleanup_path=cleanup_path,
            release_callback=_PLAYBACK_LOCK.release,
        )
    except BaseException:
        _PLAYBACK_LOCK.release()
        raise


def prepare_audio_file(audio_path: Path, *, volume_percent: int = 100) -> tuple[Path, Path | None]:
    resolved_path = audio_path.expanduser().resolve()
    if volume_percent >= 100:
        return resolved_path, None
    if volume_percent <= 0:
        volume_percent = 1
    if resolved_path.suffix.lower() != ".wav":
        return resolved_path, None

    scale = max(0.01, min(volume_percent, 100) / 100.0)
    with wave.open(str(resolved_path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())

    scaled_frames = _scale_pcm_frames(frames, sample_width=params.sampwidth, scale=scale)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        output_path = Path(handle.name)
    with wave.open(str(output_path), "wb") as target:
        target.setparams(params)
        target.writeframes(scaled_frames)
    return output_path, output_path


def _supports_dynamic_streaming(
    playback_binary: str,
    audio_path: Path,
    volume_provider: Callable[[], int] | None,
) -> bool:
    return (
        volume_provider is not None
        and Path(playback_binary).name == "aplay"
        and audio_path.suffix.lower() == ".wav"
    )


def _start_streaming_wav_playback(
    playback_binary: str,
    audio_path: Path,
    *,
    volume_provider: Callable[[], int],
) -> AudioPlaybackHandle:
    with wave.open(str(audio_path), "rb") as source:
        sample_width = source.getsampwidth()
        channel_count = source.getnchannels()
        sample_rate = source.getframerate()

    process = subprocess.Popen(
        [
            playback_binary,
            "-q",
            "-t",
            "raw",
            "-f",
            _alsa_format_from_sample_width(sample_width),
            "-c",
            str(channel_count),
            "-r",
            str(sample_rate),
            "--buffer-time",
            str(DEFAULT_APLAY_BUFFER_TIME_US),
            "--period-time",
            str(DEFAULT_APLAY_PERIOD_TIME_US),
            "-",
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None:
        process.kill()
        process.wait(timeout=1.0)
        raise RuntimeError("Audio-Streaming konnte stdin fuer aplay nicht oeffnen.")

    streamer_error: list[BaseException] = []
    streamer = Thread(
        target=_stream_wav_to_pipe,
        args=(audio_path, process.stdin, volume_provider, streamer_error),
        name=f"abr-audio-stream-{audio_path.stem}",
        daemon=True,
    )
    streamer.start()
    return AudioPlaybackHandle(
        process=process,
        streamer_thread=streamer,
        streamer_error=streamer_error,
    )


def _read_process_stderr(process: subprocess.Popen[bytes], *, existing: str | None = None) -> str | None:
    if existing:
        return existing
    stderr = process.stderr
    if stderr is None:
        return None
    raw = stderr.read()
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace").strip()
    return text or None


def _stream_wav_to_pipe(
    audio_path: Path,
    pipe: BinaryIO,
    volume_provider: Callable[[], int],
    streamer_error: list[BaseException],
    *,
    frames_per_chunk: int = DEFAULT_STREAM_FRAMES_PER_CHUNK,
    max_ahead_seconds: float = DEFAULT_STREAM_MAX_AHEAD_SECONDS,
) -> None:
    try:
        with wave.open(str(audio_path), "rb") as source:
            sample_width = source.getsampwidth()
            channel_count = source.getnchannels()
            sample_rate = source.getframerate()
            frame_size = sample_width * channel_count
            started_at = time.monotonic()
            streamed_frames = 0
            while True:
                frames = source.readframes(frames_per_chunk)
                if not frames:
                    break
                volume_percent = max(1, min(100, int(volume_provider())))
                if volume_percent < 100:
                    scale = volume_percent / 100.0
                    frames = _scale_pcm_frames(frames, sample_width=sample_width, scale=scale)
                pipe.write(frames)
                pipe.flush()
                streamed_frames += len(frames) // max(1, frame_size)
                _sleep_to_limit_playback_lead(
                    streamed_frames=streamed_frames,
                    sample_rate=sample_rate,
                    started_at=started_at,
                    max_ahead_seconds=max_ahead_seconds,
                )
        pipe.close()
    except (BrokenPipeError, ValueError):
        return
    except BaseException as exc:  # pragma: no cover - defensive propagation from background thread
        streamer_error.append(exc)
        try:
            pipe.close()
        except OSError:
            pass


def _alsa_format_from_sample_width(sample_width: int) -> str:
    format_map = {
        1: "U8",
        2: "S16_LE",
        3: "S24_3LE",
        4: "S32_LE",
    }
    try:
        return format_map[sample_width]
    except KeyError as exc:
        raise RuntimeError(f"Nicht unterstuetzte PCM-Samplebreite fuer Streaming: {sample_width}") from exc


def _sleep_to_limit_playback_lead(
    *,
    streamed_frames: int,
    sample_rate: int,
    started_at: float,
    max_ahead_seconds: float,
) -> None:
    if sample_rate <= 0:
        return
    streamed_duration = streamed_frames / sample_rate
    elapsed = time.monotonic() - started_at
    sleep_seconds = _compute_playback_lead_sleep(
        streamed_duration=streamed_duration,
        elapsed=elapsed,
        max_ahead_seconds=max_ahead_seconds,
    )
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)


def _compute_playback_lead_sleep(
    *,
    streamed_duration: float,
    elapsed: float,
    max_ahead_seconds: float,
) -> float:
    return max(0.0, streamed_duration - elapsed - max_ahead_seconds)


def _scale_pcm_frames(frames: bytes, *, sample_width: int, scale: float) -> bytes:
    if sample_width not in {1, 2, 3, 4}:
        return frames
    if sample_width == 1:
        return bytes(_scale_u8_sample(value, scale) for value in frames)

    scaled = bytearray(len(frames))
    for offset in range(0, len(frames), sample_width):
        sample = _decode_signed_pcm(frames[offset : offset + sample_width], sample_width)
        scaled_sample = _clip_signed_pcm(int(round(sample * scale)), sample_width)
        scaled[offset : offset + sample_width] = _encode_signed_pcm(scaled_sample, sample_width)
    return bytes(scaled)


def _scale_u8_sample(value: int, scale: float) -> int:
    signed = value - 128
    scaled = max(-128, min(127, int(round(signed * scale))))
    return scaled + 128


def _decode_signed_pcm(chunk: bytes, sample_width: int) -> int:
    if sample_width == 3:
        sign_extension = b"\xff" if (chunk[2] & 0x80) else b"\x00"
        return int.from_bytes(chunk + sign_extension, byteorder="little", signed=True)
    return int.from_bytes(chunk, byteorder="little", signed=True)


def _encode_signed_pcm(value: int, sample_width: int) -> bytes:
    if sample_width == 3:
        return int(value).to_bytes(4, byteorder="little", signed=True)[:3]
    return int(value).to_bytes(sample_width, byteorder="little", signed=True)


def _clip_signed_pcm(value: int, sample_width: int) -> int:
    bits = sample_width * 8
    minimum = -(1 << (bits - 1))
    maximum = (1 << (bits - 1)) - 1
    return max(minimum, min(maximum, value))
