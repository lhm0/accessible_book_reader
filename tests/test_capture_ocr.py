import json
from pathlib import Path

import cv2
import numpy as np

from abr.capture_ocr import detect_page_orientation_from_text_lines, run_capture_ocr
from abr.models import OCRLine


def _write_test_image(path: Path) -> None:
    image = np.full((24, 32, 3), 180, dtype=np.uint8)
    ok = cv2.imwrite(str(path), image)
    assert ok


def test_textline_orientation_uses_three_lines_and_rotates_on_confident_vote() -> None:
    image = np.full((600, 900, 3), 255, dtype=np.uint8)
    for y in (120, 260, 400):
        cv2.putText(image, "Eine ausreichend lange Textzeile", (80, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)

    class FakeBackend:
        def classify_text_orientation(self, images, language: str = "de"):
            assert language == "de"
            assert len(images) == 3
            return [("180", 0.98), ("180", 0.96), ("0", 0.81)]

    result = detect_page_orientation_from_text_lines(image, FakeBackend())

    assert result["rotation_deg"] == 180
    assert len(result["line_boxes"]) == 3
    assert "votes=0:0.810,180:1.940" in result["reason"]


def test_textline_orientation_falls_back_to_zero_without_reliable_lines() -> None:
    image = np.full((200, 300, 3), 255, dtype=np.uint8)

    class FakeBackend:
        def classify_text_orientation(self, images, language: str = "de"):
            del language
            assert images == []
            return []

    result = detect_page_orientation_from_text_lines(image, FakeBackend())

    assert result["rotation_deg"] == 0


def test_run_capture_ocr_writes_left_before_processing_right(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "out"
    calls: list[str] = []

    class FakeBackend:
        def recognize(self, _image, language: str = "de") -> list[OCRLine]:
            calls.append(language)
            if len(calls) == 2:
                left_path = output_dir / "left.txt"
                assert left_path.exists()
                assert left_path.read_text(encoding="utf-8") == "Links eins\nLinks zwei\n"
            if len(calls) == 1:
                return [
                    OCRLine(text="Links eins", confidence=0.9, bbox=((0, 0), (1, 0), (1, 1), (0, 1))),
                    OCRLine(text="Links zwei", confidence=0.8, bbox=((0, 2), (1, 2), (1, 3), (0, 3))),
                ]
            return [
                OCRLine(text="Rechts", confidence=0.7, bbox=((0, 0), (1, 0), (1, 1), (0, 1))),
            ]

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())

    result = run_capture_ocr(ocr_dir=ocr_dir, output_dir=output_dir, write_overlay=False, orientation_mode="off")

    assert calls == ["de", "de"]
    assert (output_dir / "left.txt").read_text(encoding="utf-8") == "Links eins\nLinks zwei\n"
    assert (output_dir / "right.txt").read_text(encoding="utf-8") == "Rechts\n"
    assert result.report_path == output_dir / "report.json"

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["pages"][0]["slot"] == "left"
    assert payload["pages"][1]["slot"] == "right"
    assert payload["pages"][0]["ocr_line_count"] == 2
    assert payload["pages"][1]["ocr_line_count"] == 1
    assert "input_load_sec" in payload["pipeline_timings"]
    assert payload["orientation_mode"] == "off"


def test_run_capture_ocr_writes_optional_overlay_images(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    class FakeBackend:
        def recognize(self, _image, language: str = "de") -> list[OCRLine]:
            return [
                OCRLine(text="Overlay", confidence=0.95, bbox=((0, 0), (5, 0), (5, 5), (0, 5))),
            ]

    class FakeVisualizer:
        def draw_ocr_overlay(self, image, lines):
            assert len(lines) == 1
            return image.copy()

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())
    monkeypatch.setattr("abr.capture_ocr.DebugVisualizer", FakeVisualizer)

    result = run_capture_ocr(ocr_dir=ocr_dir, output_dir=tmp_path / "out", write_overlay=True, orientation_mode="off")

    left_overlay = result.output_dir / "debug" / "page_1" / "06_ocr_overlay.png"
    right_overlay = result.output_dir / "debug" / "page_2" / "06_ocr_overlay.png"
    assert left_overlay.exists()
    assert right_overlay.exists()

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["pages"][0]["debug_paths"]["06_ocr_overlay"].endswith("/debug/page_1/06_ocr_overlay.png")
    assert payload["pages"][1]["debug_paths"]["06_ocr_overlay"].endswith("/debug/page_2/06_ocr_overlay.png")


def test_run_capture_ocr_passes_english_language_and_records_it(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")
    languages: list[str] = []

    class FakeBackend:
        def recognize(self, _image, language: str = "de") -> list[OCRLine]:
            languages.append(language)
            return [
                OCRLine(
                    text="English",
                    confidence=0.9,
                    bbox=((0, 0), (1, 0), (1, 1), (0, 1)),
                    metadata={"ocr_language": language},
                )
            ]

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())

    result = run_capture_ocr(
        ocr_dir=ocr_dir,
        output_dir=tmp_path / "out",
        orientation_mode="off",
        language="en",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert languages == ["en", "en"]
    assert payload["ocr_language"] == "en"
    assert payload["pages"][0]["ocr_lines"][0]["metadata"]["ocr_language"] == "en"


def test_run_capture_ocr_records_layout_heading_from_vertical_gap(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    class FakeBackend:
        def recognize(self, _image, language: str = "de") -> list[OCRLine]:
            del language
            return [
                OCRLine(
                    text="Der kleine Petter Spinnenmann",
                    confidence=0.99,
                    bbox=((978, 667), (2153, 654), (2153, 761), (978, 774)),
                    source_index=0,
                ),
                OCRLine(
                    text="Ich glaube, dass ich eine glueckliche Kindheit hatte.",
                    confidence=0.99,
                    bbox=((874, 949), (2271, 921), (2273, 1020), (875, 1048)),
                    source_index=1,
                ),
                OCRLine(
                    text="Meine Mutter glaubte das nicht.",
                    confidence=0.99,
                    bbox=((875, 1045), (2271, 1015), (2273, 1106), (877, 1136)),
                    source_index=2,
                ),
            ]

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())

    result = run_capture_ocr(
        ocr_dir=ocr_dir,
        output_dir=tmp_path / "out",
        orientation_mode="off",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["pages"][0]["layout_blocks"] == [
        {
            "kind": "chapter_heading",
            "text": "Der kleine Petter Spinnenmann",
            "line_indices": [0],
            "bbox": [[978, 654], [2153, 654], [2153, 774], [978, 774]],
        },
        {
            "kind": "paragraph",
            "text": (
                "Ich glaube, dass ich eine glueckliche Kindheit hatte. "
                "Meine Mutter glaubte das nicht."
            ),
            "line_indices": [1, 2],
            "bbox": [[874, 921], [2273, 921], [2273, 1136], [874, 1136]],
        },
    ]


def test_run_capture_ocr_requires_manifest_json(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")

    try:
        run_capture_ocr(ocr_dir=ocr_dir, output_dir=tmp_path / "out", orientation_mode="off")
    except FileNotFoundError as exc:
        assert "manifest.json" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing manifest.json")


def test_run_capture_ocr_simple_orientation_rotates_when_probe_ocr_scores_higher(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    calls: list[tuple[int, int]] = []

    class FakeBackend:
        def recognize(self, image, language: str = "de") -> list[OCRLine]:
            del language
            calls.append((image.shape[1], image.shape[0]))
            if len(calls) == 1:
                return []
            return [OCRLine(text="Gedreht erkannt", confidence=0.9, bbox=((0, 0), (2, 0), (2, 2), (0, 2)))]

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())

    result = run_capture_ocr(ocr_dir=ocr_dir, output_dir=tmp_path / "out", orientation_mode="simple")

    assert result.pages[0].rotation_deg == 180
    assert "ocr180=" in result.pages[0].orientation_reason
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["orientation_mode"] == "simple"
    assert payload["pages"][0]["rotation_deg"] == 180
    assert "orientation_probe_ocr_0_sec" in payload["pages"][0]["timings"]
    assert "epsilon=" in payload["pages"][0]["orientation_reason"]


def test_run_capture_ocr_simple_orientation_keeps_zero_when_scores_are_too_close(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    _write_test_image(ocr_dir / "left.png")
    _write_test_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    calls = {"count": 0}

    def _lines(text: str, confidence: float) -> list[OCRLine]:
        return [OCRLine(text=text, confidence=confidence, bbox=((0, 0), (4, 0), (4, 4), (0, 4)))]

    class FakeBackend:
        def recognize(self, image, language: str = "de") -> list[OCRLine]:
            del image, language
            calls["count"] += 1
            if calls["count"] == 1:
                return _lines("Normale Probe", 0.90)
            if calls["count"] == 2:
                return _lines("Gedrehte Probe", 0.91)
            return _lines("Final", 0.95)

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda name: FakeBackend())

    result = run_capture_ocr(ocr_dir=ocr_dir, output_dir=tmp_path / "out", orientation_mode="simple")

    assert result.pages[0].rotation_deg == 0
    assert "delta=" in result.pages[0].orientation_reason
