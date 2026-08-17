import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from abr.hardware.double_page_capture import CaptureSlot, resolve_remap_path, run_capture_session
from abr.preprocessing.processor import PreprocessorConfig


def test_run_capture_session_creates_standard_layout(tmp_path: Path) -> None:
    captured_raw: list[Path] = []
    rectified_outputs: list[Path] = []
    enhanced_calls: list[tuple[Path, Path, Path]] = []

    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        captured_raw.append(raw_path)
        raw_path.write_bytes(f"raw-{slot.camera_index}".encode("ascii"))
        return ["fake-capture", str(slot.camera_index), str(raw_path)]

    def fake_rectify(slot: CaptureSlot, raw_path: Path, rectified_path: Path) -> list[str]:
        rectified_outputs.append(rectified_path)
        rectified_path.write_bytes(raw_path.read_bytes() + b"-rectified")
        return ["fake-rectify", str(slot.camera_index), str(rectified_path)]

    def fake_enhance(case_dir: Path, ocr_dir: Path, debug_dir: Path) -> object:
        enhanced_calls.append((case_dir, ocr_dir, debug_dir))
        ocr_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "page_1").mkdir(parents=True)
        (debug_dir / "page_2").mkdir(parents=True)
        (ocr_dir / "left.png").write_bytes(b"left-ocr")
        (ocr_dir / "right.png").write_bytes(b"right-ocr")
        (debug_dir / "page_1" / "02_enhanced.png").write_bytes(b"left-enhanced")
        (debug_dir / "page_2" / "02_enhanced.png").write_bytes(b"right-enhanced")
        return SimpleNamespace(
            manifest_path=ocr_dir / "manifest.json",
            config=PreprocessorConfig(denoise_enabled=False),
            timings={"total_sec": 1.5, "page_processing_sec": 1.2},
            pages=[
                SimpleNamespace(
                    page_id="page_1",
                    source_path=case_dir / "left.jpg",
                    ocr_output_path=ocr_dir / "left.png",
                    debug_paths={"02_enhanced": debug_dir / "page_1" / "02_enhanced.png"},
                    timings={"page_total_sec": 0.6},
                ),
                SimpleNamespace(
                    page_id="page_2",
                    source_path=case_dir / "right.jpg",
                    ocr_output_path=ocr_dir / "right.png",
                    debug_paths={"02_enhanced": debug_dir / "page_2" / "02_enhanced.png"},
                    timings={"page_total_sec": 0.6},
                ),
            ],
        )

    slots = [
        CaptureSlot(slot_name="left", camera_index=0, remap_path=tmp_path / "cam0_planar.npz"),
        CaptureSlot(slot_name="right", camera_index=1, remap_path=tmp_path / "cam1_planar.npz"),
    ]

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_test_001",
        slots=slots,
        width=2304,
        height=1296,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        capture_func=fake_capture,
        rectify_func=fake_rectify,
        enhance_func=fake_enhance,
    )

    assert result.session_dir == tmp_path / "captures" / "scan_test_001"
    assert result.case_dir == result.session_dir / "case"
    assert result.ocr_dir == result.session_dir / "ocr"
    assert captured_raw == [
        result.session_dir / "raw" / "cam0_raw.jpg",
        result.session_dir / "raw" / "cam1_raw.jpg",
    ]
    assert rectified_outputs == [
        result.session_dir / "rectified" / "cam0_rectified.jpg",
        result.session_dir / "rectified" / "cam1_rectified.jpg",
    ]
    assert enhanced_calls == [(result.case_dir, result.ocr_dir, result.session_dir / "debug")]
    assert (result.case_dir / "left.jpg").read_bytes() == b"raw-0-rectified"
    assert (result.case_dir / "right.jpg").read_bytes() == b"raw-1-rectified"
    assert (result.ocr_dir / "left.png").read_bytes() == b"left-ocr"
    assert (tmp_path / "captures" / "latest" / "case" / "left.jpg").read_bytes() == b"raw-0-rectified"
    assert (tmp_path / "captures" / "latest" / "ocr" / "right.png").read_bytes() == b"right-ocr"
    assert (tmp_path / "captures" / "latest" / "debug" / "page_1" / "02_enhanced.png").read_bytes() == b"left-enhanced"

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["session_name"] == "scan_test_001"
    assert metadata["ocr_dir"].endswith("/ocr")
    assert metadata["debug_dir"].endswith("/debug")
    assert metadata["slots"]["left"]["camera_index"] == 0
    assert metadata["slots"]["right"]["camera_index"] == 1
    assert metadata["slots"]["left"]["case_path"].endswith("/case/left.jpg")
    assert metadata["slots"]["right"]["rectify_command"][0] == "fake-rectify"
    assert "timings" in metadata
    assert "capture_total_sec" in metadata["timings"]
    assert "enhancement_total_sec" in metadata["timings"]
    assert "slot_total_sec" in metadata["slots"]["left"]["timings"]
    assert "capture_sec" in metadata["slots"]["right"]["timings"]
    assert metadata["enhancement"]["timings"]["total_sec"] == 1.5
    assert metadata["enhancement"]["config"]["denoise_enabled"] is False
    assert metadata["enhancement"]["pages"][0]["timings"]["page_total_sec"] == 0.6


def test_run_capture_session_rejects_existing_session_dir(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "scan_test_002"
    session_dir.mkdir(parents=True)

    try:
        run_capture_session(
            output_root=tmp_path / "captures",
            session_name="scan_test_002",
            slots=[CaptureSlot(slot_name="left", camera_index=0, remap_path=tmp_path / "cam0_planar.npz")],
            width=None,
            height=None,
            timeout_ms=1000,
            jpeg_quality=90,
            shutter_us=None,
            gain=None,
            still_command="fake-still",
            python_executable="/fake/python",
            capture_func=lambda _slot, _path: [],
            rectify_func=lambda _slot, _raw, _rectified: [],
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("Expected FileExistsError for existing session directory")


def test_resolve_remap_path_uses_camera_index_by_default() -> None:
    resolved = resolve_remap_path(None, 1)
    assert resolved.name == "cam1_planar.npz"


def test_run_capture_session_supports_raw_only_and_publishes_latest(tmp_path: Path) -> None:
    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        raw_path.write_bytes(f"raw-{slot.camera_index}".encode("ascii"))
        return ["fake-capture", str(slot.camera_index), str(raw_path)]

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_raw_only",
        slots=[
            CaptureSlot(slot_name="left", camera_index=0, remap_path=tmp_path / "cam0_planar.npz"),
            CaptureSlot(slot_name="right", camera_index=1, remap_path=tmp_path / "cam1_planar.npz"),
        ],
        width=None,
        height=None,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        raw_only=True,
        capture_func=fake_capture,
    )

    assert result.case_dir is None
    assert result.ocr_dir is None
    assert (result.session_dir / "raw" / "cam0_raw.jpg").read_bytes() == b"raw-0"
    assert not (result.session_dir / "rectified").exists()
    assert (tmp_path / "captures" / "latest" / "raw" / "cam1_raw.jpg").read_bytes() == b"raw-1"

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["case_dir"] is None
    assert metadata["ocr_dir"] is None
    assert metadata["capture"]["raw_only"] is True
    assert metadata["slots"]["left"]["rectified_path"] is None
    assert metadata["enhancement"] is None
    assert "capture_sec" in metadata["slots"]["left"]["timings"]
    assert "session_total_sec" in metadata["timings"]


def test_run_capture_session_supports_skip_enhance_and_still_publishes_debug_dir(tmp_path: Path) -> None:
    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        raw_path.write_bytes(f"raw-{slot.camera_index}".encode("ascii"))
        return ["fake-capture", str(slot.camera_index), str(raw_path)]

    def fake_rectify(slot: CaptureSlot, raw_path: Path, rectified_path: Path) -> list[str]:
        rectified_path.write_bytes(raw_path.read_bytes() + b"-rectified")
        return ["fake-rectify", slot.slot_name, str(raw_path), str(rectified_path)]

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_skip_enhance",
        slots=[
            CaptureSlot(slot_name="left", camera_index=0, remap_path=tmp_path / "cam0_planar.npz"),
            CaptureSlot(slot_name="right", camera_index=1, remap_path=tmp_path / "cam1_planar.npz"),
        ],
        width=None,
        height=None,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        enhance_after_capture=False,
        capture_func=fake_capture,
        rectify_func=fake_rectify,
    )

    assert (result.session_dir / "debug").is_dir()
    assert (tmp_path / "captures" / "latest" / "debug").is_dir()

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["enhancement"] is None
    assert metadata["debug_dir"].endswith("/debug")


def test_capture_size_defaults_to_remap_resolution(tmp_path: Path) -> None:
    remap_path = tmp_path / "cam0_planar.npz"
    np.savez(remap_path, image_width=np.int32(4656), image_height=np.int32(3496))

    captured_commands: list[list[str]] = []

    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        from abr.hardware.double_page_capture import _build_capture_runner

        runner = _build_capture_runner(
            still_command="fake-still",
            width=None,
            height=None,
            timeout_ms=1200,
            jpeg_quality=95,
            shutter_us=None,
            gain=None,
        )
        import subprocess

        original_run = subprocess.run

        def fake_run(command, check):
            captured_commands.append(command)
            raw_path.write_bytes(b"raw")
            return None

        subprocess.run = fake_run
        try:
            return runner(slot, raw_path)
        finally:
            subprocess.run = original_run

    run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_resolution",
        slots=[CaptureSlot(slot_name="left", camera_index=0, remap_path=remap_path)],
        width=None,
        height=None,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        raw_only=True,
        capture_func=fake_capture,
    )

    assert captured_commands == [
        [
            "fake-still",
            "--camera",
            "0",
            "--nopreview",
            "--timeout",
            "1200",
            "--quality",
            "95",
            "--output",
            str(tmp_path / "captures" / "scan_resolution" / "raw" / "cam0_raw.jpg"),
            "--width",
            "4656",
            "--height",
            "3496",
        ]
    ]


def test_capture_runner_includes_manual_shutter_when_configured(tmp_path: Path) -> None:
    remap_path = tmp_path / "cam0_planar.npz"
    np.savez(remap_path, image_width=np.int32(2304), image_height=np.int32(1296))

    captured_commands: list[list[str]] = []

    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        from abr.hardware.double_page_capture import _build_capture_runner

        runner = _build_capture_runner(
            still_command="fake-still",
            width=None,
            height=None,
            timeout_ms=1200,
            jpeg_quality=95,
            shutter_us=8000,
            gain=None,
        )
        import subprocess

        original_run = subprocess.run

        def fake_run(command, check):
            captured_commands.append(command)
            raw_path.write_bytes(b"raw")
            return None

        subprocess.run = fake_run
        try:
            return runner(slot, raw_path)
        finally:
            subprocess.run = original_run

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_manual_shutter",
        slots=[CaptureSlot(slot_name="left", camera_index=0, remap_path=remap_path)],
        width=None,
        height=None,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=8000,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        raw_only=True,
        capture_func=fake_capture,
    )

    assert captured_commands == [
        [
            "fake-still",
            "--camera",
            "0",
            "--nopreview",
            "--timeout",
            "1200",
            "--quality",
            "95",
            "--output",
            str(tmp_path / "captures" / "scan_manual_shutter" / "raw" / "cam0_raw.jpg"),
            "--shutter",
            "8000",
            "--width",
            "2304",
            "--height",
            "1296",
        ]
    ]

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["capture"]["shutter_us"] == 8000
    assert "capture_total_sec" in metadata["timings"]


def test_capture_runner_includes_manual_gain_when_configured(tmp_path: Path) -> None:
    remap_path = tmp_path / "cam0_planar.npz"
    np.savez(remap_path, image_width=np.int32(2304), image_height=np.int32(1296))

    captured_commands: list[list[str]] = []

    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        from abr.hardware.double_page_capture import _build_capture_runner

        runner = _build_capture_runner(
            still_command="fake-still",
            width=None,
            height=None,
            timeout_ms=1200,
            jpeg_quality=95,
            shutter_us=None,
            gain=1.5,
        )
        import subprocess

        original_run = subprocess.run

        def fake_run(command, check):
            captured_commands.append(command)
            raw_path.write_bytes(b"raw")
            return None

        subprocess.run = fake_run
        try:
            return runner(slot, raw_path)
        finally:
            subprocess.run = original_run

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_manual_gain",
        slots=[CaptureSlot(slot_name="left", camera_index=0, remap_path=remap_path)],
        width=None,
        height=None,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=1.5,
        still_command="fake-still",
        python_executable="/fake/python",
        raw_only=True,
        capture_func=fake_capture,
    )

    assert captured_commands == [
        [
            "fake-still",
            "--camera",
            "0",
            "--nopreview",
            "--timeout",
            "1200",
            "--quality",
            "95",
            "--output",
            str(tmp_path / "captures" / "scan_manual_gain" / "raw" / "cam0_raw.jpg"),
            "--gain",
            "1.5",
            "--width",
            "2304",
            "--height",
            "1296",
        ]
    ]

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["capture"]["gain"] == 1.5
    assert "capture_total_sec" in metadata["timings"]


def test_run_capture_session_records_rotation_metadata(tmp_path: Path) -> None:
    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        raw_path.write_bytes(f"raw-{slot.camera_index}".encode("ascii"))
        return ["fake-capture", str(slot.camera_index), str(raw_path)]

    def fake_rectify(slot: CaptureSlot, raw_path: Path, rectified_path: Path) -> list[str]:
        image = np.zeros((2, 3, 3), dtype=np.uint8)
        image[0, 0] = (255, 0, 0)
        ok = cv2.imwrite(str(rectified_path), image)
        assert ok
        return ["fake-rectify", str(slot.camera_index), str(rectified_path)]

    result = run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_rotated",
        slots=[
            CaptureSlot(slot_name="left", camera_index=0, remap_path=tmp_path / "cam0_planar.npz", rotate_deg=0),
            CaptureSlot(slot_name="right", camera_index=1, remap_path=tmp_path / "cam1_planar.npz", rotate_deg=180),
        ],
        width=2304,
        height=1296,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        capture_func=fake_capture,
        rectify_func=fake_rectify,
    )

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["slots"]["left"]["rotate_deg"] == 0
    assert metadata["slots"]["right"]["rotate_deg"] == 180


def test_run_capture_session_switches_led_per_slot_during_capture(tmp_path: Path) -> None:
    led_events: list[tuple[str, bool]] = []
    capture_events: list[str] = []

    class FakeLEDController:
        def set_channel(self, channel: str, is_on: bool) -> None:
            led_events.append((channel, is_on))

    def fake_capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        capture_events.append(slot.slot_name)
        raw_path.write_bytes(f"raw-{slot.slot_name}".encode("ascii"))
        return ["fake-capture", slot.slot_name, str(raw_path)]

    def fake_rectify(slot: CaptureSlot, raw_path: Path, rectified_path: Path) -> list[str]:
        rectified_path.write_bytes(raw_path.read_bytes() + b"-rectified")
        return ["fake-rectify", slot.slot_name, str(rectified_path)]

    def fake_enhance(case_dir: Path, ocr_dir: Path, debug_dir: Path) -> object:
        ocr_dir.mkdir(parents=True, exist_ok=True)
        (ocr_dir / "left.png").write_bytes(b"left-ocr")
        (ocr_dir / "right.png").write_bytes(b"right-ocr")
        (debug_dir / "page_1").mkdir(parents=True)
        (debug_dir / "page_2").mkdir(parents=True)
        (debug_dir / "page_1" / "02_enhanced.png").write_bytes(b"left-enhanced")
        (debug_dir / "page_2" / "02_enhanced.png").write_bytes(b"right-enhanced")
        return object()

    run_capture_session(
        output_root=tmp_path / "captures",
        session_name="scan_leds",
        slots=[
            CaptureSlot("left", 0, tmp_path / "cam0_planar.npz", led_channel="left"),
            CaptureSlot("right", 1, tmp_path / "cam1_planar.npz", led_channel="right"),
        ],
        width=2304,
        height=1296,
        timeout_ms=1200,
        jpeg_quality=95,
        shutter_us=None,
        gain=None,
        still_command="fake-still",
        python_executable="/fake/python",
        capture_func=fake_capture,
        rectify_func=fake_rectify,
        led_controller=FakeLEDController(),
        enhance_func=fake_enhance,
    )

    assert capture_events == ["left", "right"]
    assert led_events == [
        ("left", True),
        ("left", False),
        ("right", True),
        ("right", False),
    ]
