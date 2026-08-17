import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "hardware" / "camera_test_server.py"
SPEC = importlib.util.spec_from_file_location("camera_test_server_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CAMERA_TEST_SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMERA_TEST_SERVER)


def test_read_capture_review_state_detects_latest_case_images(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "latest"
    case_dir = session_dir / "case"
    case_dir.mkdir(parents=True)
    (case_dir / "left.jpg").write_bytes(b"left-image")
    (case_dir / "right.jpg").write_bytes(b"right-image")
    (session_dir / "metadata.json").write_text(
        json.dumps({"session_name": "scan_20260630_101500"}),
        encoding="utf-8",
    )

    state = CAMERA_TEST_SERVER.read_capture_review_state(session_dir)

    assert state["available"] is True
    assert state["session_name"] == "scan_20260630_101500"
    assert state["left_path"] == case_dir / "left.jpg"
    assert state["right_path"] == case_dir / "right.jpg"
    assert state["version"] > 0


def test_read_capture_review_state_handles_missing_images(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "latest"
    session_dir.mkdir(parents=True)

    state = CAMERA_TEST_SERVER.read_capture_review_state(session_dir)

    assert state["available"] is False
    assert state["session_name"] == "latest"
    assert state["version"] == 0


def test_read_raw_review_state_uses_slot_camera_mapping(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "latest"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "cam1_raw.jpg").write_bytes(b"left-raw")
    (raw_dir / "cam0_raw.jpg").write_bytes(b"right-raw")
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_name": "scan_20260630_111500",
                "slots": {
                    "left": {"camera_index": 1},
                    "right": {"camera_index": 0},
                },
            }
        ),
        encoding="utf-8",
    )

    state = CAMERA_TEST_SERVER.read_raw_review_state(session_dir)

    assert state["available"] is True
    assert state["session_name"] == "scan_20260630_111500"
    assert state["left_path"] == raw_dir / "cam1_raw.jpg"
    assert state["right_path"] == raw_dir / "cam0_raw.jpg"
    assert state["version"] > 0


def test_read_ocr_review_state_detects_latest_debug_images(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    page_1_dir = debug_dir / "page_1"
    page_2_dir = debug_dir / "page_2"
    page_1_dir.mkdir(parents=True)
    page_2_dir.mkdir(parents=True)
    (page_1_dir / "02_enhanced.png").write_bytes(b"left-enhanced")
    (page_2_dir / "02_enhanced.png").write_bytes(b"right-enhanced")

    state = CAMERA_TEST_SERVER.read_ocr_review_state(debug_dir, "enhanced")

    assert state["available"] is True
    assert state["run_name"] == "latest"
    assert state["stage"] == "enhanced"
    assert state["stage_file"] == "02_enhanced.png"
    assert state["left_path"] == page_1_dir / "02_enhanced.png"
    assert state["right_path"] == page_2_dir / "02_enhanced.png"
    assert state["version"] > 0


def test_read_ocr_review_state_handles_missing_images(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    debug_dir.mkdir(parents=True)

    state = CAMERA_TEST_SERVER.read_ocr_review_state(debug_dir, "enhanced")

    assert state["available"] is False
    assert state["run_name"] == "latest"
    assert state["version"] == 0


def test_read_ocr_review_state_rejects_unknown_stage(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    debug_dir.mkdir(parents=True)

    try:
        CAMERA_TEST_SERVER.read_ocr_review_state(debug_dir, "invalid")
    except ValueError as exc:
        assert "Unbekannte OCR-Stufe" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown OCR stage")


def test_read_ocr_words_review_state_detects_latest_word_overlays(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    page_1_dir = debug_dir / "page_1"
    page_2_dir = debug_dir / "page_2"
    page_1_dir.mkdir(parents=True)
    page_2_dir.mkdir(parents=True)
    (page_1_dir / "06_ocr_overlay.png").write_bytes(b"left-overlay")
    (page_2_dir / "06_ocr_overlay.png").write_bytes(b"right-overlay")

    state = CAMERA_TEST_SERVER.read_ocr_words_review_state(debug_dir)

    assert state["available"] is True
    assert state["run_name"] == "latest"
    assert state["stage_file"] == "06_ocr_overlay.png"
    assert state["left_path"] == page_1_dir / "06_ocr_overlay.png"
    assert state["right_path"] == page_2_dir / "06_ocr_overlay.png"
    assert state["version"] > 0


def test_read_ocr_words_review_state_handles_missing_images(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    debug_dir.mkdir(parents=True)

    state = CAMERA_TEST_SERVER.read_ocr_words_review_state(debug_dir)

    assert state["available"] is False
    assert state["run_name"] == "latest"
    assert state["version"] == 0


def test_read_ocr_words_review_state_falls_back_to_legacy_tesseract_overlay(tmp_path: Path) -> None:
    debug_dir = tmp_path / "runs" / "latest" / "debug"
    page_1_dir = debug_dir / "page_1"
    page_2_dir = debug_dir / "page_2"
    page_1_dir.mkdir(parents=True)
    page_2_dir.mkdir(parents=True)
    (page_1_dir / "06_tesseract_words.png").write_bytes(b"left-legacy")
    (page_2_dir / "06_tesseract_words.png").write_bytes(b"right-legacy")

    state = CAMERA_TEST_SERVER.read_ocr_words_review_state(debug_dir)

    assert state["available"] is True
    assert state["stage_file"] == "06_tesseract_words.png"
    assert state["left_path"] == page_1_dir / "06_tesseract_words.png"
    assert state["right_path"] == page_2_dir / "06_tesseract_words.png"


def test_read_review_state_collects_all_sources(tmp_path: Path) -> None:
    capture_session_dir = tmp_path / "captures" / "latest"
    raw_dir = capture_session_dir / "raw"
    case_dir = capture_session_dir / "case"
    capture_debug_dir = capture_session_dir / "debug"
    ocr_debug_dir = tmp_path / "runs" / "latest" / "debug"
    raw_dir.mkdir(parents=True)
    case_dir.mkdir(parents=True)
    (capture_debug_dir / "page_1").mkdir(parents=True)
    (capture_debug_dir / "page_2").mkdir(parents=True)
    (ocr_debug_dir / "page_1").mkdir(parents=True)
    (ocr_debug_dir / "page_2").mkdir(parents=True)

    (raw_dir / "cam0_raw.jpg").write_bytes(b"raw-left")
    (raw_dir / "cam1_raw.jpg").write_bytes(b"raw-right")
    (case_dir / "left.jpg").write_bytes(b"rectified-left")
    (case_dir / "right.jpg").write_bytes(b"rectified-right")
    (capture_debug_dir / "page_1" / "02_enhanced.png").write_bytes(b"enhanced-left")
    (capture_debug_dir / "page_2" / "02_enhanced.png").write_bytes(b"enhanced-right")
    (ocr_debug_dir / "page_1" / "06_ocr_overlay.png").write_bytes(b"ocr-left")
    (ocr_debug_dir / "page_2" / "06_ocr_overlay.png").write_bytes(b"ocr-right")
    (capture_session_dir / "metadata.json").write_text(
        json.dumps({"session_name": "scan_20260630_120000"}),
        encoding="utf-8",
    )

    state = CAMERA_TEST_SERVER.read_review_state(capture_session_dir, ocr_debug_dir)

    assert state["session_name"] == "scan_20260630_120000"
    assert state["run_name"] == "latest"
    assert set(state["sources"]) == {"raw", "rectified", "enhanced", "ocr-overlay"}
    assert state["sources"]["raw"]["available"] is True
    assert state["sources"]["rectified"]["left_path"] == case_dir / "left.jpg"
    assert state["sources"]["enhanced"]["right_path"] == capture_debug_dir / "page_2" / "02_enhanced.png"
    assert state["sources"]["ocr-overlay"]["left_path"] == ocr_debug_dir / "page_1" / "06_ocr_overlay.png"


def test_serialize_review_state_exposes_paths_and_missing_files(tmp_path: Path) -> None:
    capture_session_dir = tmp_path / "captures" / "latest"
    raw_dir = capture_session_dir / "raw"
    case_dir = capture_session_dir / "case"
    capture_debug_dir = capture_session_dir / "debug"
    ocr_debug_dir = tmp_path / "runs" / "latest" / "debug"
    raw_dir.mkdir(parents=True)
    case_dir.mkdir(parents=True)
    (capture_debug_dir / "page_1").mkdir(parents=True)
    (capture_debug_dir / "page_2").mkdir(parents=True)
    (ocr_debug_dir / "page_1").mkdir(parents=True)
    (ocr_debug_dir / "page_2").mkdir(parents=True)

    (raw_dir / "cam0_raw.jpg").write_bytes(b"raw-left")
    (raw_dir / "cam1_raw.jpg").write_bytes(b"raw-right")
    (case_dir / "left.jpg").write_bytes(b"rectified-left")
    (case_dir / "right.jpg").write_bytes(b"rectified-right")
    (capture_debug_dir / "page_1" / "02_enhanced.png").write_bytes(b"enhanced-left")
    (capture_debug_dir / "page_2" / "02_enhanced.png").write_bytes(b"enhanced-right")
    (ocr_debug_dir / "page_1" / "06_ocr_overlay.png").write_bytes(b"ocr-left")

    review_state = CAMERA_TEST_SERVER.read_review_state(capture_session_dir, ocr_debug_dir)
    payload = CAMERA_TEST_SERVER.serialize_review_state(review_state, "ocr-overlay")

    overlay = payload["sources"]["ocr-overlay"]
    assert overlay["left_path"] == str(ocr_debug_dir / "page_1" / "06_ocr_overlay.png")
    assert overlay["right_path"] == str(ocr_debug_dir / "page_2" / "06_ocr_overlay.png")
    assert overlay["source_dir"] == str(ocr_debug_dir)
    assert overlay["missing_paths"] == [str(ocr_debug_dir / "page_2" / "06_ocr_overlay.png")]
