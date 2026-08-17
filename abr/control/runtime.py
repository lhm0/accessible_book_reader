from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from html import escape as xml_escape
from queue import Empty, Queue
from threading import Condition, Event, Lock, Thread
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import xml.etree.ElementTree as ET
from typing import Callable

from abr.audio_playback import AudioPlaybackHandle, start_audio_playback
from abr.book import (
    BookStore,
    ChapterAssembler,
    PageIngestRequest,
    PageIngestResult,
    PageIngestService,
    PageIngestor,
    PageRecord,
    SummaryManager,
    SummaryService,
)
from abr.control.audio_volume import AudioVolumeController
from abr.control.artifact_cleanup import ArtifactCleaner, ArtifactCleanupConfig
from abr.control.frontpanel import ABRAction, ABRActionType, FrontPanelActionRouter, FrontPanelMonitor
from abr.hardware.nfc_gateway import NFCTagReader, NFCTagScan
from abr.system_audio import SystemAudioConfig, play_system_message
from abr.tts import create_tts_backend
from abr.tts.base import TTSBackend
from abr.usage_statistics import UsageStatisticsStore


class WorkState(str, Enum):
    IDLE = "idle"
    CAPTURE_OCR_RUNNING = "capture_ocr_running"
    BOOK_SUMMARY_RUNNING = "book_summary_running"
    CHAPTER_SUMMARY_RUNNING = "chapter_summary_running"
    DELETE_BOOK_CONFIRMATION = "delete_book_confirmation"
    CANCELLING_WORK = "cancelling_work"
    ERROR = "error"


class ForegroundJobType(str, Enum):
    DUMMY_CAPTURE_OCR = "dummy_capture_ocr"
    CAPTURE_OCR = "capture_ocr"
    BOOK_SUMMARY = "book_summary"
    CHAPTER_SUMMARY = "chapter_summary"


class ForegroundJobEventType(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ForegroundJobSpec:
    job_type: ForegroundJobType
    label: str
    runner: Callable[[Event, Callable[[str], None]], None]


@dataclass(frozen=True)
class ForegroundJobHandle:
    job_id: str
    spec: ForegroundJobSpec
    started_at: float


class ForegroundJobCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureOCRJobConfig:
    python_executable: str = sys.executable
    project_root: Path = Path(__file__).resolve().parents[2]
    capture_output_root: Path = Path("captures")
    ocr_output_dir: Path = Path("runs/latest_rapidocr")
    capture_timeout_ms: int | None = None
    no_denoise: bool = True
    overlay: bool = False
    orientation_mode: str = "off"
    language: str = "de"
    artifact_cleanup: ArtifactCleanupConfig = ArtifactCleanupConfig()
    iso15693_only_orientation: str = "reader2"

    def __post_init__(self) -> None:
        if self.language not in {"de", "en"}:
            raise ValueError("language muss de oder en sein.")
        if self.iso15693_only_orientation not in {"reader1", "reader2"}:
            raise ValueError("iso15693_only_orientation muss reader1 oder reader2 sein.")


@dataclass(frozen=True)
class CaptureBookContext:
    tag_id: str
    orientation: str = "reader2"


@dataclass(frozen=True)
class PageIngestRuntimeConfig:
    library_root: Path = Path("library")
    fallback_tag_id: str | None = "TESTBOOK"
    new_book_message_name: str = "neues_buch"
    start_ack_message_name: str = "bing"
    start_wait_heartbeat_message_name: str = "bing"
    start_wait_heartbeat_interval_s: float = 5.0
    chapter_summary_message_name: str = "kapitel_zusammenfassen"
    book_summary_message_name: str = "buch_zusammenfassen"
    cancel_work_message_name: str = "abbruch"
    error_message_name: str = "fehler"
    empty_page_message_name: str = "empty_page.wav"
    delete_book_message_name: str = "buch_loeschen"
    delete_cancel_message_name: str = "abbruch"
    delete_success_message_name: str = "buch_geloescht"
    missing_book_message_name: str = "buch_nicht_erkannt"
    missing_summary_message_name: str = "keine_zusammenfassung"
    wrong_direction_message_name: str = "wrong_direction.wav"
    repeat_page_message_name: str = "repeat_page.wav"


@dataclass(frozen=True)
class PageSpeechConfig:
    language_code: str = "de"
    chapter_label: str = "Kapitel"
    tts_backend: str = "google"
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_speed: float = 0.9
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_instructions: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_language_code: str = "de"
    google_tts_voice_name: str = "de-DE-Standard-H"
    google_tts_language_code: str = "de-DE"
    google_neural2_voice_name: str = "de-DE-Neural2-H"
    google_gemini_flash_voice_name: str = "Charon"
    google_gemini_flash_prompt: str = (
        "Lies den folgenden deutschen Buchtext ruhig, klar und natuerlich vor. "
        "Beruecksichtige Bedeutung, Satzstruktur und Dialoge. Verwende eine warme, "
        "zurueckhaltende Hoerbuchintonation ohne uebertriebene Schauspielerei. "
        "Setze an Absatz- und Kapitelgrenzen gut wahrnehmbare Pausen."
    )

    def __post_init__(self) -> None:
        if self.tts_speed <= 0:
            raise ValueError("tts_speed muss > 0 sein.")


@dataclass(frozen=True)
class _QueuedSystemAudioMessage:
    message_name: str
    heartbeat_generation: int | None = None


_CHAPTER_ANNOUNCEMENT_BREAK_MS = 1350
_ENHANCED_HEADING_BREAK_MS = 700
_ENHANCED_SENTENCE_BREAK_MS = 900
_ENHANCED_PARAGRAPH_BREAK_MS = 2000
_PLAYBACK_SENTENCE_END_RE = re.compile(r"[.!?…](?:[\"'«»”)\]]+)?(?=\s|$)")
_ENHANCED_SENTENCE_BOUNDARY_RE = re.compile(
    r'(?:(?<=[.!?…])|(?<=[.!?…][\"\'«»”)]))\s+(?=[A-ZÄÖÜ0-9\"„“»])'
)
_QUESTION_FINAL_WORD_RE = re.compile(
    r"(?P<prefix>.*?)(?P<word>[A-Za-zÄÖÜäöüß]+)(?P<ending>\?(?:[\"'«»”)\]]*)?)$"
)
_ENHANCED_PARAGRAPH_LINE_END_RE = re.compile(r"([.?](?:[\"'«»”)\]]*)?)[ \t]*\n")
_QUOTED_DIALOGUE_SENTENCE_RE = re.compile(r'^(?:"[^"\n]+"|„[^“\n]+“|»[^«\n]+«)$')
_QUESTION_FINAL_WORD_PITCH = "+3st"
_GOOGLE_TTS_CHUNK_MAX_INPUT_BYTES = 3800
_SUMMARY_TTS_CHUNK_MAX_INPUT_BYTES = 900


class PageAudioPlayer:
    def __init__(
        self,
        config: PageSpeechConfig = PageSpeechConfig(),
        *,
        status_callback: Callable[[str], None] | None = None,
        volume_provider: Callable[[], int] | None = None,
        audio_ready_callback: Callable[[str], None] | None = None,
        playback_duration_callback: Callable[[float], None] | None = None,
        error_callback: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.config = config
        self.status_callback = status_callback
        self.volume_provider = volume_provider
        self.audio_ready_callback = audio_ready_callback
        self.playback_duration_callback = playback_duration_callback
        self.error_callback = error_callback
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._cancel_generation = 0
        self._playback_handle: AudioPlaybackHandle | None = None
        self._active = False
        self._pending_utterances: list[tuple[int, str, str]] = []
        self._shutdown_requested = False
        self._worker = Thread(target=self._run, name="abr-page-audio", daemon=True)
        self._tts_backend: TTSBackend | None = None
        self._worker.start()

    def enqueue_pages(self, pages: tuple[PageRecord, ...]) -> None:
        utterances: list[tuple[str, str]] = []
        for page in pages:
            raw_language = page.metadata.get("language")
            page_language = raw_language if isinstance(raw_language, str) else "de"
            if page_language != self.config.language_code:
                raise RuntimeError(
                    f"Seitenausgabe verweigert: Seite {page.page_id} hat Sprache {page_language}, "
                    f"die aktive TTS-Sprache ist {self.config.language_code}."
                )
            text = page.speak_text.strip()
            if not text:
                continue
            page_label = _format_page_label(page)
            utterances.append((page_label, text))
        if not utterances:
            return
        self._enqueue_utterances(utterances)

    def enqueue_text(
        self,
        label: str,
        text: str,
        *,
        language_code: str | None = None,
    ) -> None:
        if language_code is not None and language_code != self.config.language_code:
            raise RuntimeError(
                f"Textausgabe verweigert: Text {label} hat Sprache {language_code}, "
                f"die aktive TTS-Sprache ist {self.config.language_code}."
            )
        normalized_text = text.strip()
        if not normalized_text:
            return
        chunks = _split_text_for_tts(
            normalized_text,
            backend_name=self.config.tts_backend,
            max_input_bytes=_SUMMARY_TTS_CHUNK_MAX_INPUT_BYTES,
            chapter_label=self.config.chapter_label,
        )
        if len(chunks) == 1:
            self._enqueue_utterances([(label, chunks[0])])
            return
        self._emit_status(
            f"Textausgabe {label} wird wegen der TTS-Eingabegroesse in {len(chunks)} Teile aufgeteilt."
        )
        self._enqueue_utterances(
            [
                (f"{label}:{index}/{len(chunks)}", chunk)
                for index, chunk in enumerate(chunks, start=1)
            ]
        )

    def _enqueue_utterances(self, utterances: list[tuple[str, str]]) -> None:
        with self._condition:
            generation = self._cancel_generation
            self._active = True
            for page_label, text in utterances:
                self._pending_utterances.append((generation, page_label, text))
            self._condition.notify_all()
        self._emit_status(f"Seitenausgabe eingeplant: {', '.join(label for label, _ in utterances)}.")

    def cancel(self) -> None:
        with self._condition:
            self._cancel_generation += 1
            playback_handle = self._playback_handle
            self._active = False
            self._pending_utterances.clear()
            self._condition.notify_all()
        if playback_handle is not None:
            playback_handle.stop()
            with self._lock:
                if self._playback_handle is playback_handle:
                    self._playback_handle = None

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        self.cancel()
        with self._condition:
            self._shutdown_requested = True
            self._condition.notify_all()
        self._worker.join(timeout=join_timeout_s)

    def set_audio_ready_callback(self, callback: Callable[[str], None] | None) -> None:
        self.audio_ready_callback = callback

    def set_error_callback(self, callback: Callable[[BaseException], None] | None) -> None:
        self.error_callback = callback

    def set_playback_duration_callback(self, callback: Callable[[float], None] | None) -> None:
        self.playback_duration_callback = callback

    def _run(self) -> None:
        while True:
            item = self._wait_for_next_utterance()
            if item is None:
                return
            generation, current_label, current_text = item
            audio_files: list[Path] = []
            prefetched_audio_path: Path | None = None
            prefetched_item: tuple[int, str, str] | None = None
            prefetched_worker: Thread | None = None
            prefetched_result: dict[str, object] | None = None
            try:
                if self._is_cancelled(generation):
                    continue
                current_audio_path = self._synthesize_page_audio(current_text, current_label)
                audio_files.append(current_audio_path)

                while True:
                    playback_result: dict[str, object] = {"error": None}
                    playback_worker = Thread(
                        target=self._play_audio_file_with_result,
                        args=(current_audio_path, current_label, generation, playback_result),
                        name=f"abr-page-audio-playback-{current_label.replace(':', '-')}",
                        daemon=True,
                    )
                    playback_worker.start()

                    while playback_worker.is_alive():
                        if prefetched_item is None and not self._is_cancelled(generation):
                            next_item = self._peek_next_pending_utterance(generation)
                            if next_item is not None:
                                prefetched_item = next_item
                                prefetched_worker, prefetched_result = self._start_prefetch(
                                    next_item[2],
                                    next_item[1],
                                )
                        playback_worker.join(timeout=0.01)

                    playback_error = playback_result.get("error")
                    if playback_error is not None:
                        raise playback_error
                    if self._is_cancelled(generation):
                        break

                    if prefetched_worker is not None and prefetched_result is not None and prefetched_item is not None:
                        prefetched_worker.join()
                        next_error = prefetched_result.get("error")
                        if next_error is not None:
                            raise next_error
                        next_audio_path = prefetched_result.get("audio_path")
                        if not isinstance(next_audio_path, Path):
                            raise RuntimeError("Seitenausgabe fehlgeschlagen: vorab erzeugtes Audio fehlt.")
                        audio_files.append(next_audio_path)
                        prefetched_audio_path = next_audio_path
                        self._pop_pending_utterance(prefetched_item)
                        current_label = prefetched_item[1]
                        current_text = prefetched_item[2]
                        prefetched_item = None
                        prefetched_worker = None
                        prefetched_result = None
                        current_audio_path = prefetched_audio_path
                        prefetched_audio_path = None
                        continue

                    next_item = self._pop_next_pending_utterance(generation)
                    if next_item is None:
                        with self._condition:
                            if generation == self._cancel_generation:
                                self._active = False
                        break
                    current_label = next_item[1]
                    current_text = next_item[2]
                    current_audio_path = self._synthesize_page_audio(current_text, current_label)
                    audio_files.append(current_audio_path)
            except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                self._emit_status(f"Seitenausgabe fehlgeschlagen: {exc}")
                if self.error_callback is not None:
                    self.error_callback(exc)
            finally:
                if prefetched_worker is not None:
                    prefetched_worker.join()
                if prefetched_result is not None:
                    pending_audio_path = prefetched_result.get("audio_path")
                    if isinstance(pending_audio_path, Path) and pending_audio_path not in audio_files:
                        audio_files.append(pending_audio_path)
                for audio_path in audio_files:
                    audio_path.unlink(missing_ok=True)
                with self._condition:
                    if generation == self._cancel_generation:
                        self._active = False

    def _start_prefetch(self, text: str, page_label: str) -> tuple[Thread, dict[str, object]]:
        result: dict[str, object] = {"audio_path": None, "error": None}
        worker = Thread(
            target=self._prefetch_audio,
            args=(text, page_label, result),
            name=f"abr-page-audio-prefetch-{page_label.replace(':', '-')}",
            daemon=True,
        )
        worker.start()
        return worker, result

    def _prefetch_audio(self, text: str, page_label: str, result: dict[str, object]) -> None:
        try:
            result["audio_path"] = self._synthesize_page_audio(text, page_label)
        except BaseException as exc:  # pragma: no cover - defensive background propagation
            result["error"] = exc

    def _play_audio_file_with_result(
        self,
        audio_path: Path,
        page_label: str,
        generation: int,
        result: dict[str, object],
    ) -> None:
        try:
            self._play_audio_file(audio_path, page_label, generation)
        except BaseException as exc:  # pragma: no cover - defensive background propagation
            result["error"] = exc

    def _synthesize_page_audio(self, text: str, page_label: str) -> Path:
        backend = self._get_tts_backend()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        self._emit_status(f"Seitenausgabe: TTS startet fuer {page_label}.")
        rendered_text, input_type = _prepare_page_tts_input(
            text,
            backend_name=self.config.tts_backend,
            chapter_label=self.config.chapter_label,
        )
        self._emit_status(
            f"Seitenausgabe: TTS-Eingabe fuer {page_label}: "
            f"{len(text)} Zeichen, {len(rendered_text.encode('utf-8'))} Byte ({input_type})."
        )
        backend.synthesize_to_file(rendered_text, output_path, input_type=input_type)
        duration_s = _wav_duration_seconds(output_path)
        duration_text = f", {duration_s:.1f} s" if duration_s is not None else ""
        self._emit_status(
            f"Seitenausgabe: Audio bereit fuer {page_label}: "
            f"{output_path.stat().st_size} Byte{duration_text}."
        )
        if self.audio_ready_callback is not None:
            self.audio_ready_callback(page_label)
        return output_path

    def _play_audio_file(self, audio_path: Path, page_label: str, generation: int) -> None:
        self._emit_status(f"Seitenausgabe: Wiedergabe startet fuer {page_label}.")
        playback_started = time.monotonic()
        playback_handle = start_audio_playback(
            audio_path,
            volume_provider=self.volume_provider,
            volume_percent=self._current_volume_percent(),
        )
        with self._lock:
            self._playback_handle = playback_handle
        try:
            return_code = playback_handle.wait()
        finally:
            elapsed_seconds = max(0.0, time.monotonic() - playback_started)
            with self._lock:
                if self._playback_handle is playback_handle:
                    self._playback_handle = None
            if self.playback_duration_callback is not None and elapsed_seconds > 0:
                try:
                    self.playback_duration_callback(elapsed_seconds)
                except BaseException as exc:  # pragma: no cover - statistics must not break audio
                    self._emit_status(f"Nutzerstatistik fuer Audiowiedergabe fehlgeschlagen: {exc}")
        if self._is_cancelled(generation):
            self._emit_status(f"Seitenausgabe: Wiedergabe abgebrochen fuer {page_label}.")
            return
        if return_code != 0:
            raise RuntimeError(f"Seitenausgabe fehlgeschlagen ({return_code}): {page_label}")
        self._emit_status(f"Seitenausgabe: Wiedergabe abgeschlossen fuer {page_label}.")

    def _current_volume_percent(self) -> int:
        if self.volume_provider is None:
            return 100
        return self.volume_provider()

    def _get_tts_backend(self) -> TTSBackend:
        if self._tts_backend is None:
            self._tts_backend = create_tts_backend(
                self.config.tts_backend,
                model_path=self.config.tts_model,
                voice=self.config.tts_voice,
                require_playback=False,
                speed=self.config.tts_speed,
                openai_model=self.config.openai_tts_model,
                openai_instructions=self.config.openai_tts_instructions,
                elevenlabs_voice_id=self.config.elevenlabs_voice_id,
                elevenlabs_model_id=self.config.elevenlabs_model_id,
                elevenlabs_language_code=self.config.elevenlabs_language_code,
                google_tts_voice_name=self.config.google_tts_voice_name,
                google_tts_language_code=self.config.google_tts_language_code,
                google_neural2_voice_name=self.config.google_neural2_voice_name,
                google_gemini_flash_voice_name=self.config.google_gemini_flash_voice_name,
                google_gemini_flash_prompt=self.config.google_gemini_flash_prompt,
            )
        return self._tts_backend

    def _is_cancelled(self, generation: int) -> bool:
        with self._lock:
            return generation != self._cancel_generation

    def _wait_for_next_utterance(self) -> tuple[int, str, str] | None:
        with self._condition:
            while not self._shutdown_requested:
                if self._pending_utterances:
                    return self._pending_utterances.pop(0)
                self._condition.wait(timeout=0.1)
            return None

    def _peek_next_pending_utterance(self, generation: int) -> tuple[int, str, str] | None:
        with self._condition:
            if not self._pending_utterances:
                return None
            next_item = self._pending_utterances[0]
            if next_item[0] != generation:
                return None
            return next_item

    def _pop_next_pending_utterance(self, generation: int) -> tuple[int, str, str] | None:
        with self._condition:
            if not self._pending_utterances:
                return None
            next_item = self._pending_utterances[0]
            if next_item[0] != generation:
                return None
            return self._pending_utterances.pop(0)

    def _pop_pending_utterance(self, item: tuple[int, str, str]) -> None:
        with self._condition:
            if self._pending_utterances and self._pending_utterances[0] == item:
                self._pending_utterances.pop(0)

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)


def _format_page_label(page: PageRecord) -> str:
    if page.page_number is not None:
        return f"{page.side}:{page.page_number}"
    return f"{page.side}:{page.page_id}"


def _prepare_page_tts_input(
    text: str,
    *,
    backend_name: str,
    chapter_label: str = "Kapitel",
) -> tuple[str, str]:
    normalized_backend = backend_name.strip().lower()
    if normalized_backend == "google-standard-enhanced":
        return _page_text_to_enhanced_ssml(text, chapter_label=chapter_label), "ssml"
    if normalized_backend in {"google", "google-neural2", "say"}:
        return _page_text_to_ssml(text, chapter_label=chapter_label), "ssml"
    return text, "text"


def _split_text_for_tts(
    text: str,
    *,
    backend_name: str,
    max_input_bytes: int = _GOOGLE_TTS_CHUNK_MAX_INPUT_BYTES,
    chapter_label: str = "Kapitel",
) -> tuple[str, ...]:
    normalized_text = text.strip()
    if not normalized_text:
        return ()
    normalized_backend = backend_name.strip().lower()
    if normalized_backend not in {
        "google",
        "google-standard-enhanced",
        "google-neural2",
        "google-gemini-flash",
    }:
        return (normalized_text,)
    if _rendered_tts_input_size(
        normalized_text,
        backend_name=normalized_backend,
        chapter_label=chapter_label,
    ) <= max_input_bytes:
        return (normalized_text,)

    chunks: list[str] = []
    current = ""
    for unit in _summary_speech_units(normalized_text):
        candidate = f"{current} {unit}".strip() if current else unit
        if _rendered_tts_input_size(
            candidate,
            backend_name=normalized_backend,
            chapter_label=chapter_label,
        ) <= max_input_bytes:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if _rendered_tts_input_size(
            unit,
            backend_name=normalized_backend,
            chapter_label=chapter_label,
        ) <= max_input_bytes:
            current = unit
            continue
        for word in unit.split():
            candidate = f"{current} {word}".strip() if current else word
            if (
                current
                and _rendered_tts_input_size(
                    candidate,
                    backend_name=normalized_backend,
                    chapter_label=chapter_label,
                )
                > max_input_bytes
            ):
                chunks.append(current)
                current = word
            else:
                current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks)


def _rendered_tts_input_size(
    text: str,
    *,
    backend_name: str,
    chapter_label: str = "Kapitel",
) -> int:
    rendered_text, _input_type = _prepare_page_tts_input(
        text,
        backend_name=backend_name,
        chapter_label=chapter_label,
    )
    return len(rendered_text.encode("utf-8"))


def _summary_speech_units(text: str) -> tuple[str, ...]:
    units: list[str] = []
    cursor = 0
    for match in _PLAYBACK_SENTENCE_END_RE.finditer(text):
        unit = text[cursor:match.end()].strip()
        if unit:
            units.append(unit)
        cursor = match.end()
    remainder = text[cursor:].strip()
    if remainder:
        units.append(remainder)
    return tuple(units) or (text.strip(),)


def _wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            if frame_rate <= 0:
                return None
            return audio.getnframes() / frame_rate
    except (EOFError, wave.Error, OSError):
        return None


def _chapter_announcement_block_re(chapter_label: str) -> re.Pattern[str]:
    label = chapter_label.strip() or "Kapitel"
    return re.compile(
        rf"(?P<chapter>^{re.escape(label)} [^\n]+?\.)\n(?:\s*\n)+",
        re.MULTILINE | re.IGNORECASE,
    )


def _page_text_to_ssml(text: str, *, chapter_label: str = "Kapitel") -> str:
    stripped = text.strip()
    if not stripped:
        return "<speak></speak>"

    parts: list[str] = []
    cursor = 0
    for match in _chapter_announcement_block_re(chapter_label).finditer(stripped):
        prefix = stripped[cursor:match.start()]
        prefix_without_trailing_breaks = prefix.rstrip()
        if prefix_without_trailing_breaks:
            parts.append(xml_escape(prefix_without_trailing_breaks))
            parts.append(f'<break time="{_CHAPTER_ANNOUNCEMENT_BREAK_MS}ms"/>')
        parts.append(xml_escape(match.group("chapter")))
        parts.append(f'<break time="{_CHAPTER_ANNOUNCEMENT_BREAK_MS}ms"/>')
        cursor = match.end()
    parts.append(xml_escape(stripped[cursor:]))
    return f"<speak>{''.join(parts)}</speak>"


def _page_text_to_enhanced_ssml(text: str, *, chapter_label: str = "Kapitel") -> str:
    """Structure prose for Standard-H without changing its spoken words."""
    stripped = text.strip()
    if not stripped:
        return "<speak></speak>"

    paragraph_marked_text = _ENHANCED_PARAGRAPH_LINE_END_RE.sub(r"\1\n\n", stripped)
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n+", paragraph_marked_text)
        if paragraph.strip()
    ]
    paragraphs = _merge_paragraphs_after_quoted_dialogue(paragraphs)
    rendered: list[str] = []
    for paragraph in paragraphs:
        escaped = xml_escape(paragraph)
        if re.fullmatch(
            rf"{re.escape(chapter_label.strip() or 'Kapitel')}\s+.+[.!?]",
            paragraph,
            flags=re.IGNORECASE,
        ):
            rendered.append(
                f'<s><emphasis level="moderate">{escaped}</emphasis></s>'
                f'<break time="{_CHAPTER_ANNOUNCEMENT_BREAK_MS}ms"/>'
            )
            continue
        if _looks_like_heading(paragraph):
            heading_break_ms = (
                _CHAPTER_ANNOUNCEMENT_BREAK_MS
                if _looks_like_title_cased_heading(paragraph)
                else _ENHANCED_HEADING_BREAK_MS
            )
            rendered.append(
                f'<s><emphasis level="moderate">{escaped}</emphasis></s>'
                f'<break time="{heading_break_ms}ms"/>'
            )
            continue

        sentences = _split_enhanced_sentences(paragraph)
        rendered_sentences: list[str] = []
        for sentence_index, sentence in enumerate(sentences):
            rendered_sentences.append(_render_enhanced_sentence(sentence))
            pause_ms = (
                _ENHANCED_PARAGRAPH_BREAK_MS
                if sentence_index == len(sentences) - 1
                else _ENHANCED_SENTENCE_BREAK_MS
            )
            rendered_sentences.append(f'<break time="{pause_ms}ms"/>')
        paragraph_ssml = "<p>" + "".join(rendered_sentences) + "</p>"
        rendered.append(paragraph_ssml)

    ssml = f"<speak>{''.join(rendered)}</speak>"
    try:
        root = ET.fromstring(ssml)
        rendered_words = re.sub(r"\s+", "", "".join(root.itertext()))
        source_words = re.sub(r"\s+", "", stripped)
        if rendered_words != source_words:
            return _page_text_to_ssml(text, chapter_label=chapter_label)
    except ET.ParseError:
        return _page_text_to_ssml(text, chapter_label=chapter_label)
    return ssml


def _merge_paragraphs_after_quoted_dialogue(paragraphs: list[str]) -> list[str]:
    """Treat a paragraph break after a quoted dialogue sentence as a sentence break."""

    merged: list[str] = []
    previous_was_dialogue = False
    for paragraph in paragraphs:
        if merged and previous_was_dialogue:
            merged[-1] = f"{merged[-1]} {paragraph}"
        else:
            merged.append(paragraph)
        previous_was_dialogue = _is_quoted_dialogue_sentence(paragraph)
    return merged


def _is_quoted_dialogue_sentence(paragraph: str) -> bool:
    if _QUOTED_DIALOGUE_SENTENCE_RE.fullmatch(paragraph) is None:
        return False
    return re.search(r'[.!?…][\"“«]$', paragraph) is not None


def _looks_like_heading(paragraph: str) -> bool:
    return (
        len(paragraph) <= 80
        and len(paragraph.split()) <= 10
        and not re.search(r"[.!?…][\"'«»”)\]]?$", paragraph)
    )


def _looks_like_title_cased_heading(paragraph: str) -> bool:
    words = [word for word in paragraph.split() if any(character.isalpha() for character in word)]
    return len(words) >= 2 and all(
        next((character for character in word if character.isalpha()), "").isupper()
        for word in words
    )


def _split_enhanced_sentences(paragraph: str) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in _ENHANCED_SENTENCE_BOUNDARY_RE.split(paragraph)
        if sentence.strip()
    ]
    return sentences or [paragraph]


def _render_enhanced_sentence(sentence: str) -> str:
    match = _QUESTION_FINAL_WORD_RE.fullmatch(sentence)
    if match is None:
        return f"<s>{xml_escape(sentence)}</s>"

    word = match.group("word")
    return (
        f"<s>{xml_escape(match.group('prefix'))}"
        f'<prosody pitch="{_QUESTION_FINAL_WORD_PITCH}">'
        f"{xml_escape(word)}</prosody>{xml_escape(match.group('ending'))}</s>"
    )


@dataclass(frozen=True)
class ForegroundJobEvent:
    event_type: ForegroundJobEventType
    job_id: str
    job_type: ForegroundJobType
    label: str
    monotonic_time: float
    message: str


class ForegroundJobManager:
    def __init__(self) -> None:
        self._events: Queue[ForegroundJobEvent] = Queue()
        self._lock = Lock()
        self._current_handle: ForegroundJobHandle | None = None
        self._current_thread: Thread | None = None
        self._current_cancel_event: Event | None = None
        self._job_counter = 0

    def is_busy(self) -> bool:
        with self._lock:
            return self._current_handle is not None

    def current_handle(self) -> ForegroundJobHandle | None:
        with self._lock:
            return self._current_handle

    def start_dummy_capture_ocr(self, duration_s: float) -> ForegroundJobHandle:
        if duration_s <= 0:
            raise ValueError("duration_s muss > 0 sein.")
        spec = ForegroundJobSpec(
            job_type=ForegroundJobType.DUMMY_CAPTURE_OCR,
            label="Dummy Capture/OCR",
            runner=_build_dummy_capture_runner(duration_s),
        )
        return self.start_foreground_job(spec)

    def start_capture_ocr(
        self,
        config: CaptureOCRJobConfig,
        *,
        tag_id: str | None = None,
        book_context_resolver: Callable[[], CaptureBookContext | None] | None = None,
        page_ingest_submitter: Callable[[PageIngestRequest], Event | None] | None = None,
    ) -> ForegroundJobHandle:
        spec = ForegroundJobSpec(
            job_type=ForegroundJobType.CAPTURE_OCR,
            label="Capture/OCR",
            runner=_build_capture_ocr_runner(
                config,
                tag_id=tag_id,
                book_context_resolver=book_context_resolver,
                page_ingest_submitter=page_ingest_submitter,
            ),
        )
        return self.start_foreground_job(spec)

    def start_foreground_job(self, spec: ForegroundJobSpec) -> ForegroundJobHandle:
        return self._start_job(spec)

    def cancel_current_job(self) -> bool:
        with self._lock:
            handle = self._current_handle
            cancel_event = self._current_cancel_event
        if handle is None or cancel_event is None or cancel_event.is_set():
            return False
        cancel_event.set()
        self._events.put(
            ForegroundJobEvent(
                event_type=ForegroundJobEventType.CANCEL_REQUESTED,
                job_id=handle.job_id,
                job_type=handle.spec.job_type,
                label=handle.spec.label,
                monotonic_time=time.monotonic(),
                message=f"{handle.spec.label}: Abbruch angefordert.",
            )
        )
        return True

    def get_event(self, timeout: float | None = None) -> ForegroundJobEvent:
        return self._events.get(timeout=timeout)

    def get_nowait(self) -> ForegroundJobEvent:
        return self._events.get_nowait()

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        self.cancel_current_job()
        with self._lock:
            thread = self._current_thread
        if thread is not None:
            thread.join(timeout=join_timeout_s)

    def _start_job(self, spec: ForegroundJobSpec) -> ForegroundJobHandle:
        with self._lock:
            if self._current_handle is not None:
                raise RuntimeError("Es laeuft bereits ein foreground job.")
            self._job_counter += 1
            handle = ForegroundJobHandle(
                job_id=f"job_{self._job_counter:04d}",
                spec=spec,
                started_at=time.monotonic(),
            )
            cancel_event = Event()
            worker = Thread(
                target=self._run_job,
                args=(handle, cancel_event),
                name=f"abr-job-{handle.job_id}",
                daemon=True,
            )
            self._current_handle = handle
            self._current_cancel_event = cancel_event
            self._current_thread = worker
            worker.start()
            return handle

    def _run_job(self, handle: ForegroundJobHandle, cancel_event: Event) -> None:
        self._events.put(
            ForegroundJobEvent(
                event_type=ForegroundJobEventType.STARTED,
                job_id=handle.job_id,
                job_type=handle.spec.job_type,
                label=handle.spec.label,
                monotonic_time=time.monotonic(),
                message=f"{handle.spec.label} gestartet.",
            )
        )
        try:
            handle.spec.runner(
                cancel_event,
                lambda message: self._events.put(
                    ForegroundJobEvent(
                        event_type=ForegroundJobEventType.PROGRESS,
                        job_id=handle.job_id,
                        job_type=handle.spec.job_type,
                        label=handle.spec.label,
                        monotonic_time=time.monotonic(),
                        message=message,
                    )
                ),
            )
            self._events.put(
                ForegroundJobEvent(
                    event_type=ForegroundJobEventType.COMPLETED,
                    job_id=handle.job_id,
                    job_type=handle.spec.job_type,
                    label=handle.spec.label,
                    monotonic_time=time.monotonic(),
                    message=f"{handle.spec.label} abgeschlossen.",
                )
            )
        except ForegroundJobCancelled:
            self._events.put(
                ForegroundJobEvent(
                    event_type=ForegroundJobEventType.CANCELLED,
                    job_id=handle.job_id,
                    job_type=handle.spec.job_type,
                    label=handle.spec.label,
                    monotonic_time=time.monotonic(),
                    message=f"{handle.spec.label} abgebrochen.",
                )
            )
        except BaseException as exc:  # pragma: no cover - defensive runtime propagation
            self._events.put(
                ForegroundJobEvent(
                    event_type=ForegroundJobEventType.FAILED,
                    job_id=handle.job_id,
                    job_type=handle.spec.job_type,
                    label=handle.spec.label,
                    monotonic_time=time.monotonic(),
                    message=f"{handle.spec.label} fehlgeschlagen: {exc}",
                )
            )
        finally:
            self._clear_current_job(handle.job_id)

    def _clear_current_job(self, job_id: str) -> None:
        with self._lock:
            if self._current_handle is None or self._current_handle.job_id != job_id:
                return
            self._current_handle = None
            self._current_cancel_event = None
            self._current_thread = None


class RuntimeController:
    def __init__(
        self,
        monitor: FrontPanelMonitor,
        job_manager: ForegroundJobManager,
        action_callback: Callable[[ABRAction], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        action_router: FrontPanelActionRouter | None = None,
        dummy_capture_job_seconds: float = 8.0,
        capture_ocr_config: CaptureOCRJobConfig | None = None,
        capture_ocr_enabled: bool = False,
        page_ingest_service: PageIngestService | None = None,
        page_ingest_config: PageIngestRuntimeConfig | None = None,
        system_audio_config: SystemAudioConfig | None = None,
        page_audio_player: PageAudioPlayer | None = None,
        chapter_assembler: ChapterAssembler | None = None,
        summary_manager: SummaryManager | None = None,
        summary_service: SummaryService | None = None,
        volume_controller: AudioVolumeController | None = None,
        nfc_tag_reader: NFCTagReader | None = None,
        usage_statistics: UsageStatisticsStore | None = None,
    ) -> None:
        self.monitor = monitor
        self.job_manager = job_manager
        self.action_callback = action_callback
        self.status_callback = status_callback
        self.action_router = action_router or FrontPanelActionRouter()
        self.work_state = WorkState.IDLE
        self.dummy_capture_job_seconds = dummy_capture_job_seconds
        self.capture_ocr_config = capture_ocr_config or CaptureOCRJobConfig()
        self.capture_ocr_enabled = capture_ocr_enabled
        self.page_ingest_service = page_ingest_service
        self.page_ingest_config = page_ingest_config or PageIngestRuntimeConfig()
        self.system_audio_config = system_audio_config or SystemAudioConfig()
        self.page_audio_player = page_audio_player
        self.chapter_assembler = chapter_assembler
        self.summary_manager = summary_manager
        self.summary_service = summary_service
        self.volume_controller = volume_controller
        self.nfc_tag_reader = nfc_tag_reader
        self.usage_statistics = usage_statistics
        self._delete_confirmation_active = False
        self._active_book_tag_id: str | None = self.page_ingest_config.fallback_tag_id
        self._pending_capture_tag_id: str | None = None
        self._pending_delete_tag_id: str | None = None
        self._stop_event = Event()
        self._heartbeat_lock = Lock()
        self._heartbeat_generation = 0
        self._heartbeat_active = False
        self._ignore_page_ingest_results = False
        self._capture_ocr_incremental_ingest_active = False
        self._last_played_page_numbers_by_book: dict[str, set[int]] = {}
        self._last_played_scan_id_by_book: dict[str, str] = {}
        self._wrong_direction_confirmation_books: set[str] = set()
        self._repeat_page_confirmation_books: set[str] = set()
        self._suppressed_playback_scans: set[tuple[str, str]] = set()
        self._volume_interrupt_updates_enabled = False
        self._system_audio_queue: Queue[_QueuedSystemAudioMessage | None] = Queue()
        self._system_audio_worker = Thread(
            target=self._run_system_audio_worker,
            name="abr-system-audio-worker",
            daemon=True,
        )
        self._system_audio_worker.start()
        if self.page_ingest_service is not None:
            self.page_ingest_service.set_result_callback(self._handle_page_ingest_result)
            self.page_ingest_service.set_failure_callback(self._handle_page_ingest_failure)
        if self.page_audio_player is not None:
            self.page_audio_player.set_audio_ready_callback(self._handle_page_audio_ready)
            self.page_audio_player.set_error_callback(self._handle_page_audio_error)
            set_duration_callback = getattr(self.page_audio_player, "set_playback_duration_callback", None)
            if callable(set_duration_callback):
                set_duration_callback(self._record_audio_playback_duration)
        if self.volume_controller is not None:
            try:
                state = self.volume_controller.initialize()
                detail = "Software-Regelung" if self.volume_controller.uses_software_volume() else "Mixer-Regelung"
                self._emit_status(
                    f"Lautstaerke initialisiert: Stufe {state.level_index + 1}/{state.level_count} ({state.percent}%, {detail})."
                )
            except Exception as exc:
                self._emit_status(f"Lautstaerke-Initialisierung fehlgeschlagen: {exc}")
            set_encoder_step_callback = getattr(self.monitor, "set_encoder_step_callback", None)
            if callable(set_encoder_step_callback):
                set_encoder_step_callback(self._request_volume_delta_from_encoder_callback)
                self._volume_interrupt_updates_enabled = True

    def run_forever(self) -> None:
        self.monitor.start()
        self._emit_status("Runtime-Controller gestartet.")
        try:
            while not self._stop_event.is_set():
                self.process_job_events()
                self._process_router_pending_actions()
                try:
                    event = self.monitor.get_event(timeout=0.1)
                except Empty:
                    continue
                action = self.action_router.translate_event(event)
                self._dispatch_action(action)
                self._process_router_pending_actions(monotonic_time=event.monotonic_time)
        finally:
            self._stop_start_wait_heartbeat()
            self._stop_system_audio_worker()
            if self.page_audio_player is not None:
                self.page_audio_player.shutdown()
            self.job_manager.shutdown()
            if self.page_ingest_service is not None:
                self.page_ingest_service.shutdown()
            if self.summary_service is not None:
                self.summary_service.shutdown()
            self.monitor.stop()
            self._emit_status("Runtime-Controller gestoppt.")

    def stop(self) -> None:
        self._stop_event.set()
        self._stop_start_wait_heartbeat()
        self._stop_system_audio_worker()
        if self.summary_service is not None:
            self.summary_service.shutdown()

    def handle_action(self, action: ABRAction) -> None:
        if self._delete_confirmation_active:
            self._handle_delete_confirmation_action(action)
            return

        if action.action_type == ABRActionType.DELETE_BOOK_REQUEST:
            self._start_delete_book_confirmation()
            return

        if action.action_type == ABRActionType.START_STOP:
            if self.job_manager.is_busy():
                if self.page_audio_player is not None and self.page_audio_player.is_active():
                    self._emit_status("Stop-Taste erkannt: laufende Seitenausgabe wird abgebrochen.")
                    self.page_audio_player.cancel()
                self._emit_status("Stop-Taste erkannt: laufender foreground job wird abgebrochen.")
                self._ignore_page_ingest_results = True
                if self.job_manager.cancel_current_job():
                    self.work_state = WorkState.CANCELLING_WORK
                    self._play_system_message_async(self.page_ingest_config.cancel_work_message_name)
            elif self.page_audio_player is not None and self.page_audio_player.is_active():
                self._emit_status("Stop-Taste erkannt: laufende Seitenausgabe wird abgebrochen.")
                self.page_audio_player.cancel()
                self._play_system_message_async(self.page_ingest_config.cancel_work_message_name)
            elif self._is_start_wait_heartbeat_active():
                self._emit_status("Stop-Taste erkannt: Wartezustand wird abgebrochen.")
                self._ignore_page_ingest_results = True
                self._stop_start_wait_heartbeat()
                self.work_state = WorkState.IDLE
                self._play_system_message_async(self.page_ingest_config.cancel_work_message_name)
            elif not self.job_manager.is_busy():
                async_nfc = (
                    self.capture_ocr_enabled
                    and self.nfc_tag_reader is not None
                    and hasattr(self.nfc_tag_reader, "start_tag_scan")
                    and hasattr(self.nfc_tag_reader, "fetch_tag_scan")
                )
                if async_nfc:
                    try:
                        self.nfc_tag_reader.start_tag_scan()
                    except BaseException as exc:
                        self._emit_status(f"NFC-Statusabfrage konnte nicht gestartet werden: {exc}")
                        self._play_system_message_async(self.page_ingest_config.missing_book_message_name)
                        return
                    self._emit_status("NFC-Statusabfrage gestartet; Ergebnis wird nach den Aufnahmen abgeholt.")
                    tag_id = None
                else:
                    tag_id = self._resolve_current_book_tag_id(require_nfc=self.nfc_tag_reader is not None)
                    if tag_id is None:
                        if self.nfc_tag_reader is not None:
                            self._emit_status("Kein NFC-Tag erkannt: Start wird abgebrochen.")
                        else:
                            self._emit_status("Keine Buch-ID konfiguriert: Start wird abgebrochen.")
                        self._play_system_message_async(self.page_ingest_config.missing_book_message_name)
                        return
                    is_new_book = self._ensure_book_context(tag_id)
                    self._active_book_tag_id = tag_id
                    self._pending_capture_tag_id = tag_id
                    if is_new_book:
                        self._emit_status(f"Neues Buch erkannt: {tag_id}. Buchstruktur wird angelegt.")
                        self._play_system_message_async(self.page_ingest_config.new_book_message_name)
                self._play_system_message_async(self.page_ingest_config.start_ack_message_name)
                if self.capture_ocr_enabled:
                    self._ignore_page_ingest_results = False
                    self._start_start_wait_heartbeat()
                    book_label = tag_id or "laufende NFC-Abfrage"
                    self._emit_status(f"Start-Taste erkannt: Capture/OCR wird fuer {book_label} gestartet.")
                    incremental_ingest = self.page_ingest_service is not None
                    self._capture_ocr_incremental_ingest_active = incremental_ingest
                    if incremental_ingest:
                        self.job_manager.start_capture_ocr(
                            self.capture_ocr_config,
                            tag_id=tag_id,
                            book_context_resolver=self._fetch_capture_book_context if async_nfc else None,
                            page_ingest_submitter=self.page_ingest_service.submit,
                        )
                    else:
                        self.job_manager.start_capture_ocr(self.capture_ocr_config)
                else:
                    self._emit_status(f"Start-Taste erkannt: Dummy Capture/OCR wird fuer Buch {tag_id} gestartet.")
                    self.job_manager.start_dummy_capture_ocr(self.dummy_capture_job_seconds)
                self.work_state = WorkState.CAPTURE_OCR_RUNNING
            return

        if action.action_type == ABRActionType.VOLUME_DELTA:
            assert action.value is not None
            self._handle_volume_delta(action.value)
            return

        if action.action_type in (ABRActionType.BOOK_SUMMARY, ABRActionType.CHAPTER_SUMMARY):
            if self.job_manager.is_busy() or (self.page_audio_player is not None and self.page_audio_player.is_active()):
                self._emit_status("Zusammenfassungstaste erkannt, aber das System ist noch beschaeftigt.")
            elif action.action_type == ABRActionType.CHAPTER_SUMMARY:
                self._start_chapter_summary_job()
            else:
                self._start_book_summary_job()
            return

        if action.action_type == ABRActionType.ENCODER_BUTTON:
            self._emit_status("EC11-Taster erkannt, aber dieser Pfad ist noch nicht verdrahtet.")

    def process_job_events(self) -> None:
        while True:
            try:
                event = self.job_manager.get_nowait()
            except Empty:
                return
            self._handle_job_event(event)

    def _handle_job_event(self, event: ForegroundJobEvent) -> None:
        if event.event_type == ForegroundJobEventType.STARTED:
            if event.job_type in (ForegroundJobType.DUMMY_CAPTURE_OCR, ForegroundJobType.CAPTURE_OCR):
                self.work_state = WorkState.CAPTURE_OCR_RUNNING
            elif event.job_type == ForegroundJobType.CHAPTER_SUMMARY:
                self.work_state = WorkState.CHAPTER_SUMMARY_RUNNING
            elif event.job_type == ForegroundJobType.BOOK_SUMMARY:
                self.work_state = WorkState.BOOK_SUMMARY_RUNNING
        elif event.event_type == ForegroundJobEventType.PROGRESS:
            pass
        elif event.event_type == ForegroundJobEventType.CANCEL_REQUESTED:
            self.work_state = WorkState.CANCELLING_WORK
        elif event.event_type == ForegroundJobEventType.COMPLETED:
            self.work_state = WorkState.IDLE
            if event.job_type == ForegroundJobType.CAPTURE_OCR:
                if self._capture_ocr_incremental_ingest_active:
                    self._pending_capture_tag_id = None
                    self._capture_ocr_incremental_ingest_active = False
                else:
                    self._enqueue_page_ingest()
        elif event.event_type == ForegroundJobEventType.CANCELLED:
            self.work_state = WorkState.IDLE
            if event.job_type == ForegroundJobType.CAPTURE_OCR:
                self._pending_capture_tag_id = None
                self._capture_ocr_incremental_ingest_active = False
                self._stop_start_wait_heartbeat()
            elif event.job_type in (ForegroundJobType.CHAPTER_SUMMARY, ForegroundJobType.BOOK_SUMMARY):
                self._stop_start_wait_heartbeat()
        elif event.event_type == ForegroundJobEventType.FAILED:
            self.work_state = WorkState.ERROR if event.job_type == ForegroundJobType.CAPTURE_OCR else WorkState.IDLE
            if event.job_type == ForegroundJobType.CAPTURE_OCR:
                self._pending_capture_tag_id = None
                self._capture_ocr_incremental_ingest_active = False
                self._stop_start_wait_heartbeat()
            elif event.job_type in (ForegroundJobType.CHAPTER_SUMMARY, ForegroundJobType.BOOK_SUMMARY):
                self._stop_start_wait_heartbeat()
        self._emit_status(f"job: {event.message}")

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)

    def _dispatch_action(self, action: ABRAction | None) -> None:
        if action is None:
            return
        if self.action_callback is not None:
            self.action_callback(action)
        self.handle_action(action)

    def _process_router_pending_actions(self, monotonic_time: float | None = None) -> None:
        for action in self.action_router.drain_pending_actions(monotonic_time):
            self._dispatch_action(action)

    def _handle_delete_confirmation_action(self, action: ABRAction) -> None:
        if action.action_type == ABRActionType.VOLUME_DELTA:
            assert action.value is not None
            self._handle_volume_delta(action.value)
            return

        if action.action_type == ABRActionType.ENCODER_BUTTON:
            self._confirm_delete_book()
            return

        if action.action_type in (
            ABRActionType.START_STOP,
            ABRActionType.BOOK_SUMMARY,
            ABRActionType.CHAPTER_SUMMARY,
            ABRActionType.DELETE_BOOK_REQUEST,
        ):
            self._cancel_delete_book_confirmation()
            return

    def _start_delete_book_confirmation(self) -> None:
        if self.job_manager.is_busy() or self.work_state not in {WorkState.IDLE, WorkState.ERROR}:
            self._emit_status("Buch-Loeschen ist im aktuellen Zustand nicht moeglich.")
            return
        tag_id = self._resolve_current_book_tag_id(require_nfc=self.nfc_tag_reader is not None)
        if tag_id is None:
            self._emit_status("Kein NFC-Tag erkannt: Buch-Loeschen wird abgebrochen.")
            self._play_system_message_async(self.page_ingest_config.missing_book_message_name)
            return
        self._delete_confirmation_active = True
        self._pending_delete_tag_id = tag_id
        self.work_state = WorkState.DELETE_BOOK_CONFIRMATION
        self._emit_status(
            f"Buch-Loeschen angefordert fuer Buch {tag_id}: "
            "Warte auf Bestaetigung am EC11-Taster oder Abbruch per Taste."
        )
        self._play_system_message_async(self.page_ingest_config.delete_book_message_name)

    def _cancel_delete_book_confirmation(self) -> None:
        self._delete_confirmation_active = False
        self._pending_delete_tag_id = None
        self.work_state = WorkState.IDLE
        self._emit_status("Buch-Loeschen abgebrochen.")
        self._play_system_message_async(self.page_ingest_config.delete_cancel_message_name)

    def _confirm_delete_book(self) -> None:
        tag_id = self._pending_delete_tag_id
        if tag_id is None:
            self._delete_confirmation_active = False
            self.work_state = WorkState.IDLE
            self._emit_status("Buch-Loeschen fehlgeschlagen: keine gespeicherte Tag-ID vorhanden.")
            return
        store = BookStore(self.page_ingest_config.library_root.expanduser().resolve())
        deleted = store.delete_book(tag_id)
        self._delete_confirmation_active = False
        self._pending_delete_tag_id = None
        self.work_state = WorkState.IDLE
        self._active_book_tag_id = None if deleted and self._active_book_tag_id == tag_id else self._active_book_tag_id
        if deleted:
            self._last_played_page_numbers_by_book.pop(tag_id, None)
            self._last_played_scan_id_by_book.pop(tag_id, None)
            self._wrong_direction_confirmation_books.discard(tag_id)
            self._repeat_page_confirmation_books.discard(tag_id)
            self._suppressed_playback_scans = {
                key for key in self._suppressed_playback_scans if key[0] != tag_id
            }
            self._emit_status(f"Buchdaten geloescht: {tag_id}.")
            self._play_system_message_async(self.page_ingest_config.delete_success_message_name)
            return
        self._emit_status(f"Keine Buchdaten zum Loeschen gefunden: {tag_id}.")

    def _enqueue_page_ingest(self) -> None:
        if self.page_ingest_service is None:
            return
        tag_id = self._pending_capture_tag_id or self._active_book_tag_id or self.page_ingest_config.fallback_tag_id
        if tag_id is None:
            self._emit_status("page-ingest konnte nicht eingeplant werden: keine Buch-Tag-ID verfuegbar.")
            return
        try:
            request = _build_page_ingest_request(
                self.capture_ocr_config,
                tag_id=tag_id,
            )
        except RuntimeError as exc:
            self._emit_status(f"page-ingest konnte nicht eingeplant werden: {exc}")
            return
        self._active_book_tag_id = tag_id
        self._pending_capture_tag_id = None
        self.page_ingest_service.submit(request)

    def _resolve_current_book_tag_id(self, *, require_nfc: bool) -> str | None:
        if self.nfc_tag_reader is not None:
            try:
                tag_id = self.nfc_tag_reader.read_tag_id()
            except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                self._emit_status(f"NFC-Lesen fehlgeschlagen: {exc}")
                return None
            if tag_id is not None:
                return tag_id
            if require_nfc:
                return None
        return self.page_ingest_config.fallback_tag_id

    def _fetch_capture_book_context(self) -> CaptureBookContext | None:
        if self.nfc_tag_reader is None:
            return None
        scan = self.nfc_tag_reader.fetch_tag_scan()
        context = self._resolve_capture_book_context(scan)
        if context is None:
            self._emit_status("Kein zuordenbarer NFC-Tag erkannt.")
            return None
        is_new_book = self._ensure_book_context(context.tag_id)
        self._active_book_tag_id = context.tag_id
        self._pending_capture_tag_id = context.tag_id
        if is_new_book:
            self._emit_status(f"Neues Buch erkannt: {context.tag_id}. Buchstruktur wird angelegt.")
            self._play_system_message_async(self.page_ingest_config.new_book_message_name)
        return context

    def _resolve_capture_book_context(self, scan: NFCTagScan) -> CaptureBookContext | None:
        store = BookStore(self.page_ingest_config.library_root.expanduser().resolve())
        primary = scan.primary_tag
        if primary is not None:
            for secondary in scan.iso15693_tags:
                store.associate_iso15693_tag(primary.uid, secondary.uid)
            orientation = "reader1" if primary.reader_id == 1 else "reader2"
            return CaptureBookContext(tag_id=primary.uid, orientation=orientation)
        for secondary in scan.iso15693_tags:
            tag_id = store.find_book_by_iso15693_tag(secondary.uid)
            if tag_id is not None:
                return CaptureBookContext(
                    tag_id=tag_id,
                    orientation=self.capture_ocr_config.iso15693_only_orientation,
                )
        return None

    def _ensure_book_context(self, tag_id: str) -> bool:
        store = BookStore(self.page_ingest_config.library_root.expanduser().resolve())
        is_new_book = store.load_book(tag_id) is None
        store.ensure_book(tag_id, language=self.capture_ocr_config.language)
        return is_new_book

    def _resolve_summary_book_tag_id(self) -> str | None:
        if self.nfc_tag_reader is not None:
            try:
                tag_id = self.nfc_tag_reader.read_tag_id()
            except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                self._emit_status(f"NFC-Lesen fuer Zusammenfassung fehlgeschlagen: {exc}")
                tag_id = None
            if tag_id is not None:
                return tag_id
        return self._active_book_tag_id or self.page_ingest_config.fallback_tag_id

    def _start_chapter_summary_job(self) -> None:
        if self.summary_manager is None or self.page_audio_player is None:
            self._emit_status("Kapitelzusammenfassung ist noch nicht konfiguriert.")
            return
        tag_id = self._resolve_summary_book_tag_id()
        if tag_id is None:
            self._emit_status("Kapitelzusammenfassung nicht moeglich: kein aktives Buch verfuegbar.")
            return
        self._active_book_tag_id = tag_id
        if self.usage_statistics is not None:
            self._record_usage("Zusammenfassungsfunktion", self.usage_statistics.record_chapter_summary, tag_id)
        try:
            self._play_system_message(self.page_ingest_config.chapter_summary_message_name)
            self._play_system_message(self.page_ingest_config.start_ack_message_name)
            self._start_start_wait_heartbeat()
            self.job_manager.start_foreground_job(
                ForegroundJobSpec(
                    job_type=ForegroundJobType.CHAPTER_SUMMARY,
                    label="Kapitelzusammenfassung",
                    runner=_build_chapter_summary_runner(
                        tag_id=tag_id,
                        chapter_assembler=self.chapter_assembler,
                        summary_manager=self.summary_manager,
                        page_audio_player=self.page_audio_player,
                        missing_summary_callback=lambda: self._play_system_message_async(
                            self.page_ingest_config.missing_summary_message_name
                        ),
                        wait_cancel_callback=self._stop_start_wait_heartbeat,
                    ),
                )
            )
        except RuntimeError as exc:
            self._stop_start_wait_heartbeat()
            self._emit_status(f"Kapitelzusammenfassung konnte nicht gestartet werden: {exc}")

    def _start_book_summary_job(self) -> None:
        if self.summary_manager is None or self.page_audio_player is None:
            self._emit_status("Buchzusammenfassung ist noch nicht konfiguriert.")
            return
        tag_id = self._resolve_summary_book_tag_id()
        if tag_id is None:
            self._emit_status("Buchzusammenfassung nicht moeglich: kein aktives Buch verfuegbar.")
            return
        self._active_book_tag_id = tag_id
        if self.usage_statistics is not None:
            self._record_usage("Was bisher geschah", self.usage_statistics.record_book_summary, tag_id)
        try:
            self._play_system_message(self.page_ingest_config.book_summary_message_name)
            self._play_system_message(self.page_ingest_config.start_ack_message_name)
            self._start_start_wait_heartbeat()
            self.job_manager.start_foreground_job(
                ForegroundJobSpec(
                    job_type=ForegroundJobType.BOOK_SUMMARY,
                    label="Was bisher geschah",
                    runner=_build_book_summary_runner(
                        tag_id=tag_id,
                        chapter_assembler=self.chapter_assembler,
                        summary_manager=self.summary_manager,
                        page_audio_player=self.page_audio_player,
                        missing_summary_callback=lambda: self._play_system_message_async(
                            self.page_ingest_config.missing_summary_message_name
                        ),
                        wait_cancel_callback=self._stop_start_wait_heartbeat,
                    ),
                )
            )
        except RuntimeError as exc:
            self._stop_start_wait_heartbeat()
            self._emit_status(f"Buchzusammenfassung konnte nicht gestartet werden: {exc}")

    def _play_system_message_async(self, message_name: str, *, heartbeat_generation: int | None = None) -> None:
        self._system_audio_queue.put(
            _QueuedSystemAudioMessage(
                message_name=message_name,
                heartbeat_generation=heartbeat_generation,
            )
        )

    def _start_start_wait_heartbeat(self) -> None:
        interval_s = self.page_ingest_config.start_wait_heartbeat_interval_s
        if interval_s <= 0:
            return
        with self._heartbeat_lock:
            self._heartbeat_generation += 1
            generation = self._heartbeat_generation
            self._heartbeat_active = True
        Thread(
            target=self._run_start_wait_heartbeat,
            args=(generation, interval_s),
            name=f"abr-start-heartbeat-{generation}",
            daemon=True,
        ).start()

    def _stop_start_wait_heartbeat(self) -> None:
        with self._heartbeat_lock:
            self._heartbeat_generation += 1
            self._heartbeat_active = False

    def _is_start_wait_heartbeat_active(self) -> bool:
        with self._heartbeat_lock:
            return self._heartbeat_active

    def _run_start_wait_heartbeat(self, generation: int, interval_s: float) -> None:
        while not self._stop_event.wait(interval_s):
            with self._heartbeat_lock:
                if generation != self._heartbeat_generation:
                    return
            self._play_system_message_async(
                self.page_ingest_config.start_wait_heartbeat_message_name,
                heartbeat_generation=generation,
            )

    def _play_system_message(self, message_name: str) -> bool:
        try:
            play_system_message(
                message_name,
                config=self.system_audio_config,
                volume_percent=self._current_volume_percent(),
                volume_provider=self._current_volume_percent,
            )
            return True
        except BaseException as exc:  # pragma: no cover - defensive runtime propagation
            self._emit_status(f"Systemhinweis konnte nicht abgespielt werden: {exc}")
            return False

    def _play_page_sequence_warning(self, message_name: str) -> None:
        if self.job_manager.cancel_current_job():
            self._emit_status(
                "Seitenfolge-Warnung: laufender Capture/OCR-Job wird vor der rechten Seite abgebrochen."
            )
        self._emit_status(f"Seitenfolge-Hinweis startet: {message_name}.")
        if self._play_system_message(message_name):
            self._emit_status(f"Seitenfolge-Hinweis abgeschlossen: {message_name}.")

    def _handle_page_ingest_result(self, request: PageIngestRequest, result: PageIngestResult) -> None:
        if self.usage_statistics is not None:
            page_keys = [f"{page.scan_id}:{page.page_id}" for page in result.pages]
            self._record_usage(
                "gescannte Seiten",
                self.usage_statistics.record_scanned_pages,
                result.tag_id,
                page_keys,
            )
        if self._ignore_page_ingest_results:
            self._stop_start_wait_heartbeat()
            self._emit_status("page-ingest Ergebnis verworfen: Wartezustand wurde zuvor abgebrochen.")
            return
        pages_for_audio = _prepare_pages_for_playback(result.pages, request.playback_sides)
        if not any(page.speak_text.strip() for page in pages_for_audio):
            if self._is_start_wait_heartbeat_active():
                self.work_state = WorkState.ERROR
                self._stop_start_wait_heartbeat()
                self._emit_status("page-ingest lieferte keine vorlesbaren Seiten.")
                self._play_system_message_async(self.page_ingest_config.empty_page_message_name)
            return
        if self.page_audio_player is None:
            self._stop_start_wait_heartbeat()
            return
        if not self._allow_page_sequence_playback(result.tag_id, pages_for_audio):
            return
        self._handle_completed_chapters(result.tag_id)
        self.page_audio_player.enqueue_pages(pages_for_audio)

    def _record_audio_playback_duration(self, seconds: float) -> None:
        tag_id = self._active_book_tag_id
        if self.usage_statistics is None or tag_id is None:
            return
        self._record_usage("Audiowiedergabe", self.usage_statistics.record_audio_seconds, tag_id, seconds)

    def _record_usage(self, label: str, callback: Callable, *args: object) -> None:
        try:
            callback(*args)
        except BaseException as exc:  # pragma: no cover - statistics must not block the device
            self._emit_status(f"Nutzerstatistik ({label}) konnte nicht gespeichert werden: {exc}")

    def _allow_page_sequence_playback(
        self,
        tag_id: str,
        pages: tuple[PageRecord, ...],
    ) -> bool:
        numbered_pages = {page.page_number for page in pages if page.page_number is not None}
        if not numbered_pages:
            return True

        scan_id = next((page.scan_id for page in pages if page.scan_id), "")
        scan_key = (tag_id, scan_id)
        if scan_id and scan_key in self._suppressed_playback_scans:
            self._emit_status(
                f"Seitenausgabe fuer bereits abgewiesenen Scan {scan_id} unterdrueckt."
            )
            self._stop_start_wait_heartbeat()
            return False

        previous_scan_id = self._last_played_scan_id_by_book.get(tag_id)
        if scan_id and scan_id == previous_scan_id:
            self._last_played_page_numbers_by_book.setdefault(tag_id, set()).update(numbered_pages)
            return True

        previous_pages = self._last_played_page_numbers_by_book.get(tag_id)
        skip_repeat_check = tag_id in self._repeat_page_confirmation_books
        skip_wrong_direction_check = tag_id in self._wrong_direction_confirmation_books
        self._repeat_page_confirmation_books.discard(tag_id)
        self._wrong_direction_confirmation_books.discard(tag_id)

        if skip_wrong_direction_check:
            self._last_played_page_numbers_by_book[tag_id] = set(numbered_pages)
            if scan_id:
                self._last_played_scan_id_by_book[tag_id] = scan_id
            return True

        repeated_pages = previous_pages is not None and bool(numbered_pages & previous_pages)
        if repeated_pages and not skip_repeat_check:
            self._repeat_page_confirmation_books.add(tag_id)
            if scan_id:
                self._suppressed_playback_scans.add(scan_key)
            self._stop_start_wait_heartbeat()
            self._emit_status(
                "Seitenausgabe abgebrochen: mindestens eine Seite wurde unmittelbar zuvor vorgelesen "
                f"({sorted(numbered_pages & previous_pages)})."
            )
            self._play_page_sequence_warning(self.page_ingest_config.repeat_page_message_name)
            return False

        wrong_direction = (
            previous_pages is not None
            and min(numbered_pages) < min(previous_pages)
        )
        if wrong_direction and not skip_wrong_direction_check:
            self._wrong_direction_confirmation_books.add(tag_id)
            if scan_id:
                self._suppressed_playback_scans.add(scan_key)
            self._stop_start_wait_heartbeat()
            self._emit_status(
                "Seitenausgabe abgebrochen: rueckwaerts geblaettert "
                f"(neu {sorted(numbered_pages)}, zuvor {sorted(previous_pages)})."
            )
            self._play_page_sequence_warning(self.page_ingest_config.wrong_direction_message_name)
            return False

        self._last_played_page_numbers_by_book[tag_id] = set(numbered_pages)
        if scan_id:
            self._last_played_scan_id_by_book[tag_id] = scan_id
        return True

    def _handle_page_ingest_failure(self, _request: PageIngestRequest, _exc: BaseException) -> None:
        self._stop_start_wait_heartbeat()

    def _handle_page_audio_ready(self, _page_label: str) -> None:
        self._stop_start_wait_heartbeat()

    def _handle_page_audio_error(self, _exc: BaseException) -> None:
        self._stop_start_wait_heartbeat()

    def _handle_completed_chapters(self, tag_id: str) -> None:
        if self.chapter_assembler is None:
            return
        try:
            assembly_result = self.chapter_assembler.assemble_available_chapters(tag_id)
        except BaseException as exc:  # pragma: no cover - defensive runtime propagation
            self._emit_status(f"Abschnittsbildung fehlgeschlagen: {exc}")
            return
        if not assembly_result.created_chapters:
            return
        chapter_ids = ", ".join(chapter.chapter_id for chapter in assembly_result.created_chapters)
        self._emit_status(f"Neue Abschnitte gespeichert: {chapter_ids}.")
        if self.summary_manager is not None:
            if not self.summary_manager.is_available():
                self._emit_status("Kapitelzusammenfassung uebersprungen: Gemini ist nicht verfuegbar.")
                return
            for chapter in assembly_result.created_chapters:
                try:
                    self.summary_manager.summarize_chapter(tag_id, chapter.chapter_id)
                    self._emit_status(f"Kapitelzusammenfassung gespeichert: {chapter.chapter_id}.")
                except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                    self._emit_status(f"Kapitelzusammenfassung fehlgeschlagen ({chapter.chapter_id}): {exc}")
            return
        if self.summary_service is None:
            return
        for chapter in assembly_result.created_chapters:
            self.summary_service.submit_chapter_summary(tag_id, chapter.chapter_id)

    def _handle_volume_delta(self, delta: int) -> None:
        if self.volume_controller is None:
            self._emit_status(f"Lautstaerke-Aenderung erkannt: Delta {delta:+d}.")
            return
        try:
            if self._volume_interrupt_updates_enabled:
                state = self.volume_controller.apply_requested_volume()
            else:
                state = self.volume_controller.apply_delta(delta)
        except Exception as exc:
            self._emit_status(f"Lautstaerke-Aenderung fehlgeschlagen: {exc}")
            return
        if state is None:
            return
        self._emit_status(
            f"Lautstaerke gesetzt: Stufe {state.level_index + 1}/{state.level_count} ({state.percent}%)."
        )

    def _request_volume_delta_from_encoder_callback(self, delta: int) -> None:
        if self.volume_controller is None:
            return
        try:
            self.volume_controller.request_delta(delta)
        except BaseException as exc:  # pragma: no cover - hardware callback guard
            self._emit_status(f"Lautstaerke-Interrupt fehlgeschlagen: {exc}")

    def _current_volume_percent(self) -> int:
        if self.volume_controller is None:
            return 100
        return self.volume_controller.current_percent()

    def _run_system_audio_worker(self) -> None:
        while True:
            queued_message = self._system_audio_queue.get()
            if queued_message is None:
                self._system_audio_queue.task_done()
                return
            if queued_message.heartbeat_generation is not None:
                with self._heartbeat_lock:
                    if queued_message.heartbeat_generation != self._heartbeat_generation:
                        self._system_audio_queue.task_done()
                        continue
                if self.page_audio_player is not None and self.page_audio_player.is_active():
                    self._system_audio_queue.task_done()
                    continue
            self._play_system_message(queued_message.message_name)
            self._system_audio_queue.task_done()

    def _stop_system_audio_worker(self) -> None:
        worker = getattr(self, "_system_audio_worker", None)
        if worker is None or not worker.is_alive():
            return
        self._system_audio_queue.put(None)
        worker.join(timeout=1.0)


def _build_dummy_capture_runner(duration_s: float) -> Callable[[Event, Callable[[str], None]], None]:
    def _runner(cancel_event: Event, progress_callback: Callable[[str], None]) -> None:
        progress_callback(f"Dummy Capture/OCR laeuft fuer {duration_s:g}s.")
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            if cancel_event.wait(0.05):
                raise ForegroundJobCancelled()
    return _runner


def _build_capture_ocr_runner(
    config: CaptureOCRJobConfig,
    *,
    tag_id: str | None = None,
    book_context_resolver: Callable[[], CaptureBookContext | None] | None = None,
    page_ingest_submitter: Callable[[PageIngestRequest], Event | None] | None = None,
) -> Callable[[Event, Callable[[str], None]], None]:
    from abr.capture_ocr import run_capture_ocr_pages, write_capture_ocr_report
    from abr.hardware.double_page_capture import publish_latest
    from abr.preprocessing.enhance_for_ocr import (
        _write_manifest as write_enhancement_manifest,
        enhance_page_image_path,
    )
    from abr.preprocessing.processor import PreprocessorConfig

    project_root = config.project_root.expanduser().resolve()
    capture_script = project_root / "hardware" / "capture_double_page.py"
    ocr_script = project_root / "hardware" / "run_rapidocr.py"
    capture_output_root = _resolve_under_project(project_root, config.capture_output_root)
    ocr_output_dir = _resolve_under_project(project_root, config.ocr_output_dir)
    artifact_cleaner = ArtifactCleaner(config.artifact_cleanup)
    default_preprocess_config = PreprocessorConfig(denoise_enabled=not config.no_denoise)
    incremental_ingest = page_ingest_submitter is not None and (tag_id is not None or book_context_resolver is not None)

    def _runner(cancel_event: Event, progress_callback: Callable[[str], None]) -> None:
        latest_ocr_dir = capture_output_root / "latest" / "ocr"
        latest_metadata_path = capture_output_root / "latest" / "metadata.json"
        latest_dir = capture_output_root / "latest"
        capture_command = [config.python_executable, str(capture_script), "--output-root", str(capture_output_root)]
        if config.no_denoise:
            capture_command.append("--no-denoise")
        if incremental_ingest:
            capture_command.append("--skip-enhance")
        if config.capture_timeout_ms is not None:
            capture_command.extend(["--timeout-ms", str(config.capture_timeout_ms)])

        progress_callback("Capture startet.")
        _run_subprocess(capture_command, cancel_event=cancel_event, cwd=project_root)
        _raise_if_cancelled(cancel_event)
        capture_metadata = _read_json_file(latest_metadata_path)
        session_dir = _capture_session_dir_from_metadata(capture_metadata, latest_metadata_path)
        stable_output_dir = session_dir / "ocr_text"
        stable_output_dir.mkdir(parents=True, exist_ok=True)
        resolved_tag_id = tag_id
        orientation: str | None = None
        if book_context_resolver is not None:
            progress_callback("Aufnahmen abgeschlossen, NFC-Ergebnis wird abgeholt.")
            context = book_context_resolver()
            if context is None:
                raise RuntimeError("Kein ISO14443A-Tag und keine bekannte ISO15693-Zuordnung gefunden.")
            resolved_tag_id = context.tag_id
            orientation = context.orientation
        preprocess_config = _preprocess_config_for_orientation(default_preprocess_config, orientation)
        if resolved_tag_id is None and incremental_ingest:
            raise RuntimeError("Keine Buch-Tag-ID fuer page-ingest verfuegbar.")

        if not incremental_ingest:
            ocr_command = [
                config.python_executable,
                str(ocr_script),
                "--ocr-dir",
                str(latest_ocr_dir),
                "--output-dir",
                str(ocr_output_dir),
                "--orientation-mode",
                config.orientation_mode,
                "--language",
                config.language,
            ]
            if config.overlay:
                ocr_command.append("--overlay")

            progress_callback("Capture abgeschlossen, OCR startet.")
            _run_subprocess(ocr_command, cancel_event=cancel_event, cwd=project_root)
            _raise_if_cancelled(cancel_event)
            _snapshot_ocr_output(
                source_output_dir=ocr_output_dir,
                stable_output_dir=stable_output_dir,
            )
            progress_callback(f"OCR abgeschlossen, Ergebnis archiviert unter {stable_output_dir}.")
        else:
            case_dir = session_dir / "case"
            if orientation is not None:
                _apply_capture_orientation(case_dir, orientation)
                left_camera, right_camera = _camera_assignment_after_orientation(
                    capture_metadata,
                    orientation,
                )
                progress_callback(
                    "NFC-Zuordnung angewendet: "
                    f"{_orientation_label(orientation)}, "
                    f"linkes Bild = Kamera {left_camera}, "
                    f"rechtes Bild = Kamera {right_camera}, "
                    "Drehung der Seitendatei links = 0 Grad, "
                    "Drehung der Seitendatei rechts = 180 Grad, "
                    f"zusaetzliche OCR-Drehung links/rechts = "
                    f"{preprocess_config.left_page_rotate_deg}/"
                    f"{preprocess_config.right_page_rotate_deg} Grad."
                )
            session_ocr_dir = session_dir / "ocr"
            session_debug_dir = session_dir / "debug"
            stable_metadata_path = session_dir / "metadata.json"
            enhancement_pages = []

            progress_callback("Capture abgeschlossen, Bildvorbereitung links startet.")
            left_artifact = enhance_page_image_path(
                case_dir / "left.jpg",
                page_id="page_1",
                debug_dir=session_debug_dir,
                ocr_dir=session_ocr_dir,
                config=preprocess_config,
            )
            enhancement_pages.append(left_artifact)
            write_enhancement_manifest(
                session_ocr_dir,
                enhancement_pages,
                config=preprocess_config,
                timings={"page_processing_sec": left_artifact.timings.get("page_total_sec", 0.0)},
            )
            _raise_if_cancelled(cancel_event)

            progress_callback("Bildvorbereitung links abgeschlossen, OCR links startet.")
            left_ocr_result = run_capture_ocr_pages(
                ocr_dir=session_ocr_dir,
                output_dir=stable_output_dir,
                page_images=(("page_1", left_artifact.ocr_output_path),),
                write_overlay=config.overlay,
                orientation_mode=config.orientation_mode,
                language=config.language,
                report_filename="left_report.json",
            )
            _raise_if_cancelled(cancel_event)
            left_ingest_completion = page_ingest_submitter(
                _build_page_ingest_request_for_report(
                    tag_id=resolved_tag_id,
                    report_path=left_ocr_result.report_path,
                    session_dir=session_dir,
                    capture_metadata_path=stable_metadata_path,
                    created_at=_optional_str(capture_metadata.get("created_at")),
                    playback_sides=("left",),
                )
            )
            if left_ingest_completion is not None:
                while not left_ingest_completion.wait(timeout=0.05):
                    _raise_if_cancelled(cancel_event)
            _raise_if_cancelled(cancel_event)
            progress_callback("OCR links abgeschlossen, page-ingest fuer die linke Seite eingeplant.")

            progress_callback("Bildvorbereitung rechts startet.")
            right_artifact = enhance_page_image_path(
                case_dir / "right.jpg",
                page_id="page_2",
                debug_dir=session_debug_dir,
                ocr_dir=session_ocr_dir,
                config=preprocess_config,
            )
            enhancement_pages.append(right_artifact)
            enhancement_total_sec = sum(page.timings.get("page_total_sec", 0.0) for page in enhancement_pages)
            write_enhancement_manifest(
                session_ocr_dir,
                enhancement_pages,
                config=preprocess_config,
                timings={"page_processing_sec": enhancement_total_sec, "total_sec": enhancement_total_sec},
            )
            _raise_if_cancelled(cancel_event)

            progress_callback("Bildvorbereitung rechts abgeschlossen, OCR rechts startet.")
            right_ocr_result = run_capture_ocr_pages(
                ocr_dir=session_ocr_dir,
                output_dir=stable_output_dir,
                page_images=(("page_2", right_artifact.ocr_output_path),),
                write_overlay=config.overlay,
                orientation_mode=config.orientation_mode,
                language=config.language,
                report_filename=None,
            )
            _raise_if_cancelled(cancel_event)

            combined_timings = {
                "left_total_sec": left_ocr_result.timings.get("total_sec", 0.0),
                "right_total_sec": right_ocr_result.timings.get("total_sec", 0.0),
                "page_processing_sec": left_ocr_result.timings.get("page_processing_sec", 0.0)
                + right_ocr_result.timings.get("page_processing_sec", 0.0),
                "input_load_sec": left_ocr_result.timings.get("input_load_sec", 0.0)
                + right_ocr_result.timings.get("input_load_sec", 0.0),
            }
            combined_timings["total_sec"] = combined_timings["left_total_sec"] + combined_timings["right_total_sec"]
            final_report_path = stable_output_dir / "report.json"
            write_capture_ocr_report(
                report_path=final_report_path,
                ocr_dir=session_ocr_dir,
                pages=[left_ocr_result.pages[0], right_ocr_result.pages[0]],
                timings=combined_timings,
                orientation_mode=config.orientation_mode,
                language=config.language,
            )
            _update_capture_metadata_after_incremental_processing(
                metadata_path=stable_metadata_path,
                latest_metadata_path=latest_metadata_path,
                session_ocr_dir=session_ocr_dir,
                preprocess_config=preprocess_config,
                enhancement_pages=enhancement_pages,
                enhancement_total_sec=enhancement_total_sec,
            )
            publish_latest(session_dir, latest_dir, raw_only=False)
            shutil.copy2(stable_metadata_path, latest_metadata_path)
            page_ingest_submitter(
                _build_page_ingest_request_for_report(
                    tag_id=resolved_tag_id,
                    report_path=final_report_path,
                    session_dir=session_dir,
                    capture_metadata_path=stable_metadata_path,
                    created_at=_optional_str(capture_metadata.get("created_at")),
                    playback_sides=("right",),
                )
            )
            progress_callback(f"OCR rechts abgeschlossen, Ergebnis archiviert unter {stable_output_dir}.")

        removed_paths = artifact_cleaner.cleanup_after_ocr(
            session_dir=session_dir,
            latest_dir=latest_dir,
            ocr_output_dir=ocr_output_dir,
        )
        if removed_paths:
            removed_text = ", ".join(str(path) for path in removed_paths)
            progress_callback(f"Artefakte nach OCR bereinigt: {removed_text}.")
    return _runner


def _apply_capture_orientation(case_dir: Path, orientation: str) -> None:
    from abr.hardware.double_page_rectify import apply_rotation_in_place

    if orientation == "reader2":
        pass
    elif orientation == "reader1":
        left_path = case_dir / "left.jpg"
        right_path = case_dir / "right.jpg"
        temp_path = case_dir / ".camera_swap.jpg"
        left_path.replace(temp_path)
        right_path.replace(left_path)
        temp_path.replace(right_path)
    else:
        raise ValueError(f"Unbekannte Buchorientierung: {orientation}")

    apply_rotation_in_place(case_dir / "right.jpg", 180)


def _preprocess_config_for_orientation(default_config, orientation: str | None):
    if orientation is None:
        return default_config
    if orientation in {"reader1", "reader2"}:
        return replace(default_config, left_page_rotate_deg=0, right_page_rotate_deg=0)
    raise ValueError(f"Unbekannte Buchorientierung: {orientation}")


def _camera_assignment_after_orientation(
    capture_metadata: dict[str, object],
    orientation: str,
) -> tuple[str, str]:
    slots = capture_metadata.get("slots")
    slots_dict = slots if isinstance(slots, dict) else {}
    left_slot = slots_dict.get("left")
    right_slot = slots_dict.get("right")
    left_camera = _camera_index_label(left_slot)
    right_camera = _camera_index_label(right_slot)
    if orientation == "reader2":
        return left_camera, right_camera
    if orientation == "reader1":
        return right_camera, left_camera
    raise ValueError(f"Unbekannte Buchorientierung: {orientation}")


def _camera_index_label(slot: object) -> str:
    if not isinstance(slot, dict):
        return "unbekannt"
    camera_index = slot.get("camera_index")
    if camera_index is None:
        return "unbekannt"
    return str(camera_index)


def _orientation_label(orientation: str) -> str:
    if orientation == "reader2":
        return "Orientierung 1 / ISO14443A auf Leser 2 / feste Kamera-Zuordnung"
    if orientation == "reader1":
        return "Orientierung 2 / ISO14443A auf Leser 1 / Seiten vertauscht"
    return orientation


def _resolve_under_project(project_root: Path, path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (project_root / expanded).resolve()


def _run_subprocess(command: list[str], *, cancel_event: Event, cwd: Path) -> None:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        while process.poll() is None:
            if cancel_event.wait(0.1):
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
                raise ForegroundJobCancelled()

        output = ""
        if process.stdout is not None:
            output = process.stdout.read().strip()
        if process.returncode != 0:
            if output:
                last_line = output.splitlines()[-1]
                raise RuntimeError(f"Kommando fehlgeschlagen ({process.returncode}): {last_line}")
            raise RuntimeError(f"Kommando fehlgeschlagen ({process.returncode}).")
    finally:
        if process.stdout is not None:
            process.stdout.close()


def _raise_if_cancelled(cancel_event: Event) -> None:
    if cancel_event.is_set():
        raise ForegroundJobCancelled()


def _build_page_ingest_request(config: CaptureOCRJobConfig, *, tag_id: str) -> PageIngestRequest:
    project_root = config.project_root.expanduser().resolve()
    capture_output_root = _resolve_under_project(project_root, config.capture_output_root)
    latest_metadata_path = capture_output_root / "latest" / "metadata.json"
    capture_metadata = _read_json_file(latest_metadata_path)
    session_dir = _capture_session_dir_from_metadata(capture_metadata, latest_metadata_path)
    stable_report_path = session_dir / "ocr_text" / "report.json"
    stable_metadata_path = session_dir / "metadata.json"
    return PageIngestRequest(
        tag_id=tag_id,
        report_path=stable_report_path,
        scan_id=session_dir.name,
        session_dir=session_dir,
        capture_metadata_path=stable_metadata_path,
        created_at=_optional_str(capture_metadata.get("created_at")),
    )


def _build_page_ingest_request_for_report(
    *,
    tag_id: str,
    report_path: Path,
    session_dir: Path,
    capture_metadata_path: Path,
    created_at: str | None,
    playback_sides: tuple[str, ...] | None = None,
) -> PageIngestRequest:
    return PageIngestRequest(
        tag_id=tag_id,
        report_path=report_path,
        scan_id=session_dir.name,
        session_dir=session_dir,
        capture_metadata_path=capture_metadata_path,
        created_at=created_at,
        playback_sides=playback_sides,
    )


def build_page_ingest_service(
    *,
    library_root: Path,
    capture_ocr_config: CaptureOCRJobConfig | None = None,
    language_code: str = "de",
    status_callback: Callable[[str], None] | None = None,
) -> PageIngestService:
    store = BookStore(library_root.expanduser().resolve())
    ingestor = PageIngestor(store, language_code=language_code)
    success_callback = None
    if capture_ocr_config is not None:
        success_callback = _build_page_ingest_cleanup_callback(capture_ocr_config)
    return PageIngestService(
        ingestor,
        status_callback=status_callback,
        success_callback=success_callback,
    )


def _snapshot_ocr_output(*, source_output_dir: Path, stable_output_dir: Path) -> None:
    stable_output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("report.json", "left.txt", "right.txt"):
        source_path = source_output_dir / filename
        if not source_path.exists():
            raise RuntimeError(f"OCR-Ergebnis fehlt: {source_path}")
        shutil.copy2(source_path, stable_output_dir / filename)


def _capture_session_dir_from_metadata(metadata: dict[str, object], metadata_path: Path) -> Path:
    session_dir = metadata.get("session_dir")
    if not session_dir:
        raise RuntimeError(f"Capture-Metadaten ohne session_dir: {metadata_path}")
    return Path(str(session_dir)).expanduser().resolve()


def _read_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"Datei fehlt: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ungueltiges JSON-Dokument: {path}")
    return payload


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _prepare_pages_for_playback(
    pages: tuple[PageRecord, ...],
    playback_sides: tuple[str, ...] | None,
) -> tuple[PageRecord, ...]:
    selected_pages = _select_pages_for_playback(pages, playback_sides)
    return tuple(_strip_page_tail_fragment_for_playback(page) for page in selected_pages)


def _select_pages_for_playback(
    pages: tuple[PageRecord, ...],
    playback_sides: tuple[str, ...] | None,
) -> tuple[PageRecord, ...]:
    if not playback_sides:
        return pages
    wanted_sides = {side.strip().lower() for side in playback_sides}
    return tuple(page for page in pages if page.side in wanted_sides)


def _strip_page_tail_fragment_for_playback(page: PageRecord) -> PageRecord:
    trimmed_text = _strip_tail_fragment_for_playback(page.speak_text, page.tail_fragment)
    if trimmed_text == page.speak_text:
        return page
    return replace(page, speak_text=trimmed_text)


def _strip_tail_fragment_for_playback(speak_text: str, tail_fragment: str | None) -> str:
    stripped = speak_text.strip()
    fragment = tail_fragment.strip() if tail_fragment else _extract_trailing_incomplete_fragment_for_playback(stripped)
    if not stripped or not fragment:
        return stripped
    if stripped == fragment:
        return ""
    if stripped.endswith(fragment):
        return stripped[: -len(fragment)].rstrip()
    return stripped


def _extract_trailing_incomplete_fragment_for_playback(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if _PLAYBACK_SENTENCE_END_RE.search(stripped[-4:]) is not None:
        return None
    matches = list(_PLAYBACK_SENTENCE_END_RE.finditer(stripped))
    if matches:
        fragment = stripped[matches[-1].end():].strip()
        return fragment or None
    return stripped


def _build_page_ingest_cleanup_callback(
    config: CaptureOCRJobConfig,
) -> Callable[[PageIngestRequest, object], list[Path]]:
    artifact_cleaner = ArtifactCleaner(config.artifact_cleanup)
    project_root = config.project_root.expanduser().resolve()
    capture_output_root = _resolve_under_project(project_root, config.capture_output_root)
    latest_dir = capture_output_root / "latest"
    ocr_output_dir = _resolve_under_project(project_root, config.ocr_output_dir)

    def _callback(request: PageIngestRequest, _result: object) -> list[Path]:
        return artifact_cleaner.cleanup_after_ingest(
            session_dir=request.session_dir,
            latest_dir=latest_dir,
            ocr_output_dir=ocr_output_dir,
        )

    return _callback


def _build_chapter_summary_runner(
    *,
    tag_id: str,
    chapter_assembler: ChapterAssembler | None,
    summary_manager: SummaryManager,
    page_audio_player: PageAudioPlayer,
    missing_summary_callback: Callable[[], None] | None = None,
    wait_cancel_callback: Callable[[], None] | None = None,
) -> Callable[[Event, Callable[[str], None]], None]:
    def _runner(cancel_event: Event, progress_callback: Callable[[str], None]) -> None:
        pending_content = None
        if chapter_assembler is not None:
            assembly_result = chapter_assembler.assemble_available_chapters(tag_id)
            if assembly_result.created_chapters:
                progress_callback(
                    "Abschnittsbildung nachgezogen: "
                    + ", ".join(chapter.chapter_id for chapter in assembly_result.created_chapters)
                    + "."
                )
            pending_content = chapter_assembler.collect_pending_content(tag_id)
        _raise_if_cancelled(cancel_event)
        has_completed_chapter = summary_manager.has_completed_chapters(tag_id)
        if pending_content is not None and pending_content.text.strip():
            if has_completed_chapter:
                progress_callback(
                    "Temporaere Kapitelzusammenfassung wird aus dem letzten Abschnitt und "
                    f"{len(pending_content.text)} Zeichen offenem Text erzeugt."
                )
            else:
                progress_callback(
                    "Temporaere Kapitelzusammenfassung wird aus "
                    f"{len(pending_content.text)} Zeichen offenem Text erzeugt; "
                    "es gibt noch keinen abgeschlossenen Abschnitt."
                )
            chapter, summary = summary_manager.summarize_chapter_progress(
                tag_id,
                pending_content.text,
                pending_page_ids=pending_content.page_ids,
                pending_page_numbers=pending_content.page_numbers,
            )
            _raise_if_cancelled(cancel_event)
            page_audio_player.enqueue_text(
                _temporary_chapter_summary_audio_label(chapter, pending_content.page_numbers),
                summary.text,
                language_code=_summary_language(summary),
            )
            progress_callback("Temporaere Kapitelzusammenfassung bereit; sie wird nicht gespeichert.")
            return
        if not has_completed_chapter:
            progress_callback("Kapitelzusammenfassung uebersprungen: noch kein abgeschlossener Abschnitt verfuegbar.")
            if wait_cancel_callback is not None:
                wait_cancel_callback()
            if missing_summary_callback is not None:
                missing_summary_callback()
            return
        progress_callback("Kapitelzusammenfassung wird geladen oder aktualisiert.")
        chapter, summary = summary_manager.summarize_latest_chapter(tag_id)
        progress_callback(
            "Kapitelzusammenfassung Quelle: "
            + _chapter_summary_source_name(chapter, summary)
            + "."
        )
        _raise_if_cancelled(cancel_event)
        page_audio_player.enqueue_text(
            _chapter_summary_audio_label(chapter),
            summary.text,
            language_code=_summary_language(summary),
        )
        progress_callback(f"Kapitelzusammenfassung bereit: {chapter.chapter_id}.")

    return _runner


def _build_book_summary_runner(
    *,
    tag_id: str,
    chapter_assembler: ChapterAssembler | None,
    summary_manager: SummaryManager,
    page_audio_player: PageAudioPlayer,
    missing_summary_callback: Callable[[], None] | None = None,
    wait_cancel_callback: Callable[[], None] | None = None,
) -> Callable[[Event, Callable[[str], None]], None]:
    def _runner(cancel_event: Event, progress_callback: Callable[[str], None]) -> None:
        if chapter_assembler is not None:
            assembly_result = chapter_assembler.assemble_available_chapters(tag_id)
            if assembly_result.created_chapters:
                progress_callback(
                    "Abschnittsbildung nachgezogen: "
                    + ", ".join(chapter.chapter_id for chapter in assembly_result.created_chapters)
                    + "."
                )
        _raise_if_cancelled(cancel_event)
        if not summary_manager.has_completed_chapters(tag_id):
            progress_callback("Buchzusammenfassung uebersprungen: noch kein abgeschlossener Abschnitt verfuegbar.")
            if wait_cancel_callback is not None:
                wait_cancel_callback()
            if missing_summary_callback is not None:
                missing_summary_callback()
            return
        progress_callback("Buchzusammenfassung wird geladen oder aktualisiert.")
        summary = summary_manager.summarize_book_so_far(tag_id)
        progress_callback(
            f"Buchzusammenfassung Quelle: {_book_summary_source_name(summary_manager, tag_id)}; "
            f"{len(summary.text)} Zeichen."
        )
        _raise_if_cancelled(cancel_event)
        page_audio_player.enqueue_text(
            "was-bisher-geschah",
            summary.text,
            language_code=_summary_language(summary),
        )
        progress_callback("Buchzusammenfassung bereit.")

    return _runner


def _chapter_summary_audio_label(chapter) -> str:
    if chapter.start_page is not None and chapter.end_page is not None:
        if chapter.start_page == chapter.end_page:
            return f"kapitel-zusammenfassung:{chapter.start_page}"
        return f"kapitel-zusammenfassung:{chapter.start_page}-{chapter.end_page}"
    return f"kapitel-zusammenfassung:{chapter.chapter_id}"


def _temporary_chapter_summary_audio_label(chapter, pending_page_numbers: tuple[int, ...]) -> str:
    start_page = getattr(chapter, "start_page", None) if chapter is not None else None
    end_page = pending_page_numbers[-1] if pending_page_numbers else None
    if start_page is not None and end_page is not None:
        return f"kapitel-zusammenfassung-temporaer:{start_page}-{end_page}"
    return "kapitel-zusammenfassung-temporaer"


def _book_summary_source_name(summary_manager: SummaryManager, tag_id: str) -> str:
    store = getattr(summary_manager, "store", None)
    config = getattr(summary_manager, "config", None)
    filename = getattr(config, "book_summary_filename", "book_so_far_summary.json")
    if store is None or not hasattr(store, "book_dir"):
        return str(filename)
    return str(store.book_dir(tag_id) / "summaries" / str(filename))


def _summary_language(summary) -> str:
    metadata = getattr(summary, "metadata", None)
    if not isinstance(metadata, dict):
        return "de"
    language = metadata.get("language")
    return language if isinstance(language, str) else "de"


def _chapter_summary_source_name(chapter, summary) -> str:
    summary_path = getattr(chapter, "summary_path", None)
    if summary_path is not None:
        name = getattr(summary_path, "name", None)
        if isinstance(name, str) and name:
            return name
    summary_id = getattr(summary, "summary_id", None)
    if isinstance(summary_id, str) and summary_id:
        return f"{summary_id}.json"
    chapter_id = getattr(chapter, "chapter_id", None)
    if isinstance(chapter_id, str) and chapter_id:
        return f"{chapter_id}_summary.json"
    return "unbekannt"


def _update_capture_metadata_after_incremental_processing(
    *,
    metadata_path: Path,
    latest_metadata_path: Path,
    session_ocr_dir: Path,
    preprocess_config,
    enhancement_pages: list[object],
    enhancement_total_sec: float,
) -> None:
    metadata = _read_json_file(metadata_path)
    timings = metadata.setdefault("timings", {})
    if isinstance(timings, dict):
        timings["enhancement_total_sec"] = enhancement_total_sec
    metadata["ocr_dir"] = str(session_ocr_dir)
    metadata["debug_dir"] = str(metadata_path.parent / "debug")
    metadata["enhancement"] = {
        "manifest_path": str(session_ocr_dir / "manifest.json"),
        "config": {
            "ocr_input_mode": getattr(preprocess_config, "ocr_input_mode", None),
            "denoise_enabled": getattr(preprocess_config, "denoise_enabled", None),
            "sharpen_alpha": getattr(preprocess_config, "sharpen_alpha", None),
            "sharpen_sigma": getattr(preprocess_config, "sharpen_sigma", None),
            "threshold_block_size": getattr(preprocess_config, "threshold_block_size", None),
            "threshold_c": getattr(preprocess_config, "threshold_c", None),
        },
        "timings": {
            "page_processing_sec": enhancement_total_sec,
            "total_sec": enhancement_total_sec,
        },
        "pages": [
            {
                "page_id": getattr(page, "page_id", None),
                "source_path": str(getattr(page, "source_path")),
                "ocr_output_path": str(getattr(page, "ocr_output_path")),
                "debug_paths": {
                    stage: str(path)
                    for stage, path in getattr(page, "debug_paths", {}).items()
                },
                "timings": getattr(page, "timings", {}),
            }
            for page in enhancement_pages
        ],
    }
    metadata_text = json.dumps(metadata, indent=2, ensure_ascii=False)
    metadata_path.write_text(metadata_text, encoding="utf-8")
    latest_metadata_path.write_text(metadata_text, encoding="utf-8")
