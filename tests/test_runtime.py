from __future__ import annotations

import time
from queue import Empty
from pathlib import Path
import json
from types import SimpleNamespace
import pytest

from abr.control import (
    ABRAction,
    ABRActionType,
    AudioVolumeState,
    ArtifactCleanupConfig,
    CaptureOCRJobConfig,
    ForegroundJobEventType,
    ForegroundJobManager,
    FrontPanelActionRouter,
    FrontPanelButtonEvent,
    FrontPanelButtonState,
    FrontPanelEncoderEvent,
    FrontPanelEventType,
    FrontPanelMonitor,
    PageIngestRuntimeConfig,
    RuntimeController,
    WorkState,
    build_page_ingest_service,
)
from abr.book import ChapterAssemblyResult, ChapterRecord, SummaryRecord
from abr.hardware.control_panel import CONTROL_PANEL_PINS
from abr.hardware.nfc_gateway import NFCTag, NFCTagScan
from abr.control import runtime as runtime_module


class _FakeGPIO:
    def __init__(self) -> None:
        self.levels = {pin: True for pin in CONTROL_PANEL_PINS}

    def configure_inputs(self, pins) -> None:
        self.configured = list(pins)

    def read_levels(self, pins) -> dict[int, bool]:
        return {pin: self.levels[pin] for pin in pins}

    def close(self) -> None:
        return None


class _StaticNFCTagReader:
    def __init__(self, tag_id: str | None) -> None:
        self.tag_id = tag_id
        self.read_calls = 0

    def read_tag_id(self) -> str | None:
        self.read_calls += 1
        return self.tag_id


class _AsyncNFCTagReader(_StaticNFCTagReader):
    def __init__(self, scan: NFCTagScan) -> None:
        super().__init__(None)
        self.scan = scan
        self.start_calls = 0
        self.fetch_calls = 0

    def start_tag_scan(self) -> None:
        self.start_calls += 1

    def fetch_tag_scan(self) -> NFCTagScan:
        self.fetch_calls += 1
        return self.scan


class _FakePageAudioPlayer:
    def __init__(self) -> None:
        self.enqueued: list[list[str]] = []
        self.enqueued_texts: list[tuple[str, str]] = []
        self.active = False
        self.cancel_calls = 0
        self.shutdown_calls = 0
        self.audio_ready_callback = None
        self.error_callback = None

    def enqueue_pages(self, pages) -> None:
        self.enqueued.append([page.speak_text for page in pages])
        self.active = True

    def enqueue_text(self, label: str, text: str, *, language_code: str | None = None) -> None:
        self.enqueued_texts.append((label, text))
        self.active = True

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.active = False

    def is_active(self) -> bool:
        return self.active

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        self.shutdown_calls += 1
        self.active = False

    def set_audio_ready_callback(self, callback) -> None:
        self.audio_ready_callback = callback

    def set_error_callback(self, callback) -> None:
        self.error_callback = callback


class _FakeVolumeController:
    def __init__(self) -> None:
        self.initialized = False
        self.applied_deltas: list[int] = []
        self.requested_deltas: list[int] = []
        self.apply_requested_calls = 0
        self.percent = 91

    def initialize(self):
        self.initialized = True
        return AudioVolumeState(level_index=8, level_count=10, percent=91)

    def apply_delta(self, delta: int):
        self.applied_deltas.append(delta)
        self.percent = 100
        return AudioVolumeState(level_index=9, level_count=10, percent=100)

    def request_delta(self, delta: int):
        self.requested_deltas.append(delta)
        self.percent = max(20, min(100, self.percent + (delta * 9)))
        return AudioVolumeState(level_index=9, level_count=10, percent=self.percent)

    def apply_requested_volume(self):
        self.apply_requested_calls += 1
        return AudioVolumeState(level_index=9, level_count=10, percent=self.percent)

    def current_percent(self) -> int:
        return self.percent

    def uses_software_volume(self) -> bool:
        return True


class _FakeSynthBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Path]] = []

    def synthesize_to_file(self, text: str, output_path: Path, *, input_type: str = "text") -> Path:
        self.calls.append((text, input_type, output_path))
        output_path.write_text("ok", encoding="utf-8")
        return output_path


class _FakeChapterAssembler:
    def __init__(self, created_chapters=None, *, pending_text: str = "") -> None:
        self.created_chapters = tuple(created_chapters or ())
        self.pending_text = pending_text
        self.calls: list[str] = []

    def assemble_available_chapters(self, tag_id: str):
        self.calls.append(tag_id)
        return ChapterAssemblyResult(tag_id=tag_id, created_chapters=self.created_chapters)

    def collect_pending_content(self, tag_id: str):
        return SimpleNamespace(
            tag_id=tag_id,
            text=self.pending_text,
            page_ids=("page_0012",),
            page_numbers=(12,),
        )


class _FakeSummaryManager:
    def __init__(self, *, latest_text: str = "Kapitelzusammenfassung.", book_text: str = "Was bisher geschah.") -> None:
        self.latest_text = latest_text
        self.book_text = book_text
        self.latest_calls: list[str] = []
        self.progress_calls: list[tuple[str, str, tuple[str, ...], tuple[int, ...]]] = []
        self.book_calls: list[str] = []
        self.auto_calls: list[tuple[str, str]] = []
        self.available = True
        self.completed_chapters = True
        self.latest_summary_available = True

    def is_available(self) -> bool:
        return self.available

    def has_completed_chapters(self, tag_id: str) -> bool:
        del tag_id
        return self.completed_chapters

    def summarize_chapter(self, tag_id: str, chapter_id: str, *, force: bool = False):
        del force
        self.auto_calls.append((tag_id, chapter_id))
        return SummaryRecord(
            summary_id=f"{chapter_id}_summary",
            summary_type="chapter",
            updated_at="2026-07-04T12:00:00Z",
            text=self.latest_text,
            source_chapter_ids=[chapter_id],
            model_name="fake",
        )

    def summarize_latest_chapter(self, tag_id: str, *, force: bool = False):
        del force
        self.latest_calls.append(tag_id)
        chapter = ChapterRecord(
            chapter_id="chapter_0001",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("summary.txt"),
            page_ids=["page_0010", "page_0011"],
            page_numbers=[10, 11],
            start_page=10,
            end_page=11,
            summary_path=Path("chapter_0001_summary.json"),
        )
        summary = SummaryRecord(
            summary_id="chapter_0001_summary",
            summary_type="chapter",
            updated_at="2026-07-04T12:00:00Z",
            text=self.latest_text,
            source_chapter_ids=["chapter_0001"],
            model_name="fake",
        )
        return chapter, summary

    def summarize_chapter_progress(
        self,
        tag_id: str,
        pending_text: str,
        *,
        pending_page_ids: tuple[str, ...] = (),
        pending_page_numbers: tuple[int, ...] = (),
    ):
        self.progress_calls.append(
            (tag_id, pending_text, pending_page_ids, pending_page_numbers)
        )
        chapter = (
            ChapterRecord(
                chapter_id="chapter_0001",
                created_at="2026-07-04T12:00:00Z",
                completed_at="2026-07-04T12:00:00Z",
                text_path=Path("summary.txt"),
                page_ids=["page_0010", "page_0011"],
                page_numbers=[10, 11],
                start_page=10,
                end_page=11,
                summary_path=Path("chapter_0001_summary.json"),
            )
            if self.completed_chapters
            else None
        )
        return chapter, SummaryRecord(
            summary_id="temporary_chapter_progress",
            summary_type="temporary_chapter_progress",
            updated_at="2026-08-01T12:00:00Z",
            text="Temporäre Zusammenfassung mit offenem Text.",
            source_chapter_ids=["chapter_0001"] if chapter is not None else [],
            model_name="fake",
            metadata={"temporary": True},
        )

    def load_latest_chapter_summary(self, tag_id: str):
        self.latest_calls.append(tag_id)
        if not self.latest_summary_available:
            return None
        chapter = ChapterRecord(
            chapter_id="chapter_0001",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("summary.txt"),
            page_ids=["page_0010", "page_0011"],
            page_numbers=[10, 11],
            start_page=10,
            end_page=11,
            summary_path=Path("chapter_0001_summary.json"),
        )
        summary = SummaryRecord(
            summary_id="chapter_0001_summary",
            summary_type="chapter",
            updated_at="2026-07-04T12:00:00Z",
            text=self.latest_text,
            source_chapter_ids=["chapter_0001"],
            model_name="fake",
        )
        return chapter, summary

    def summarize_book_so_far(self, tag_id: str, *, force: bool = False):
        del force
        self.book_calls.append(tag_id)
        return SummaryRecord(
            summary_id="book_so_far_summary",
            summary_type="book_so_far",
            updated_at="2026-07-04T12:00:00Z",
            text=self.book_text,
            source_chapter_ids=["chapter_0001"],
            model_name="fake",
        )


class _FakeSummaryService:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, str]] = []
        self.shutdown_calls = 0

    def submit_chapter_summary(self, tag_id: str, chapter_id: str) -> None:
        self.submitted.append((tag_id, chapter_id))

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        del join_timeout_s
        self.shutdown_calls += 1


def _start_stop_action() -> ABRAction:
    router = FrontPanelActionRouter()
    event = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control="start_stop_nfc",
        label="Start / Stop / NFC",
        monotonic_time=1.0,
        pin=17,
        state=FrontPanelButtonState.PRESSED,
    )
    action = router.translate_event(event)
    assert action is None
    delayed_actions = router.drain_pending_actions(monotonic_time=1.3)
    assert len(delayed_actions) == 1
    return delayed_actions[0]


def _button_down_action(control: str, *, monotonic_time: float = 1.0) -> ABRAction:
    label_map = {
        "start_stop_nfc": "Start / Stop / NFC",
        "book_summary": "Buch-Zusammenfassung",
        "chapter_summary": "Kapitel-/Letzte-Seiten-Zusammenfassung",
        "encoder_button": "EC11-Taster",
    }
    pin_map = {
        "start_stop_nfc": 17,
        "book_summary": 22,
        "chapter_summary": 24,
        "encoder_button": 16,
    }
    router = FrontPanelActionRouter()
    event = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control=control,
        label=label_map[control],
        monotonic_time=monotonic_time,
        pin=pin_map[control],
        state=FrontPanelButtonState.PRESSED,
    )
    action = router.translate_event(event)
    if action is not None:
        return action
    delayed_actions = router.drain_pending_actions(monotonic_time=monotonic_time + 0.3)
    assert len(delayed_actions) == 1
    return delayed_actions[0]


def test_foreground_job_manager_emits_started_and_completed() -> None:
    manager = ForegroundJobManager()
    handle = manager.start_dummy_capture_ocr(0.05)

    events = []
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            event = manager.get_event(timeout=0.2)
            events.append(event)
            if event.event_type == ForegroundJobEventType.COMPLETED:
                break
        except Empty:
            pass

    manager.shutdown()

    assert handle.job_id == "job_0001"
    event_types = [event.event_type for event in events]
    assert event_types[0] == ForegroundJobEventType.STARTED
    assert event_types[-1] == ForegroundJobEventType.COMPLETED
    assert ForegroundJobEventType.PROGRESS in event_types
    assert manager.is_busy() is False


def test_foreground_job_manager_can_cancel_running_job() -> None:
    manager = ForegroundJobManager()
    manager.start_dummy_capture_ocr(0.5)
    assert manager.cancel_current_job() is True

    events = []
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            event = manager.get_event(timeout=0.2)
            events.append(event)
            if event.event_type == ForegroundJobEventType.CANCELLED:
                break
        except Empty:
            pass

    manager.shutdown()

    event_types = [event.event_type for event in events]
    assert event_types[0] == ForegroundJobEventType.STARTED
    assert event_types[-1] == ForegroundJobEventType.CANCELLED
    assert ForegroundJobEventType.PROGRESS in event_types
    assert ForegroundJobEventType.CANCEL_REQUESTED in event_types
    assert manager.is_busy() is False


def test_runtime_controller_start_stop_drives_dummy_job() -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        dummy_capture_job_seconds=0.5,
    )

    action = _start_stop_action()
    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(action)
        controller.process_job_events()
        assert controller.work_state == WorkState.CAPTURE_OCR_RUNNING

        controller.handle_action(action)
        controller.process_job_events()
        assert controller.work_state == WorkState.CANCELLING_WORK

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and controller.work_state != WorkState.IDLE:
            controller.process_job_events()
            time.sleep(0.01)

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(played_messages) < 2:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert any("Dummy Capture/OCR gestartet" in status for status in statuses)
    assert any("Abbruch angefordert" in status for status in statuses)
    assert any("abgebrochen" in status for status in statuses)
    assert played_messages == ["bing", "abbruch"]


def test_runtime_controller_repeats_start_heartbeat_while_waiting_for_readout(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    manager.start_capture_ocr = lambda config: None  # type: ignore[method-assign]
    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("BOOKKNOWN")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        capture_ocr_enabled=True,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKKNOWN",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
        ),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline and len(played_messages) < 3:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert played_messages.count("bing") >= 3


def test_runtime_controller_stops_start_heartbeat_when_first_page_audio_is_ready(tmp_path: Path) -> None:
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    manager.start_capture_ocr = lambda config: None  # type: ignore[method-assign]
    page_audio_player = _FakePageAudioPlayer()
    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("BOOKKNOWN")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        capture_ocr_enabled=True,
        page_audio_player=page_audio_player,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKKNOWN",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
        ),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        assert page_audio_player.audio_ready_callback is not None
        page_audio_player.audio_ready_callback("left:1")
        time.sleep(0.12)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert played_messages == ["bing"]


def test_runtime_controller_stops_heartbeat_and_plays_empty_page_when_ingest_has_no_speakable_pages(
    tmp_path: Path,
) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    manager.start_capture_ocr = lambda config: None  # type: ignore[method-assign]
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        capture_ocr_enabled=True,
        page_audio_player=_FakePageAudioPlayer(),
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKKNOWN",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
            error_message_name="fehler",
            empty_page_message_name="empty_page.wav",
        ),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline and played_messages.count("bing") < 2:
            time.sleep(0.01)

        empty_pages = (
            runtime_module.PageRecord(
                page_id="page_1",
                scan_id="scan_empty",
                created_at="2026-07-03T21:02:47Z",
                side="left",
                clean_text="",
                speak_text="",
            ),
            runtime_module.PageRecord(
                page_id="page_2",
                scan_id="scan_empty",
                created_at="2026-07-03T21:02:47Z",
                side="right",
                clean_text="",
                speak_text="",
            ),
        )
        controller._handle_page_ingest_result(
            runtime_module.PageIngestRequest(
                tag_id="BOOKKNOWN",
                report_path=tmp_path / "report.json",
            ),
            runtime_module.PageIngestResult(
                tag_id="BOOKKNOWN",
                scan_record=None,  # type: ignore[arg-type]
                pages=empty_pages,
                scan_manifest_path=tmp_path / "scan.json",
                saved_page_paths=(),
            ),
        )
        time.sleep(0.12)
        message_count_after_stop = len(played_messages)
        time.sleep(0.12)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.ERROR
    assert "empty_page.wav" in played_messages
    assert "fehler" not in played_messages
    assert len(played_messages) == message_count_after_stop
    assert any("keine vorlesbaren Seiten" in status for status in statuses)


def test_runtime_controller_can_cancel_start_wait_heartbeat_with_stop(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    manager.start_capture_ocr = lambda config: None  # type: ignore[method-assign]
    page_audio_player = _FakePageAudioPlayer()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        capture_ocr_enabled=True,
        page_audio_player=page_audio_player,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKKNOWN",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
            cancel_work_message_name="abbruch",
        ),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        action = _start_stop_action()
        controller.handle_action(action)
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline and played_messages.count("bing") < 2:
            time.sleep(0.01)

        controller.handle_action(action)
        time.sleep(0.12)
        message_count_after_stop = len(played_messages)

        controller._handle_page_ingest_result(
            runtime_module.PageIngestRequest(
                tag_id="BOOKKNOWN",
                report_path=tmp_path / "report.json",
            ),
            runtime_module.PageIngestResult(
                tag_id="BOOKKNOWN",
                scan_record=None,  # type: ignore[arg-type]
                pages=(
                    runtime_module.PageRecord(
                        page_id="page_1",
                        scan_id="scan_late",
                        created_at="2026-07-03T21:02:47Z",
                        side="left",
                        clean_text="Hallo",
                        speak_text="Hallo",
                    ),
                ),
                scan_manifest_path=tmp_path / "scan.json",
                saved_page_paths=(),
            ),
        )
        time.sleep(0.12)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert page_audio_player.enqueued == []
    assert played_messages[-1] == "abbruch"
    assert len(played_messages) == message_count_after_stop
    assert any("Wartezustand wird abgebrochen" in status for status in statuses)


def test_capture_ocr_runner_invokes_capture_then_ocr(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    recorded_commands: list[list[str]] = []
    latest_metadata_path = tmp_path / "captures" / "latest" / "metadata.json"
    latest_metadata_path.parent.mkdir(parents=True)
    session_dir = tmp_path / "captures" / "scan_test_001"
    session_dir.mkdir(parents=True)
    latest_metadata_path.write_text(
        json.dumps({"session_dir": str(session_dir)}, indent=2),
        encoding="utf-8",
    )
    latest_ocr_output_dir = tmp_path / "runs" / "latest_rapidocr"
    latest_ocr_output_dir.mkdir(parents=True)
    (latest_ocr_output_dir / "report.json").write_text("{}", encoding="utf-8")
    (latest_ocr_output_dir / "left.txt").write_text("Links\n", encoding="utf-8")
    (latest_ocr_output_dir / "right.txt").write_text("Rechts\n", encoding="utf-8")

    def _fake_run_subprocess(command: list[str], *, cancel_event, cwd: Path) -> None:
        recorded_commands.append(command)

    original = runtime_module._run_subprocess
    runtime_module._run_subprocess = _fake_run_subprocess
    try:
        runner = runtime_module._build_capture_ocr_runner(
            CaptureOCRJobConfig(
                python_executable="/usr/bin/python3",
                project_root=tmp_path,
                capture_output_root=Path("captures"),
                ocr_output_dir=Path("runs/latest_rapidocr"),
                no_denoise=True,
                overlay=False,
                orientation_mode="off",
            )
        )
        runner(runtime_module.Event(), lambda message: None)
    finally:
        runtime_module._run_subprocess = original

    assert recorded_commands == [
        [
            "/usr/bin/python3",
            str(tmp_path / "hardware" / "capture_double_page.py"),
            "--output-root",
            str((tmp_path / "captures").resolve()),
            "--no-denoise",
        ],
        [
            "/usr/bin/python3",
            str(tmp_path / "hardware" / "run_rapidocr.py"),
            "--ocr-dir",
            str((tmp_path / "captures" / "latest" / "ocr").resolve()),
            "--output-dir",
            str((tmp_path / "runs" / "latest_rapidocr").resolve()),
                "--orientation-mode",
                "off",
                "--language",
                "de",
            ],
    ]
    assert (session_dir / "ocr_text" / "report.json").exists()
    assert (session_dir / "ocr_text" / "left.txt").read_text(encoding="utf-8") == "Links\n"
    assert latest_metadata_path.exists()
    assert latest_ocr_output_dir.exists()


def test_capture_ocr_runner_cleans_transient_artifacts_after_ocr_in_production_mode(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    recorded_commands: list[list[str]] = []
    progress_messages: list[str] = []
    latest_dir = tmp_path / "captures" / "latest"
    latest_metadata_path = latest_dir / "metadata.json"
    latest_dir.mkdir(parents=True)
    session_dir = tmp_path / "captures" / "scan_test_003"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({"session_dir": str(session_dir)}, indent=2),
        encoding="utf-8",
    )
    latest_metadata_path.write_text(
        json.dumps({"session_dir": str(session_dir)}, indent=2),
        encoding="utf-8",
    )
    for root in (session_dir, latest_dir):
        for relative_name in ("raw", "rectified", "case", "ocr", "debug"):
            (root / relative_name).mkdir(parents=True)
    latest_ocr_output_dir = tmp_path / "runs" / "latest_rapidocr"
    latest_ocr_output_dir.mkdir(parents=True)
    (latest_ocr_output_dir / "report.json").write_text("{}", encoding="utf-8")
    (latest_ocr_output_dir / "left.txt").write_text("Links\n", encoding="utf-8")
    (latest_ocr_output_dir / "right.txt").write_text("Rechts\n", encoding="utf-8")

    def _fake_run_subprocess(command: list[str], *, cancel_event, cwd: Path) -> None:
        recorded_commands.append(command)

    original = runtime_module._run_subprocess
    runtime_module._run_subprocess = _fake_run_subprocess
    try:
        runner = runtime_module._build_capture_ocr_runner(
            CaptureOCRJobConfig(
                python_executable="/usr/bin/python3",
                project_root=tmp_path,
                capture_output_root=Path("captures"),
                ocr_output_dir=Path("runs/latest_rapidocr"),
                no_denoise=True,
                overlay=False,
                orientation_mode="off",
                artifact_cleanup=ArtifactCleanupConfig(
                    mode="production",
                    stage="after-ocr",
                ),
            )
        )
        runner(runtime_module.Event(), progress_messages.append)
    finally:
        runtime_module._run_subprocess = original

    assert len(recorded_commands) == 2
    assert (session_dir / "ocr_text" / "report.json").exists()
    assert (session_dir / "metadata.json").exists()
    for relative_name in ("raw", "rectified", "case", "ocr", "debug"):
        assert (session_dir / relative_name).exists() is False
        assert (latest_dir / relative_name).exists() is False
    assert latest_metadata_path.exists()
    assert latest_ocr_output_dir.exists() is False
    assert any("Artefakte nach OCR bereinigt" in message for message in progress_messages)


def test_capture_ocr_runner_submits_left_then_right_ingest_requests_in_incremental_mode(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    recorded_commands: list[list[str]] = []
    submitted_requests: list[runtime_module.PageIngestRequest] = []
    published_latest: list[Path] = []
    combined_reports: list[Path] = []

    latest_dir = tmp_path / "captures" / "latest"
    latest_metadata_path = latest_dir / "metadata.json"
    latest_dir.mkdir(parents=True)
    session_dir = tmp_path / "captures" / "scan_test_incremental"
    case_dir = session_dir / "case"
    ocr_dir = session_dir / "ocr"
    debug_dir = session_dir / "debug"
    for path in (case_dir, ocr_dir, debug_dir):
        path.mkdir(parents=True, exist_ok=True)
    stable_metadata_path = session_dir / "metadata.json"
    metadata_payload = {
        "created_at": "2026-07-02T15:45:00Z",
        "session_dir": str(session_dir),
        "timings": {},
    }
    stable_metadata_path.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
    latest_metadata_path.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")

    def _fake_run_subprocess(command: list[str], *, cancel_event, cwd: Path) -> None:
        del cancel_event, cwd
        recorded_commands.append(command)

    def _fake_enhance_page_image_path(source_path, *, page_id, debug_dir, ocr_dir, config):
        del debug_dir, config
        output_path = ocr_dir / ("left.png" if page_id == "page_1" else "right.png")
        output_path.write_text(page_id, encoding="utf-8")
        return SimpleNamespace(
            page_id=page_id,
            source_path=Path(source_path),
            ocr_output_path=output_path,
            debug_paths={},
            timings={"page_total_sec": 0.1 if page_id == "page_1" else 0.2},
        )

    def _fake_write_manifest(ocr_dir, pages, *, config, timings):
        del config, timings
        (ocr_dir / "manifest.json").write_text(
            json.dumps({"pages": [page.page_id for page in pages]}, indent=2),
            encoding="utf-8",
        )
        return ocr_dir / "manifest.json"

    def _fake_run_capture_ocr_pages(*, ocr_dir, output_dir, page_images, write_overlay, orientation_mode, language, report_filename):
        del ocr_dir, write_overlay, orientation_mode, language
        output_dir.mkdir(parents=True, exist_ok=True)
        page_id, image_path = page_images[0]
        slot = "left" if page_id == "page_1" else "right"
        report_path = output_dir / ("left_report.json" if slot == "left" else "right_report.json")
        if report_filename:
            report_path.write_text("{}", encoding="utf-8")
        (output_dir / f"{slot}.txt").write_text(f"{slot}\n", encoding="utf-8")
        page_result = SimpleNamespace(
            page_id=page_id,
            slot=slot,
            source_path=Path(image_path),
            text_path=output_dir / f"{slot}.txt",
            rotation_deg=0,
            orientation_reason="off",
            text=slot,
            lines=[],
            debug_paths={},
            timings={"page_total_sec": 0.3 if slot == "left" else 0.4},
        )
        return SimpleNamespace(
            report_path=report_path,
            pages=[page_result],
            timings={
                "total_sec": 0.3 if slot == "left" else 0.4,
                "page_processing_sec": 0.3 if slot == "left" else 0.4,
                "input_load_sec": 0.0,
            },
        )

    def _fake_write_capture_ocr_report(*, report_path, ocr_dir, pages, timings, orientation_mode, language):
        del ocr_dir, pages, timings, orientation_mode, language
        combined_reports.append(report_path)
        report_path.write_text("{}", encoding="utf-8")

    def _fake_publish_latest(session_dir_arg: Path, latest_dir_arg: Path, *, raw_only: bool) -> None:
        assert session_dir_arg == session_dir
        assert latest_dir_arg == latest_dir
        assert raw_only is False
        published_latest.append(session_dir_arg)

    original_run_subprocess = runtime_module._run_subprocess
    original_detect_orientation = runtime_module._detect_capture_orientation
    original_apply_orientation = runtime_module._apply_capture_orientation
    runtime_module._run_subprocess = _fake_run_subprocess
    runtime_module._detect_capture_orientation = lambda case_dir, *, language, preprocess_config: {
        "rotation_deg": 0,
        "reason": f"test {case_dir} {language}",
    }
    runtime_module._apply_capture_orientation = lambda case_dir, orientation: None

    import abr.capture_ocr as capture_ocr_module
    import abr.hardware.double_page_capture as double_page_capture_module
    import abr.preprocessing.enhance_for_ocr as enhance_module

    original_enhance = enhance_module.enhance_page_image_path
    original_manifest = enhance_module._write_manifest
    original_run_pages = capture_ocr_module.run_capture_ocr_pages
    original_write_report = capture_ocr_module.write_capture_ocr_report
    original_publish_latest = double_page_capture_module.publish_latest
    enhance_module.enhance_page_image_path = _fake_enhance_page_image_path  # type: ignore[method-assign]
    enhance_module._write_manifest = _fake_write_manifest  # type: ignore[method-assign]
    capture_ocr_module.run_capture_ocr_pages = _fake_run_capture_ocr_pages  # type: ignore[method-assign]
    capture_ocr_module.write_capture_ocr_report = _fake_write_capture_ocr_report  # type: ignore[method-assign]
    double_page_capture_module.publish_latest = _fake_publish_latest  # type: ignore[method-assign]
    try:
        runner = runtime_module._build_capture_ocr_runner(
            runtime_module.CaptureOCRJobConfig(
                python_executable="/usr/bin/python3",
                project_root=tmp_path,
                capture_output_root=Path("captures"),
                no_denoise=True,
                orientation_mode="off",
            ),
            tag_id="BOOK77",
            page_ingest_submitter=submitted_requests.append,
        )
        runner(runtime_module.Event(), lambda message: None)
    finally:
        runtime_module._run_subprocess = original_run_subprocess
        runtime_module._detect_capture_orientation = original_detect_orientation
        runtime_module._apply_capture_orientation = original_apply_orientation
        enhance_module.enhance_page_image_path = original_enhance  # type: ignore[method-assign]
        enhance_module._write_manifest = original_manifest  # type: ignore[method-assign]
        capture_ocr_module.run_capture_ocr_pages = original_run_pages  # type: ignore[method-assign]
        capture_ocr_module.write_capture_ocr_report = original_write_report  # type: ignore[method-assign]
        double_page_capture_module.publish_latest = original_publish_latest  # type: ignore[method-assign]

    assert recorded_commands == [
        [
            "/usr/bin/python3",
            str(tmp_path / "hardware" / "capture_double_page.py"),
            "--output-root",
            str((tmp_path / "captures").resolve()),
            "--no-denoise",
            "--skip-enhance",
        ]
    ]
    assert [request.playback_sides for request in submitted_requests] == [("left",), ("right",)]
    assert all(request.scan_id == session_dir.name for request in submitted_requests)
    assert submitted_requests[0].report_path == session_dir / "ocr_text" / "left_report.json"
    assert submitted_requests[1].report_path == session_dir / "ocr_text" / "report.json"
    assert combined_reports == [session_dir / "ocr_text" / "report.json"]
    assert published_latest == [session_dir]


def test_runtime_controller_enqueues_page_ingest_after_capture_completion(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    statuses: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()

    latest_metadata_path = tmp_path / "captures" / "latest" / "metadata.json"
    latest_metadata_path.parent.mkdir(parents=True)
    session_dir = tmp_path / "captures" / "scan_test_002"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    latest_metadata_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (stable_dir / "report.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Hallo Welt.", "bbox": [[0, 10], [100, 10], [100, 40], [0, 40]]},
                            {"text": "8", "bbox": [[0, 900], [20, 900], [20, 920], [0, 920]]},
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    page_ingest_service = build_page_ingest_service(
        library_root=tmp_path / "library",
        status_callback=statuses.append,
    )
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        capture_ocr_config=CaptureOCRJobConfig(
            project_root=tmp_path,
            capture_output_root=Path("captures"),
        ),
        capture_ocr_enabled=True,
        page_ingest_service=page_ingest_service,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOK77",
        ),
    )

    controller._handle_job_event(
        runtime_module.ForegroundJobEvent(
            event_type=ForegroundJobEventType.COMPLETED,
            job_id="job_0001",
            job_type=runtime_module.ForegroundJobType.CAPTURE_OCR,
            label="Capture/OCR",
            monotonic_time=time.monotonic(),
            message="Capture/OCR abgeschlossen.",
        )
    )

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if any("page-ingest abgeschlossen" in status for status in statuses):
            break
        time.sleep(0.01)

    page_ingest_service.shutdown()
    manager.shutdown()

    assert any("page-ingest eingeplant" in status for status in statuses)
    assert any("page-ingest abgeschlossen" in status for status in statuses)


def test_page_ingest_service_cleans_remaining_artifacts_after_success(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    statuses: list[str] = []
    session_dir = tmp_path / "captures" / "scan_test_004"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    latest_dir = tmp_path / "captures" / "latest"
    latest_dir.mkdir(parents=True)
    latest_metadata_path = latest_dir / "metadata.json"
    latest_metadata_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    capture_metadata_path = session_dir / "metadata.json"
    capture_metadata_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path = stable_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [{"text": "8", "bbox": [[0, 900], [20, 900], [20, 920], [0, 920]]}],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    ocr_output_dir = tmp_path / "runs" / "latest_rapidocr"
    ocr_output_dir.mkdir(parents=True)

    page_ingest_service = build_page_ingest_service(
        library_root=tmp_path / "library",
        capture_ocr_config=CaptureOCRJobConfig(
            project_root=tmp_path,
            capture_output_root=Path("captures"),
            ocr_output_dir=Path("runs/latest_rapidocr"),
            artifact_cleanup=ArtifactCleanupConfig(
                mode="production",
                stage="after-ocr",
            ),
        ),
        status_callback=statuses.append,
    )
    try:
        page_ingest_service.submit(
            runtime_module.PageIngestRequest(
                tag_id="BOOK88",
                report_path=report_path,
                scan_id=session_dir.name,
                session_dir=session_dir,
                capture_metadata_path=capture_metadata_path,
                created_at="2026-07-02T15:45:00Z",
            )
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any("artefakte bereinigt" in status for status in statuses):
                break
            time.sleep(0.01)
    finally:
        page_ingest_service.shutdown()

    assert any("page-ingest abgeschlossen" in status for status in statuses)
    assert any("artefakte bereinigt" in status for status in statuses)
    assert session_dir.exists() is False
    assert latest_dir.exists() is False
    assert ocr_output_dir.exists() is False
    assert (tmp_path / "library" / "BOOK88" / "pages" / "0008.json").exists()


def test_runtime_controller_delete_book_confirmation_and_execution(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            delete_book_message_name="buch_loeschen",
            delete_success_message_name="buch_geloescht",
        ),
        nfc_tag_reader=_StaticNFCTagReader("BOOKDEL"),
    )

    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("BOOKDEL")
    (store.book_dir("BOOKDEL") / "state" / "flag.json").write_text("{}", encoding="utf-8")

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(ABRAction(ABRActionType.DELETE_BOOK_REQUEST, _button_down_action("chapter_summary").source_event))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)

        assert controller.work_state == WorkState.DELETE_BOOK_CONFIRMATION
        assert played_messages == ["buch_loeschen"]

        controller.handle_action(_button_down_action("encoder_button"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(played_messages) < 2:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert store.book_dir("BOOKDEL").exists() is False
    assert any("Buch-Loeschen angefordert fuer Buch BOOKDEL" in status for status in statuses)
    assert any("Buchdaten geloescht: BOOKDEL" in status for status in statuses)
    assert played_messages == ["buch_loeschen", "buch_geloescht"]


def test_runtime_controller_delete_book_confirmation_can_be_cancelled(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    statuses: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            delete_book_message_name="buch_loeschen",
            delete_cancel_message_name="abbruch",
        ),
        nfc_tag_reader=_StaticNFCTagReader("BOOKDEL"),
    )

    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("BOOKDEL")

    played_messages: list[str] = []
    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(ABRAction(ABRActionType.DELETE_BOOK_REQUEST, _button_down_action("chapter_summary").source_event))
        controller.handle_action(_button_down_action("start_stop_nfc", monotonic_time=2.0))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(played_messages) < 2:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert store.book_dir("BOOKDEL").exists()
    assert any("Buch-Loeschen abgebrochen" in status for status in statuses)
    assert played_messages == ["buch_loeschen", "abbruch"]


def test_runtime_controller_uses_nfc_tag_for_page_ingest(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    statuses: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    nfc_reader = _StaticNFCTagReader("BOOKNFC01")
    page_audio_player = _FakePageAudioPlayer()

    latest_metadata_path = tmp_path / "captures" / "latest" / "metadata.json"
    latest_metadata_path.parent.mkdir(parents=True)
    session_dir = tmp_path / "captures" / "scan_test_nfc"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    latest_metadata_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:45:00Z",
                "session_dir": str(session_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (stable_dir / "report.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Hallo Welt.", "bbox": [[0, 10], [100, 10], [100, 40], [0, 40]]},
                            {"text": "8", "bbox": [[0, 900], [20, 900], [20, 920], [0, 920]]},
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    page_ingest_service = build_page_ingest_service(
        library_root=tmp_path / "library",
        status_callback=statuses.append,
    )
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        capture_ocr_config=CaptureOCRJobConfig(
            project_root=tmp_path,
            capture_output_root=Path("captures"),
        ),
        capture_ocr_enabled=False,
        page_ingest_service=page_ingest_service,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
        ),
        page_audio_player=page_audio_player,
        nfc_tag_reader=nfc_reader,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = lambda message_name, config=None, **kwargs: Path("ok.wav")
    try:
        controller.handle_action(_start_stop_action())
        controller._handle_job_event(
            runtime_module.ForegroundJobEvent(
                event_type=ForegroundJobEventType.COMPLETED,
                job_id="job_0001",
                job_type=runtime_module.ForegroundJobType.CAPTURE_OCR,
                label="Capture/OCR",
                monotonic_time=time.monotonic(),
                message="Capture/OCR abgeschlossen.",
            )
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any("page-ingest abgeschlossen" in status for status in statuses):
                break
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        page_ingest_service.shutdown()
        controller.stop()
        manager.shutdown()

    assert nfc_reader.read_calls == 1
    assert (tmp_path / "library" / "BOOKNFC01" / "pages" / "0008.json").exists()
    assert page_audio_player.enqueued == [["Hallo Welt."]]


def test_runtime_controller_can_abort_active_page_audio(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    page_audio_player.active = True
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            cancel_work_message_name="abbruch",
        ),
        page_audio_player=page_audio_player,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert page_audio_player.cancel_calls == 1
    assert played_messages == ["abbruch"]
    assert any("laufende Seitenausgabe wird abgebrochen" in status for status in statuses)


def test_runtime_controller_chapter_summary_button_enqueues_latest_summary_audio(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager(latest_text="Der letzte Abschnitt in Kurzform.")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library", fallback_tag_id="BOOKSUM"),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("chapter_summary"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            controller.process_job_events()
            if page_audio_player.enqueued_texts:
                break
            time.sleep(0.01)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert summary_manager.latest_calls == ["BOOKSUM"]
    assert page_audio_player.enqueued_texts == [
        ("kapitel-zusammenfassung:10-11", "Der letzte Abschnitt in Kurzform.")
    ]
    assert any("Kapitelzusammenfassung Quelle: chapter_0001_summary.json." in status for status in statuses)
    assert any("Kapitelzusammenfassung bereit" in status for status in statuses)


def test_runtime_controller_chapter_summary_includes_pending_open_section_text(tmp_path: Path) -> None:
    statuses: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager()
    chapter_assembler = _FakeChapterAssembler(
        pending_text="Neue Handlung seit dem letzten abgeschlossenen Abschnitt."
    )
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKPENDING",
        ),
        page_audio_player=page_audio_player,
        chapter_assembler=chapter_assembler,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = lambda *args, **kwargs: Path("ok.wav")
    try:
        controller.handle_action(_button_down_action("chapter_summary"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            controller.process_job_events()
            if page_audio_player.enqueued_texts:
                break
            time.sleep(0.01)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert summary_manager.latest_calls == []
    assert summary_manager.progress_calls == [
        (
            "BOOKPENDING",
            "Neue Handlung seit dem letzten abgeschlossenen Abschnitt.",
            ("page_0012",),
            (12,),
        )
    ]
    assert page_audio_player.enqueued_texts == [
        (
            "kapitel-zusammenfassung-temporaer:10-12",
            "Temporäre Zusammenfassung mit offenem Text.",
        )
    ]
    assert any("offenem Text erzeugt" in status for status in statuses)
    assert any("wird nicht gespeichert" in status for status in statuses)


def test_chapter_summary_runner_uses_pending_text_before_first_completed_section() -> None:
    statuses: list[str] = []
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager()
    summary_manager.completed_chapters = False
    chapter_assembler = _FakeChapterAssembler(pending_text="Die ersten offenen Seiten.")
    runner = runtime_module._build_chapter_summary_runner(
        tag_id="BOOKSTART",
        chapter_assembler=chapter_assembler,
        summary_manager=summary_manager,
        page_audio_player=page_audio_player,
    )

    runner(runtime_module.Event(), statuses.append)

    assert summary_manager.progress_calls == [
        ("BOOKSTART", "Die ersten offenen Seiten.", ("page_0012",), (12,))
    ]
    assert page_audio_player.enqueued_texts == [
        (
            "kapitel-zusammenfassung-temporaer",
            "Temporäre Zusammenfassung mit offenem Text.",
        )
    ]
    assert any("noch keinen abgeschlossenen Abschnitt" in status for status in statuses)


def test_runtime_controller_book_summary_button_enqueues_book_summary_audio(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager(book_text="Die Geschichte bisher.")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library", fallback_tag_id="BOOKSUM"),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("book_summary"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            controller.process_job_events()
            if page_audio_player.enqueued_texts:
                break
            time.sleep(0.01)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert summary_manager.book_calls == ["BOOKSUM"]
    assert page_audio_player.enqueued_texts == [("was-bisher-geschah", "Die Geschichte bisher.")]
    assert any("Buchzusammenfassung bereit" in status for status in statuses)


def test_runtime_controller_chapter_summary_button_plays_intro_and_repeats_bing_until_audio_ready(tmp_path: Path) -> None:
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager(latest_text="Der letzte Abschnitt in Kurzform.")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKSUM",
            chapter_summary_message_name="kapitel_zusammenfassen",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
        ),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("chapter_summary"))
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            controller.process_job_events()
            if len(played_messages) >= 3 and page_audio_player.enqueued_texts:
                break
            time.sleep(0.01)
        assert page_audio_player.audio_ready_callback is not None
        pre_ready_count = len(played_messages)
        page_audio_player.audio_ready_callback("kapitel-zusammenfassung:10-11")
        time.sleep(0.12)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert page_audio_player.enqueued_texts == [
        ("kapitel-zusammenfassung:10-11", "Der letzte Abschnitt in Kurzform.")
    ]
    assert played_messages[0:2] == ["kapitel_zusammenfassen", "bing"]
    assert played_messages.count("bing") == 1
    assert len(played_messages) == pre_ready_count


def test_runtime_controller_book_summary_button_plays_intro_and_repeats_bing_until_audio_ready(tmp_path: Path) -> None:
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager(book_text="Die Geschichte bisher.")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKSUM",
            book_summary_message_name="buch_zusammenfassen",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
        ),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("book_summary"))
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            controller.process_job_events()
            if len(played_messages) >= 3 and page_audio_player.enqueued_texts:
                break
            time.sleep(0.01)
        assert page_audio_player.audio_ready_callback is not None
        pre_ready_count = len(played_messages)
        page_audio_player.audio_ready_callback("was-bisher-geschah")
        time.sleep(0.12)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert page_audio_player.enqueued_texts == [("was-bisher-geschah", "Die Geschichte bisher.")]
    assert played_messages[0:2] == ["buch_zusammenfassen", "bing"]
    assert played_messages.count("bing") == 1
    assert len(played_messages) == pre_ready_count


def test_runtime_controller_chapter_summary_button_plays_missing_summary_warning(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager()
    summary_manager.completed_chapters = False
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKSUM",
            chapter_summary_message_name="kapitel_zusammenfassen",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
            missing_summary_message_name="keine_zusammenfassung",
        ),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("chapter_summary"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            controller.process_job_events()
            if played_messages:
                break
            time.sleep(0.01)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert summary_manager.latest_calls == []
    assert page_audio_player.enqueued_texts == []
    assert played_messages[0:2] == ["kapitel_zusammenfassen", "bing"]
    assert played_messages[-1] == "keine_zusammenfassung"
    assert any("noch kein abgeschlossener Abschnitt verfuegbar" in status for status in statuses)


def test_runtime_controller_book_summary_button_plays_missing_summary_warning(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    summary_manager = _FakeSummaryManager()
    summary_manager.completed_chapters = False
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id="BOOKSUM",
            book_summary_message_name="buch_zusammenfassen",
            start_ack_message_name="bing",
            start_wait_heartbeat_message_name="bing",
            start_wait_heartbeat_interval_s=0.05,
            missing_summary_message_name="keine_zusammenfassung",
        ),
        page_audio_player=page_audio_player,
        summary_manager=summary_manager,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_button_down_action("book_summary"))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            controller.process_job_events()
            if played_messages:
                break
            time.sleep(0.01)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        controller.stop()
        runtime_module.play_system_message = original
        manager.shutdown()

    assert summary_manager.book_calls == []
    assert page_audio_player.enqueued_texts == []
    assert played_messages[0:2] == ["buch_zusammenfassen", "bing"]
    assert played_messages[-1] == "keine_zusammenfassung"
    assert any("noch kein abgeschlossener Abschnitt verfuegbar" in status for status in statuses)


def test_runtime_controller_creates_automatic_chapter_summaries_after_page_ingest(tmp_path: Path) -> None:
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    created_chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=tmp_path / "chapter.txt",
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=1,
    )
    chapter_assembler = _FakeChapterAssembler([created_chapter])
    summary_manager = _FakeSummaryManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_audio_player=page_audio_player,
        chapter_assembler=chapter_assembler,
        summary_manager=summary_manager,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    try:
        controller._handle_page_ingest_result(
            runtime_module.PageIngestRequest(
                tag_id="BOOKAUTO",
                report_path=tmp_path / "report.json",
            ),
            runtime_module.PageIngestResult(
                tag_id="BOOKAUTO",
                scan_record=None,  # type: ignore[arg-type]
                pages=(
                    runtime_module.PageRecord(
                        page_id="page_0001",
                        scan_id="scan_1",
                        created_at="2026-07-04T12:00:00Z",
                        side="left",
                        clean_text="Seite eins.",
                        speak_text="Seite eins.",
                        page_number=1,
                    ),
                ),
                scan_manifest_path=tmp_path / "scan.json",
                saved_page_paths=(),
            ),
        )
    finally:
        controller.stop()
        manager.shutdown()

    assert chapter_assembler.calls == ["BOOKAUTO"]
    assert summary_manager.auto_calls == [("BOOKAUTO", "chapter_0001")]


def test_runtime_controller_stop_cancels_audio_and_background_capture_job(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    page_audio_player.active = True
    cancel_calls: list[str] = []
    manager.is_busy = lambda: True  # type: ignore[method-assign]
    manager.cancel_current_job = lambda: cancel_calls.append("cancelled") or True  # type: ignore[method-assign]
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            cancel_work_message_name="abbruch",
        ),
        page_audio_player=page_audio_player,
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert page_audio_player.cancel_calls == 1
    assert cancel_calls
    assert controller.work_state == WorkState.CANCELLING_WORK
    assert played_messages == ["abbruch"]
    assert any("laufender foreground job wird abgebrochen" in status for status in statuses)


def test_runtime_controller_strips_left_tail_fragment_before_early_playback(tmp_path: Path) -> None:
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_audio_player=page_audio_player,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )

    try:
        controller._handle_page_ingest_result(
            runtime_module.PageIngestRequest(
                tag_id="BOOKTAIL",
                report_path=tmp_path / "left_report.json",
                playback_sides=("left",),
            ),
            runtime_module.PageIngestResult(
                tag_id="BOOKTAIL",
                scan_record=None,  # type: ignore[arg-type]
                pages=(
                    runtime_module.PageRecord(
                        page_id="page_0040",
                        scan_id="scan_tail",
                        created_at="2026-07-04T08:55:00Z",
                        side="left",
                        clean_text="Es wurde still.\nSie ging langsam",
                        speak_text="Es wurde still.\nSie ging langsam",
                        page_number=40,
                        tail_fragment="Sie ging langsam",
                    ),
                ),
                scan_manifest_path=tmp_path / "scan.json",
                saved_page_paths=(),
            ),
        )
    finally:
        controller.stop()
        manager.shutdown()

    assert page_audio_player.enqueued == [["Es wurde still."]]


def test_runtime_controller_strips_left_incomplete_suffix_before_early_playback_even_without_tail_fragment(
    tmp_path: Path,
) -> None:
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    page_audio_player = _FakePageAudioPlayer()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_audio_player=page_audio_player,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )

    try:
        controller._handle_page_ingest_result(
            runtime_module.PageIngestRequest(
                tag_id="BOOKTAIL",
                report_path=tmp_path / "left_report.json",
                playback_sides=("left",),
            ),
            runtime_module.PageIngestResult(
                tag_id="BOOKTAIL",
                scan_record=None,  # type: ignore[arg-type]
                pages=(
                    runtime_module.PageRecord(
                        page_id="page_0040",
                        scan_id="scan_tail",
                        created_at="2026-07-04T08:55:00Z",
                        side="left",
                        clean_text="Es wurde still.\nSie ging langsam",
                        speak_text="Es wurde still.\nSie ging langsam",
                        page_number=40,
                        tail_fragment=None,
                    ),
                ),
                scan_manifest_path=tmp_path / "scan.json",
                saved_page_paths=(),
            ),
        )
    finally:
        controller.stop()
        manager.shutdown()

    assert page_audio_player.enqueued == [["Es wurde still."]]


def test_runtime_controller_warns_for_repeated_pages_and_allows_confirmed_retry(tmp_path: Path) -> None:
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=ForegroundJobManager(),
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    warnings: list[str] = []
    controller._play_page_sequence_warning = warnings.append  # type: ignore[method-assign]

    def pages(scan_id: str) -> tuple[runtime_module.PageRecord, ...]:
        return (
            runtime_module.PageRecord(
                page_id=f"{scan_id}_left",
                scan_id=scan_id,
                created_at="2026-07-30T12:00:00Z",
                side="left",
                clean_text="Links.",
                speak_text="Links.",
                page_number=290,
            ),
            runtime_module.PageRecord(
                page_id=f"{scan_id}_right",
                scan_id=scan_id,
                created_at="2026-07-30T12:00:00Z",
                side="right",
                clean_text="Rechts.",
                speak_text="Rechts.",
                page_number=291,
            ),
        )

    try:
        assert controller._allow_page_sequence_playback("BOOK", pages("scan_1")) is True
        assert controller._allow_page_sequence_playback("BOOK", pages("scan_2")) is False
        assert warnings == ["repeat_page.wav"]
        assert controller._allow_page_sequence_playback("BOOK", pages("scan_2")) is False
        assert controller._allow_page_sequence_playback("BOOK", pages("scan_3")) is True
        assert "BOOK" not in controller._repeat_page_confirmation_books
        assert controller._allow_page_sequence_playback("BOOK", pages("scan_4")) is False
    finally:
        controller.stop()
        controller.job_manager.shutdown()


def test_runtime_controller_warns_for_backward_pages_then_guarantees_retry_playback(tmp_path: Path) -> None:
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=ForegroundJobManager(),
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    warnings: list[str] = []
    controller._play_page_sequence_warning = warnings.append  # type: ignore[method-assign]

    def page(scan_id: str, number: int) -> runtime_module.PageRecord:
        return runtime_module.PageRecord(
            page_id=f"{scan_id}_{number}",
            scan_id=scan_id,
            created_at="2026-07-30T12:00:00Z",
            side="left",
            clean_text="Text.",
            speak_text="Text.",
            page_number=number,
        )

    try:
        assert controller._allow_page_sequence_playback(
            "BOOK", (page("scan_1", 290), page("scan_1", 291))
        ) is True
        assert controller._allow_page_sequence_playback(
            "BOOK", (page("scan_2", 288), page("scan_2", 289))
        ) is False
        assert warnings == ["wrong_direction.wav"]

        # The confirmed retry must play even if it overlaps the previous spread.
        assert controller._allow_page_sequence_playback(
            "BOOK", (page("scan_3", 289), page("scan_3", 290))
        ) is True
        assert controller._last_played_page_numbers_by_book["BOOK"] == {289, 290}
        assert "BOOK" not in controller._wrong_direction_confirmation_books
    finally:
        controller.stop()
        controller.job_manager.shutdown()


def test_page_sequence_warning_cancels_active_capture_before_playback(tmp_path: Path) -> None:
    manager = ForegroundJobManager()
    cancel_calls: list[str] = []
    manager.cancel_current_job = lambda: cancel_calls.append("cancel") or True  # type: ignore[method-assign]
    statuses: list[str] = []
    played_messages: list[str] = []
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    controller._play_system_message = (  # type: ignore[method-assign]
        lambda message_name: played_messages.append(message_name) or True
    )

    try:
        controller._play_page_sequence_warning("repeat_page.wav")
    finally:
        controller.stop()
        manager.shutdown()

    assert cancel_calls[0] == "cancel"
    assert played_messages == ["repeat_page.wav"]
    assert any("vor der rechten Seite abgebrochen" in status for status in statuses)
    assert any("Seitenfolge-Hinweis abgeschlossen" in status for status in statuses)


def test_runtime_controller_accumulates_incremental_left_and_right_pages_per_scan(tmp_path: Path) -> None:
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=ForegroundJobManager(),
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    left = runtime_module.PageRecord(
        page_id="page_0290",
        scan_id="scan_1",
        created_at="2026-07-30T12:00:00Z",
        side="left",
        clean_text="Links.",
        speak_text="Links.",
        page_number=290,
    )
    right = runtime_module.PageRecord(
        page_id="page_0291",
        scan_id="scan_1",
        created_at="2026-07-30T12:00:00Z",
        side="right",
        clean_text="Rechts.",
        speak_text="Rechts.",
        page_number=291,
    )

    try:
        assert controller._allow_page_sequence_playback("BOOK", (left,)) is True
        assert controller._allow_page_sequence_playback("BOOK", (right,)) is True
        assert controller._last_played_page_numbers_by_book["BOOK"] == {290, 291}
    finally:
        controller.stop()
        controller.job_manager.shutdown()


def test_runtime_controller_applies_volume_delta_via_volume_controller(tmp_path: Path) -> None:
    statuses: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    volume_controller = _FakeVolumeController()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
        volume_controller=volume_controller,
    )

    try:
        assert monitor.encoder_step_callback is not None
        monitor.encoder_step_callback(1)
        controller.handle_action(
            ABRAction(
                action_type=ABRActionType.VOLUME_DELTA,
                source_event=FrontPanelEncoderEvent(
                    event_type=FrontPanelEventType.ENCODER_STEP,
                    control="volume",
                    label="Lautstaerke",
                    monotonic_time=1.0,
                    delta=1,
                    position=1,
                ),
                value=1,
            )
        )
    finally:
        controller.stop()
        manager.shutdown()

    assert volume_controller.initialized is True
    assert volume_controller.requested_deltas == [1]
    assert volume_controller.apply_requested_calls == 1
    assert volume_controller.applied_deltas == []
    assert any("Lautstaerke initialisiert: Stufe 9/10 (91%, Software-Regelung)." in status for status in statuses)
    assert any("Lautstaerke gesetzt: Stufe 10/10 (100%)." in status for status in statuses)


def test_synchronous_system_message_observes_encoder_volume_callback_during_playback(
    tmp_path: Path,
) -> None:
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    volume_controller = _FakeVolumeController()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
        volume_controller=volume_controller,
    )
    observed: list[int] = []

    def _fake_play_system_message(
        message_name,
        *,
        config,
        volume_percent,
        volume_provider,
    ):
        del message_name, config
        observed.append(volume_percent)
        assert volume_provider() == 91
        assert monitor.encoder_step_callback is not None
        monitor.encoder_step_callback(-1)
        observed.append(volume_provider())
        return Path("bing.wav")

    original = runtime_module.play_system_message
    runtime_module.play_system_message = _fake_play_system_message
    try:
        assert controller._play_system_message("bing") is True
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert observed == [91, 82]
    assert volume_controller.apply_requested_calls == 0


def test_page_audio_player_prefetches_right_page_during_left_playback(tmp_path: Path) -> None:
    statuses: list[str] = []
    player = runtime_module.PageAudioPlayer(status_callback=statuses.append)
    playback_started = runtime_module.Event()
    left_playback_finished = runtime_module.Event()
    synth_order: list[str] = []
    play_order: list[str] = []

    def _fake_synthesize_page_audio(text: str, page_label: str) -> Path:
        synth_order.append(page_label)
        output_path = tmp_path / f"{page_label.replace(':', '_')}.wav"
        output_path.write_text(text, encoding="utf-8")
        if page_label == "right:2":
            assert playback_started.wait(timeout=1.0)
            assert left_playback_finished.is_set() is False
        return output_path

    def _fake_play_audio_file(audio_path: Path, page_label: str, generation: int) -> None:
        del audio_path, generation
        play_order.append(page_label)
        if page_label == "left:1":
            playback_started.set()
            time.sleep(0.05)
            left_playback_finished.set()

    player._synthesize_page_audio = _fake_synthesize_page_audio  # type: ignore[method-assign]
    player._play_audio_file = _fake_play_audio_file  # type: ignore[method-assign]
    try:
        player.enqueue_pages(
            (
                runtime_module.PageRecord(
                    page_id="page_0001",
                    scan_id="scan_1",
                    created_at="2026-07-03T11:00:00Z",
                    side="left",
                    clean_text="Links",
                    speak_text="Links",
                    page_number=1,
                ),
                runtime_module.PageRecord(
                    page_id="page_0002",
                    scan_id="scan_1",
                    created_at="2026-07-03T11:00:00Z",
                    side="right",
                    clean_text="Rechts",
                    speak_text="Rechts",
                    page_number=2,
                ),
            )
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and player.is_active():
            time.sleep(0.01)
    finally:
        player.shutdown()

    assert synth_order == ["left:1", "right:2"]
    assert play_order == ["left:1", "right:2"]


def test_page_audio_player_prefetches_later_enqueued_page_during_current_playback(tmp_path: Path) -> None:
    player = runtime_module.PageAudioPlayer()
    playback_started = runtime_module.Event()
    left_playback_finished = runtime_module.Event()
    right_prefetched = runtime_module.Event()
    synth_order: list[str] = []
    play_order: list[str] = []

    def _fake_synthesize_page_audio(text: str, page_label: str) -> Path:
        synth_order.append(page_label)
        output_path = tmp_path / f"{page_label.replace(':', '_')}.wav"
        output_path.write_text(text, encoding="utf-8")
        if page_label == "right:2":
            assert playback_started.wait(timeout=1.0)
            assert left_playback_finished.is_set() is False
            right_prefetched.set()
        return output_path

    def _fake_play_audio_file(audio_path: Path, page_label: str, generation: int) -> None:
        del audio_path, generation
        play_order.append(page_label)
        if page_label == "left:1":
            playback_started.set()
            assert right_prefetched.wait(timeout=1.0)
            left_playback_finished.set()

    player._synthesize_page_audio = _fake_synthesize_page_audio  # type: ignore[method-assign]
    player._play_audio_file = _fake_play_audio_file  # type: ignore[method-assign]
    try:
        player.enqueue_pages(
            (
                runtime_module.PageRecord(
                    page_id="page_0001",
                    scan_id="scan_1",
                    created_at="2026-07-03T11:00:00Z",
                    side="left",
                    clean_text="Links",
                    speak_text="Links",
                    page_number=1,
                ),
            )
        )
        assert playback_started.wait(timeout=1.0)
        player.enqueue_pages(
            (
                runtime_module.PageRecord(
                    page_id="page_0002",
                    scan_id="scan_1",
                    created_at="2026-07-03T11:00:00Z",
                    side="right",
                    clean_text="Rechts",
                    speak_text="Rechts",
                    page_number=2,
                ),
            )
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and player.is_active():
            time.sleep(0.01)
    finally:
        player.shutdown()

    assert synth_order == ["left:1", "right:2"]
    assert play_order == ["left:1", "right:2"]


def test_prepare_page_tts_input_uses_longer_ssml_break_after_chapter_announcement() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Kapitel vier.\n\nDer Anfang des Kapitels.",
        backend_name="google",
    )

    assert input_type == "ssml"
    assert rendered_text == (
        "<speak>Kapitel vier.<break time=\"1350ms\"/>Der Anfang des Kapitels.</speak>"
    )


def test_prepare_page_tts_input_uses_english_chapter_announcement() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Chapter forty-two.\n\nA new beginning.",
        backend_name="google",
        chapter_label="Chapter",
    )

    assert input_type == "ssml"
    assert rendered_text == (
        "<speak>Chapter forty-two.<break time=\"1350ms\"/>A new beginning.</speak>"
    )


def test_page_audio_player_rejects_page_from_different_language() -> None:
    player = runtime_module.PageAudioPlayer(
        runtime_module.PageSpeechConfig(language_code="en", chapter_label="Chapter")
    )
    try:
        page = runtime_module.PageRecord(
            page_id="page_0001",
            scan_id="scan_1",
            created_at="2026-08-07T12:00:00Z",
            side="left",
            clean_text="Deutscher Text.",
            speak_text="Deutscher Text.",
            page_number=1,
            metadata={"language": "de"},
        )
        with pytest.raises(RuntimeError, match="aktive TTS-Sprache ist en"):
            player.enqueue_pages((page,))
        with pytest.raises(RuntimeError, match="aktive TTS-Sprache ist en"):
            player.enqueue_text("summary", "Deutsche Zusammenfassung.", language_code="de")
    finally:
        player.shutdown()


def test_enhanced_renderer_emphasizes_english_chapter_announcement() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Chapter twenty-one.\n\nThe story continues.",
        backend_name="google-standard-enhanced",
        chapter_label="Chapter",
    )

    assert (
        '<s><emphasis level="moderate">Chapter twenty-one.</emphasis></s>'
        '<break time="1350ms"/>'
    ) in rendered_text


def test_prepare_page_tts_input_keeps_ssml_for_google_neural2() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Kapitel vier.\n\nDer Anfang des Kapitels.",
        backend_name="google-neural2",
    )

    assert input_type == "ssml"
    assert '<break time="1350ms"/>' in rendered_text


def test_prepare_page_tts_input_enhances_standard_h_without_changing_words() -> None:
    text = (
        "Kapitel vier.\n\n"
        "Ein neuer Morgen\n\n"
        "Der erste Satz. Der zweite Satz!\n\n"
        "„Kommst du mit?“\n"
        "fragte Anna."
    )

    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        text,
        backend_name="google-standard-enhanced",
    )

    assert input_type == "ssml"
    assert '<break time="1350ms"/>' in rendered_text
    assert '<break time="700ms"/>' in rendered_text
    assert (
        '<p><s>Der erste Satz.</s><break time="900ms"/>'
        '<s>Der zweite Satz!</s><break time="2000ms"/></p>'
    ) in rendered_text
    assert (
        '<p><s>„Kommst du mit?“ fragte Anna.</s><break time="2000ms"/></p>'
        in rendered_text
    )


def test_prepare_page_tts_input_keeps_legacy_google_renderer_unchanged() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Eine Überschrift\n\nDer erste Satz. Der zweite Satz.",
        backend_name="google",
    )

    assert input_type == "ssml"
    assert rendered_text == (
        "<speak>Eine Überschrift\n\nDer erste Satz. Der zweite Satz.</speak>"
    )


def test_enhanced_standard_h_raises_last_word_of_question() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Kommst du morgen?",
        backend_name="google-standard-enhanced",
    )

    assert input_type == "ssml"
    assert rendered_text == (
        '<speak><p><s>Kommst du <prosody pitch="+3st">'
        'morgen</prosody>?</s><break time="2000ms"/></p></speak>'
    )


def test_enhanced_standard_h_raises_short_question_word_completely() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Kommst du mit?",
        backend_name="google-standard-enhanced",
    )

    assert '<prosody pitch="+3st">mit</prosody>?' in rendered_text


def test_enhanced_standard_h_adds_explicit_pause_between_paragraphs() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Der erste Absatz.\n\nDer zweite Absatz.",
        backend_name="google-standard-enhanced",
    )

    assert rendered_text == (
        '<speak><p><s>Der erste Absatz.</s><break time="2000ms"/></p>'
        '<p><s>Der zweite Absatz.</s><break time="2000ms"/></p></speak>'
    )
    assert rendered_text.count('<break time="2000ms"/>') == 2


def test_enhanced_standard_h_uses_chapter_pause_after_heading() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Erlebnis In Der Knabenzeit\n\nDer Schlosser Mohr ging nach Hause.",
        backend_name="google-standard-enhanced",
    )

    assert rendered_text == (
        '<speak><s><emphasis level="moderate">Erlebnis In Der Knabenzeit</emphasis></s>'
        '<break time="1350ms"/>'
        '<p><s>Der Schlosser Mohr ging nach Hause.</s><break time="2000ms"/></p></speak>'
    )


def test_enhanced_standard_h_detects_paragraph_after_sentence_ending_at_line_break() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "»Da ist noch frei.«\n"
        "Gérard stellt seinen Geigenkasten ab. Seine Hand\n"
        "ruht auf dem Leder.\n"
        "»Ist etwas passiert?«\n"
        "Die Frage überrumpelt Sasha.",
        backend_name="google-standard-enhanced",
    )

    assert rendered_text.count('<break time="900ms"/>') == 3
    assert rendered_text.count('<break time="2000ms"/>') == 2
    assert (
        '<s>Gérard stellt seinen Geigenkasten ab.</s><break time="900ms"/>'
        '<s>Seine Hand ruht auf dem Leder.</s><break time="2000ms"/></p>'
    ) in rendered_text


def test_enhanced_standard_h_uses_only_sentence_pause_after_guillemet_dialogue() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "»Wer ist das?«\n"
        "»Gehört die Frau zu uns?«\n"
        "»Still, man kann euch hören.«\n"
        "Die Kinder schwiegen.",
        backend_name="google-standard-enhanced",
    )

    assert rendered_text.count('<break time="900ms"/>') == 3
    assert rendered_text.count('<break time="2000ms"/>') == 1
    assert '<s>»Still, man kann euch hören.«</s><break time="900ms"/>' in rendered_text
    assert '<s>Die Kinder schwiegen.</s><break time="2000ms"/>' in rendered_text


def test_enhanced_standard_h_uses_only_sentence_pause_after_straight_quoted_dialogue() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        '\"Wer ist das?\"\n\"Ich weiß es nicht.\"\nDanach gingen sie weiter.',
        backend_name="google-standard-enhanced",
    )

    assert rendered_text.count('<break time="900ms"/>') == 2
    assert rendered_text.count('<break time="2000ms"/>') == 1


def test_enhanced_standard_h_uses_sentence_and_paragraph_breaks_without_adding_them() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Satz eins. Satz zwei? Satz drei!\n\nNaechster Absatz.",
        backend_name="google-standard-enhanced",
    )

    assert rendered_text == (
        '<speak><p><s>Satz eins.</s><break time="900ms"/>'
        '<s>Satz <prosody pitch="+3st">zwei</prosody>?</s><break time="900ms"/>'
        '<s>Satz drei!</s><break time="2000ms"/></p>'
        '<p><s>Naechster Absatz.</s><break time="2000ms"/></p></speak>'
    )


def test_legacy_google_does_not_add_question_pitch() -> None:
    rendered_text, _ = runtime_module._prepare_page_tts_input(
        "Kommst du morgen?",
        backend_name="google",
    )

    assert "<prosody" not in rendered_text


def test_prepare_page_tts_input_uses_plain_text_for_google_gemini_flash() -> None:
    text = "Kapitel vier.\n\nDer Anfang des Kapitels."

    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        text,
        backend_name="google-gemini-flash",
    )

    assert input_type == "text"
    assert rendered_text == text


def test_long_summary_is_split_at_sentence_boundaries_for_google_tts() -> None:
    text = " ".join(
        f"Dies ist Zusammenfassungssatz Nummer {index}."
        for index in range(1, 181)
    )

    chunks = runtime_module._split_text_for_tts(
        text,
        backend_name="google-standard-enhanced",
    )

    assert len(chunks) > 1
    assert all(chunk.endswith(".") for chunk in chunks)
    assert all(
        runtime_module._rendered_tts_input_size(
            chunk,
            backend_name="google-standard-enhanced",
        )
        <= runtime_module._GOOGLE_TTS_CHUNK_MAX_INPUT_BYTES
        for chunk in chunks
    )
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split())


def test_short_summary_remains_one_tts_utterance() -> None:
    text = "Eine kurze und vollständige Zusammenfassung."

    assert runtime_module._split_text_for_tts(
        text,
        backend_name="google-standard-enhanced",
    ) == (text,)


def test_summary_chunk_limit_creates_smaller_complete_sentence_groups() -> None:
    text = " ".join(
        f"Zusammenfassungssatz {index} beschreibt einen weiteren Teil der Handlung."
        for index in range(1, 61)
    )

    chunks = runtime_module._split_text_for_tts(
        text,
        backend_name="google-standard-enhanced",
        max_input_bytes=runtime_module._SUMMARY_TTS_CHUNK_MAX_INPUT_BYTES,
    )

    assert len(chunks) > 1
    assert all(chunk.endswith(".") for chunk in chunks)
    assert all(
        runtime_module._rendered_tts_input_size(
            chunk,
            backend_name="google-standard-enhanced",
        )
        <= 900
        for chunk in chunks
    )


def test_prepare_page_tts_input_uses_longer_ssml_break_before_and_after_chapter_announcement() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Und dann kam der Sonntag.\n\nKapitel vier.\n\nDer Anfang des Kapitels.",
        backend_name="google",
    )

    assert input_type == "ssml"
    assert rendered_text == (
        "<speak>Und dann kam der Sonntag.<break time=\"1350ms\"/>"
        "Kapitel vier.<break time=\"1350ms\"/>Der Anfang des Kapitels.</speak>"
    )


def test_page_audio_player_sends_chapter_pause_as_ssml_for_google(tmp_path: Path) -> None:
    backend = _FakeSynthBackend()
    player = runtime_module.PageAudioPlayer(
        config=runtime_module.PageSpeechConfig(tts_backend="google"),
    )
    player._get_tts_backend = lambda: backend  # type: ignore[method-assign]
    try:
        audio_path = player._synthesize_page_audio(
            "Kapitel vier.\n\nDer Anfang des Kapitels.",
            "left:4",
        )
    finally:
        player.shutdown()

    assert backend.calls[0][1] == "ssml"
    assert '<break time="1350ms"/>' in backend.calls[0][0]
    audio_path.unlink(missing_ok=True)


def test_prepare_page_tts_input_keeps_plain_text_for_non_ssml_backend() -> None:
    rendered_text, input_type = runtime_module._prepare_page_tts_input(
        "Kapitel vier.\n\nDer Anfang des Kapitels.",
        backend_name="espeak",
    )

    assert input_type == "text"
    assert rendered_text == "Kapitel vier.\n\nDer Anfang des Kapitels."


def test_runtime_controller_aborts_start_when_nfc_tag_missing(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            missing_book_message_name="buch_nicht_erkannt",
        ),
        nfc_tag_reader=_StaticNFCTagReader(None),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert played_messages == ["buch_nicht_erkannt"]
    assert any("Kein NFC-Tag erkannt: Start wird abgebrochen" in status for status in statuses)


def test_runtime_controller_announces_new_book_and_creates_book_layout(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            new_book_message_name="neues_buch",
            start_ack_message_name="bing",
        ),
        nfc_tag_reader=_StaticNFCTagReader("NEWBOOK01"),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not played_messages:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    store = runtime_module.BookStore(tmp_path / "library")
    assert controller.work_state == WorkState.CAPTURE_OCR_RUNNING
    assert played_messages == ["neues_buch", "bing"]
    assert store.book_dir("NEWBOOK01").exists()
    assert (store.book_dir("NEWBOOK01") / "book.json").exists()
    assert any("Neues Buch erkannt: NEWBOOK01" in status for status in statuses)


def test_runtime_controller_does_not_announce_existing_book_on_start(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("BOOKKNOWN")
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            new_book_message_name="neues_buch",
            start_ack_message_name="bing",
        ),
        nfc_tag_reader=_StaticNFCTagReader("BOOKKNOWN"),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(_start_stop_action())
        time.sleep(0.05)
    finally:
        runtime_module.play_system_message = original
        controller.stop()
        manager.shutdown()

    assert controller.work_state == WorkState.CAPTURE_OCR_RUNNING
    assert played_messages == ["bing"]
    assert any("Start-Taste erkannt: Dummy Capture/OCR wird fuer Buch BOOKKNOWN gestartet." in status for status in statuses)
    assert not any("Neues Buch erkannt: BOOKKNOWN" in status for status in statuses)


def test_runtime_controller_delete_book_aborts_when_nfc_tag_missing(tmp_path: Path) -> None:
    statuses: list[str] = []
    played_messages: list[str] = []
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    manager = ForegroundJobManager()
    controller = RuntimeController(
        monitor=monitor,
        job_manager=manager,
        status_callback=statuses.append,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=tmp_path / "library",
            fallback_tag_id=None,
            delete_book_message_name="buch_loeschen",
            missing_book_message_name="buch_nicht_erkannt",
        ),
        nfc_tag_reader=_StaticNFCTagReader(None),
    )

    original = runtime_module.play_system_message
    runtime_module.play_system_message = (
        lambda message_name, config=None, **kwargs: played_messages.append(message_name) or Path("ok.wav")
    )
    try:
        controller.handle_action(ABRAction(ABRActionType.DELETE_BOOK_REQUEST, _button_down_action("chapter_summary").source_event))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(played_messages) < 1:
            time.sleep(0.01)
    finally:
        runtime_module.play_system_message = original
        manager.shutdown()

    assert controller.work_state == WorkState.IDLE
    assert played_messages == ["buch_nicht_erkannt"]
    assert any("Kein NFC-Tag erkannt: Buch-Loeschen wird abgebrochen" in status for status in statuses)


def test_capture_book_context_prefers_type_a_and_persists_type_v_association(tmp_path: Path) -> None:
    manager = ForegroundJobManager()
    scan = NFCTagScan(
        tags=(
            NFCTag("04A1B2C3", "ISO14443A", 1),
            NFCTag("E004010916F34897", "ISO15693", 2),
        )
    )
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=manager,
        capture_ocr_config=CaptureOCRJobConfig(project_root=tmp_path),
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
        nfc_tag_reader=_AsyncNFCTagReader(scan),
    )
    try:
        context = controller._resolve_capture_book_context(scan)
    finally:
        controller.stop()
        manager.shutdown()

    assert context == runtime_module.CaptureBookContext("04A1B2C3", "reader1")
    store = runtime_module.BookStore(tmp_path / "library")
    assert store.load_iso15693_tag_ids("04A1B2C3") == ["E004010916F34897"]


def test_capture_book_context_resolves_type_v_only_with_configured_fallback_orientation(tmp_path: Path) -> None:
    store = runtime_module.BookStore(tmp_path / "library")
    store.ensure_book("04A1B2C3")
    store.associate_iso15693_tag("04A1B2C3", "E004010916F34897")
    manager = ForegroundJobManager()
    scan = NFCTagScan(tags=(NFCTag("E004010916F34897", "ISO15693", 1),))
    controller = RuntimeController(
        monitor=FrontPanelMonitor(gpio=_FakeGPIO()),
        job_manager=manager,
        capture_ocr_config=CaptureOCRJobConfig(
            project_root=tmp_path,
            iso15693_only_orientation="reader1",
        ),
        page_ingest_config=PageIngestRuntimeConfig(library_root=tmp_path / "library"),
    )
    try:
        context = controller._resolve_capture_book_context(scan)
    finally:
        controller.stop()
        manager.shutdown()

    assert context == runtime_module.CaptureBookContext("04A1B2C3", "reader1")


def test_nfc_orientations_override_legacy_right_page_rotation() -> None:
    from abr.preprocessing.processor import PreprocessorConfig

    default = PreprocessorConfig()

    reader2 = runtime_module._preprocess_config_for_orientation(default, "reader2")
    reader1 = runtime_module._preprocess_config_for_orientation(default, "reader1")

    assert (reader2.left_page_rotate_deg, reader2.right_page_rotate_deg) == (0, 0)
    assert (reader1.left_page_rotate_deg, reader1.right_page_rotate_deg) == (0, 0)


def test_nfc_orientation_swaps_camera_pages_only_for_reader1(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    left = case_dir / "left.jpg"
    right = case_dir / "right.jpg"
    left.write_bytes(b"camera-left")
    right.write_bytes(b"camera-right")
    rotated_paths: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        "abr.hardware.double_page_rectify.apply_rotation_in_place",
        lambda path, degrees: rotated_paths.append((path, degrees)),
    )

    runtime_module._apply_capture_orientation(case_dir, "reader2")
    assert left.read_bytes() == b"camera-left"
    assert right.read_bytes() == b"camera-right"
    assert rotated_paths == [(right, 180)]

    runtime_module._apply_capture_orientation(case_dir, "reader1")
    assert left.read_bytes() == b"camera-right"
    assert right.read_bytes() == b"camera-left"
    assert rotated_paths == [(right, 180), (right, 180)]


def test_ocr_orientation_maps_upright_to_reader2_and_upside_down_to_reader1(tmp_path: Path, monkeypatch) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    decisions = iter((0, 180))
    applied: list[str] = []

    monkeypatch.setattr(
        runtime_module,
        "_detect_capture_orientation",
        lambda case_dir, *, language, preprocess_config: {
            "rotation_deg": next(decisions),
            "reason": language,
        },
    )
    monkeypatch.setattr(
        runtime_module,
        "_apply_capture_orientation",
        lambda case_dir, orientation: applied.append(orientation),
    )

    for _ in range(2):
        result = runtime_module._detect_capture_orientation(
            case_dir,
            language="de",
            preprocess_config=object(),
        )
        orientation = "reader1" if result["rotation_deg"] == 180 else "reader2"
        runtime_module._apply_capture_orientation(case_dir, orientation)

    assert applied == ["reader2", "reader1"]


def test_camera_assignment_log_data_follows_orientation_swap() -> None:
    metadata = {
        "slots": {
            "left": {"camera_index": 0},
            "right": {"camera_index": 1},
        }
    }

    assert runtime_module._camera_assignment_after_orientation(metadata, "reader2") == ("0", "1")
    assert runtime_module._camera_assignment_after_orientation(metadata, "reader1") == ("1", "0")
