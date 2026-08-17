from pathlib import Path

import cv2
import numpy as np

import json

from abr.preprocessing.enhance_for_ocr import enhance_case_dir, enhance_image_paths, preprocess_image_with_timings
from abr.preprocessing.processor import PreprocessorConfig


def test_enhance_image_paths_writes_expected_stage_files(tmp_path: Path) -> None:
    left_path = tmp_path / "left.jpg"
    right_path = tmp_path / "right.jpg"
    image = np.full((40, 60, 3), 180, dtype=np.uint8)
    cv2.imwrite(str(left_path), image)
    cv2.imwrite(str(right_path), image)

    result = enhance_image_paths(
        [left_path, right_path],
        debug_dir=tmp_path / "debug",
        ocr_dir=tmp_path / "ocr",
    )

    assert result.debug_dir == (tmp_path / "debug").resolve()
    assert result.ocr_dir == (tmp_path / "ocr").resolve()
    assert len(result.pages) == 2
    assert (result.debug_dir / "page_1" / "01_gray.png").exists()
    assert (result.debug_dir / "page_1" / "02_enhanced.png").exists()
    assert (result.debug_dir / "page_1" / "03_sharpened.png").exists()
    assert (result.debug_dir / "page_1" / "04_binary.png").exists()
    assert (result.debug_dir / "page_2" / "02_enhanced.png").exists()
    assert (result.ocr_dir / "left.png").exists()
    assert (result.ocr_dir / "right.png").exists()
    assert result.manifest_path == result.ocr_dir / "manifest.json"
    assert result.manifest_path.exists()
    assert result.config.denoise_enabled is True
    assert result.pages[0].ocr_output_path == result.ocr_dir / "left.png"
    assert result.pages[1].ocr_output_path == result.ocr_dir / "right.png"
    assert "total_sec" in result.timings
    assert "manifest_write_sec" in result.timings
    assert "page_total_sec" in result.pages[0].timings
    assert "ocr_write_sec" in result.pages[1].timings

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["denoise_enabled"] is True
    assert "timings" in manifest
    assert "page_processing_sec" in manifest["timings"]
    assert "timings" in manifest["pages"][0]
    assert "preprocess_image_total_sec" in manifest["pages"][0]["timings"]


def test_enhance_case_dir_reads_left_right_case_layout(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    image = np.full((32, 48, 3), 200, dtype=np.uint8)
    cv2.imwrite(str(case_dir / "left.jpg"), image)
    cv2.imwrite(str(case_dir / "right.jpg"), image)

    result = enhance_case_dir(
        case_dir,
        debug_dir=tmp_path / "debug",
        ocr_dir=tmp_path / "ocr",
    )

    assert [page.page_id for page in result.pages] == ["page_1", "page_2"]
    assert result.pages[0].source_path == (case_dir / "left.jpg").resolve()
    assert result.pages[1].source_path == (case_dir / "right.jpg").resolve()
    assert result.pages[0].ocr_output_path == (tmp_path / "ocr" / "left.png").resolve()
    assert result.pages[1].ocr_output_path == (tmp_path / "ocr" / "right.png").resolve()


def test_preprocess_image_with_timings_reports_stage_breakdown() -> None:
    image = np.full((24, 36, 3), 180, dtype=np.uint8)

    artifacts, timings = preprocess_image_with_timings(image, page_id="page_2", source_path=Path("right.jpg"))

    assert artifacts.ocr_input is not None
    assert "page_rotation_sec" in timings
    assert "gray_sec" in timings
    assert "denoise_sec" in timings
    assert "clahe_sec" in timings
    assert "binary_sec" in timings
    assert "preprocess_image_total_sec" in timings


def test_enhance_image_paths_records_disabled_denoise_in_manifest(tmp_path: Path) -> None:
    image_path = tmp_path / "left.jpg"
    image = np.full((40, 60, 3), 180, dtype=np.uint8)
    cv2.imwrite(str(image_path), image)

    result = enhance_image_paths(
        [image_path],
        debug_dir=tmp_path / "debug",
        ocr_dir=tmp_path / "ocr",
        config=PreprocessorConfig(denoise_enabled=False),
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.config.denoise_enabled is False
    assert manifest["denoise_enabled"] is False
