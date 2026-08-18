from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from abr.debug import DebugArtifactWriter
from abr.debug.visualization import DebugVisualizer
from abr.layout import BasicLayoutAnalyzer
from abr.models import ImageArray, OCRLine
from abr.ocr.factory import create_ocr_backend


PAGE_SLOT_NAMES = {
    "page_1": "left",
    "page_2": "right",
}
ORIENTATION_SCORE_EPSILON = 0.02
ORIENTATION_LINE_COUNT = 3
ORIENTATION_CLASSIFIER_MIN_CONFIDENCE = 0.55
ORIENTATION_VOTE_MARGIN = 0.35


@dataclass(slots=True)
class OCRPageResult:
    page_id: str
    slot: str
    source_path: Path
    text_path: Path
    rotation_deg: int
    orientation_reason: str
    text: str
    lines: list[OCRLine]
    debug_paths: dict[str, Path]
    timings: dict[str, float]


@dataclass(slots=True)
class OCRRunResult:
    ocr_dir: Path
    output_dir: Path
    report_path: Path
    pages: list[OCRPageResult]
    timings: dict[str, float]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Schlanker RapidOCR-Lauf auf vorbereiteten OCR-Bildern aus capture_double_page. "
            "Schreibt left.txt und right.txt sowie optional OCR-Overlay-Bilder."
        )
    )
    parser.add_argument(
        "--ocr-dir",
        type=Path,
        required=True,
        help="Vorbereiteter OCR-Ordner mit left.png, right.png und manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/latest_rapidocr"),
        help="Ausgabeverzeichnis fuer left.txt, right.txt und report.json",
    )
    parser.add_argument(
        "--language",
        choices=("de", "en"),
        default="de",
        help="OCR-Sprache: de oder en, Standard: de.",
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="OCR-Overlay-Bilder unter output-dir/debug/page_1|page_2/06_ocr_overlay.png schreiben",
    )
    parser.add_argument(
        "--orientation-mode",
        default="simple",
        choices=["off", "simple"],
        help="Orientierungserkennung: off = deaktiviert, simple = kleiner Textausschnitt mit 0/180-Vergleich",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_capture_ocr(
        ocr_dir=args.ocr_dir,
        output_dir=args.output_dir,
        write_overlay=args.overlay,
        orientation_mode=args.orientation_mode,
        language=args.language,
    )
    print(f"OCR-Dir: {result.ocr_dir}")
    print(f"Output:  {result.output_dir}")
    print(f"Report:  {result.report_path}")
    for page in result.pages:
        print(f"{page.slot}: {page.text_path}")
    return 0


def run_capture_ocr(
    *,
    ocr_dir: Path,
    output_dir: Path,
    write_overlay: bool = False,
    orientation_mode: str = "simple",
    language: str = "de",
) -> OCRRunResult:
    resolved_ocr_dir = _validate_ocr_dir(ocr_dir)
    return run_capture_ocr_pages(
        ocr_dir=resolved_ocr_dir,
        output_dir=output_dir,
        page_images=(
            ("page_1", resolved_ocr_dir / "left.png"),
            ("page_2", resolved_ocr_dir / "right.png"),
        ),
        write_overlay=write_overlay,
        orientation_mode=orientation_mode,
        language=language,
    )


def run_capture_ocr_pages(
    *,
    ocr_dir: Path,
    output_dir: Path,
    page_images: tuple[tuple[str, Path], ...] | list[tuple[str, Path]],
    write_overlay: bool = False,
    orientation_mode: str = "simple",
    language: str = "de",
    report_filename: str | None = "report.json",
) -> OCRRunResult:
    resolved_ocr_dir = ocr_dir.expanduser().resolve()
    resolved_output_dir = output_dir.expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    debug_writer = DebugArtifactWriter(resolved_output_dir / "debug" if write_overlay else None)
    visualizer = DebugVisualizer()
    ocr_backend = create_ocr_backend("rapidocr")

    started = time.monotonic()
    run_timings: dict[str, float] = {"input_load_sec": 0.0}
    pages: list[OCRPageResult] = []
    for index, (page_id, image_path) in enumerate(page_images, start=1):
        page_result = _run_capture_ocr_page(
            page_id=page_id,
            image_path=Path(image_path).expanduser().resolve(),
            index=index,
            output_dir=resolved_output_dir,
            debug_writer=debug_writer,
            visualizer=visualizer,
            ocr_backend=ocr_backend,
            write_overlay=write_overlay,
            orientation_mode=orientation_mode,
            language=language,
        )
        pages.append(page_result)
        run_timings["input_load_sec"] += page_result.timings.get("image_load_sec", 0.0)

    run_timings["page_processing_sec"] = sum(page.timings.get("page_total_sec", 0.0) for page in pages)
    run_timings["total_sec"] = time.monotonic() - started
    report_path = resolved_output_dir / report_filename if report_filename else None
    if report_path is not None:
        write_capture_ocr_report(
            report_path=report_path,
            ocr_dir=resolved_ocr_dir,
            pages=pages,
            timings=run_timings,
            orientation_mode=orientation_mode,
            language=language,
        )
    return OCRRunResult(
        ocr_dir=resolved_ocr_dir,
        output_dir=resolved_output_dir,
        report_path=report_path or resolved_output_dir / "report.json",
        pages=pages,
        timings=run_timings,
    )


def _validate_ocr_dir(ocr_dir: Path) -> Path:
    resolved = ocr_dir.expanduser().resolve()
    manifest_path = resolved / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"OCR-Ordner enthaelt kein manifest.json: {resolved}. "
            "Bitte capture_double_page oder enhance_for_ocr verwenden."
        )
    return resolved


def _resolve_ocr_images(ocr_dir: Path) -> list[Path]:
    left = ocr_dir / "left.png"
    right = ocr_dir / "right.png"
    missing = [path for path in (left, right) if not path.exists()]
    if missing:
        missing_paths = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"OCR-Bilder fehlen: {missing_paths}")
    return [left, right]


def _write_text_file(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        if text:
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_report(
    report_path: Path,
    ocr_dir: Path,
    pages: list[OCRPageResult],
    timings: dict[str, float],
    *,
    orientation_mode: str,
    language: str,
) -> None:
    payload = {
        "ocr_dir": str(ocr_dir),
        "orientation_mode": orientation_mode,
        "ocr_language": language,
        "pages": [
            {
                "page_id": page.page_id,
                "slot": page.slot,
                "source_path": str(page.source_path),
                "text_path": str(page.text_path),
                "rotation_deg": page.rotation_deg,
                "orientation_reason": page.orientation_reason,
                "ocr_line_count": len(page.lines),
                "avg_confidence": _avg_confidence(page.lines),
                "debug_paths": {stage: str(path) for stage, path in page.debug_paths.items()},
                "timings": page.timings,
                "layout_blocks": _serialize_layout_blocks(page.lines),
                "ocr_lines": [
                    {
                        "text": line.text,
                        "confidence": line.confidence,
                        "bbox": line.bbox,
                        "metadata": line.metadata,
                    }
                    for line in page.lines
                ],
            }
            for page in pages
        ],
        "pipeline_timings": timings,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _serialize_layout_blocks(lines: list[OCRLine]) -> list[dict[str, object]]:
    blocks, _page_number, _paragraphs = BasicLayoutAnalyzer().analyze(lines)
    return [
        {
            "kind": block.kind,
            "text": block.text,
            "line_indices": block.line_indices,
            "bbox": block.bbox,
        }
        for block in blocks
    ]


def write_capture_ocr_report(
    *,
    report_path: Path,
    ocr_dir: Path,
    pages: list[OCRPageResult],
    timings: dict[str, float],
    orientation_mode: str,
    language: str = "de",
) -> None:
    _write_report(
        report_path=report_path,
        ocr_dir=ocr_dir,
        pages=pages,
        timings=timings,
        orientation_mode=orientation_mode,
        language=language,
    )


def _run_capture_ocr_page(
    *,
    page_id: str,
    image_path: Path,
    index: int,
    output_dir: Path,
    debug_writer: DebugArtifactWriter,
    visualizer: DebugVisualizer,
    ocr_backend,
    write_overlay: bool,
    orientation_mode: str,
    language: str,
) -> OCRPageResult:
    page_started = time.monotonic()
    slot = PAGE_SLOT_NAMES.get(page_id, f"slot_{index}")
    timings: dict[str, float] = {}

    image_load_started = time.monotonic()
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    timings["image_load_sec"] = time.monotonic() - image_load_started
    if image is None:
        raise FileNotFoundError(f"Bild konnte nicht geladen werden: {image_path}")

    rotation_deg = 0
    orientation_reason = "orientation disabled"
    oriented_image = image
    if orientation_mode == "simple":
        orientation_started = time.monotonic()
        orientation_result = _detect_orientation_simple(image, ocr_backend, language=language)
        timings["orientation_sec"] = time.monotonic() - orientation_started
        timings.update(orientation_result["timings"])
        rotation_deg = int(orientation_result["rotation_deg"])
        orientation_reason = str(orientation_result["reason"])
        oriented_image = orientation_result["image"]
    else:
        timings["orientation_sec"] = 0.0
        timings["orientation_probe_search_sec"] = 0.0
        timings["orientation_probe_ocr_0_sec"] = 0.0
        timings["orientation_probe_ocr_180_sec"] = 0.0
        timings["orientation_probe_rotate_sec"] = 0.0
        timings["orientation_apply_rotation_sec"] = 0.0

    ocr_started = time.monotonic()
    lines = ocr_backend.recognize(oriented_image, language=language)
    timings["ocr_sec"] = time.monotonic() - ocr_started

    text_started = time.monotonic()
    text = "\n".join(line.text for line in lines)
    text_path = output_dir / f"{slot}.txt"
    _write_text_file(text_path, text)
    timings["text_write_sec"] = time.monotonic() - text_started

    debug_paths: dict[str, Path] = {}
    if write_overlay:
        overlay_started = time.monotonic()
        overlay = visualizer.draw_ocr_overlay(oriented_image, lines)
        timings["overlay_render_sec"] = time.monotonic() - overlay_started

        overlay_write_started = time.monotonic()
        path = debug_writer.write_image(page_id, "06_ocr_overlay", overlay)
        timings["overlay_write_sec"] = time.monotonic() - overlay_write_started
        if path is not None:
            debug_paths["06_ocr_overlay"] = path
    else:
        timings["overlay_render_sec"] = 0.0
        timings["overlay_write_sec"] = 0.0

    timings["page_total_sec"] = time.monotonic() - page_started
    return OCRPageResult(
        page_id=page_id,
        slot=slot,
        source_path=image_path,
        text_path=text_path,
        rotation_deg=rotation_deg,
        orientation_reason=orientation_reason,
        text=text,
        lines=lines,
        debug_paths=debug_paths,
        timings=timings,
    )


def _avg_confidence(lines: list[OCRLine]) -> float:
    return sum(line.confidence for line in lines) / max(1, len(lines))


def detect_page_orientation_from_text_lines(
    image: ImageArray,
    ocr_backend,
    *,
    language: str = "de",
) -> dict[str, object]:
    """Determine 0/180 page orientation from three inexpensive line crops."""
    started = time.monotonic()
    line_images, line_boxes = _select_orientation_line_images(image, count=ORIENTATION_LINE_COUNT)
    selection_sec = time.monotonic() - started

    classifier_started = time.monotonic()
    classifications = ocr_backend.classify_text_orientation(line_images, language=language)
    classifier_sec = time.monotonic() - classifier_started

    accepted = [
        (label, confidence)
        for label, confidence in classifications
        if confidence >= ORIENTATION_CLASSIFIER_MIN_CONFIDENCE
    ]
    if len(line_images) < ORIENTATION_LINE_COUNT:
        raise RuntimeError(
            "OCR-Orientierung nicht bestimmbar: "
            f"nur {len(line_images)} von {ORIENTATION_LINE_COUNT} Textzeilen gefunden."
        )
    if len(accepted) < 2:
        raise RuntimeError(
            "OCR-Orientierung nicht bestimmbar: "
            f"nur {len(accepted)} verlaessliche Klassifikationen erhalten."
        )
    vote_0 = sum(confidence for label, confidence in accepted if label == "0")
    vote_180 = sum(confidence for label, confidence in accepted if label == "180")
    if vote_180 > vote_0 + ORIENTATION_VOTE_MARGIN:
        rotation_deg = 180
    elif vote_0 > vote_180 + ORIENTATION_VOTE_MARGIN:
        rotation_deg = 0
    else:
        raise RuntimeError(
            "OCR-Orientierung nicht eindeutig: "
            f"votes=0:{vote_0:.3f},180:{vote_180:.3f}, "
            f"erforderlicher Vorsprung={ORIENTATION_VOTE_MARGIN:.3f}."
        )
    reason = (
        f"textline-classifier boxes={line_boxes}, results={classifications}, "
        f"accepted={len(accepted)}/{len(classifications)}, votes=0:{vote_0:.3f},"
        f"180:{vote_180:.3f}, margin={ORIENTATION_VOTE_MARGIN:.3f}"
    )
    return {
        "rotation_deg": rotation_deg,
        "reason": reason,
        "line_boxes": line_boxes,
        "classifications": classifications,
        "timings": {
            "orientation_line_selection_sec": selection_sec,
            "orientation_classifier_sec": classifier_sec,
            "orientation_sec": selection_sec + classifier_sec,
        },
    }


def _select_orientation_line_images(
    image: ImageArray,
    *,
    count: int = ORIENTATION_LINE_COUNT,
) -> tuple[list[ImageArray], list[tuple[int, int, int, int]]]:
    """Find likely long text rows using a cheap horizontal ink projection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    inverted = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    kernel_width = max(15, width // 80)
    joined = cv2.morphologyEx(
        inverted,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 3)),
    )
    contours = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.18 or h < max(8, height * 0.003) or h > height * 0.08:
            continue
        aspect = w / max(1, h)
        if aspect < 3.0:
            continue
        candidates.append((float(w * min(aspect, 20.0)), (x, y, w, h)))

    selected: list[tuple[int, int, int, int]] = []
    min_vertical_distance = max(12, height // 20)
    for _score, box in sorted(candidates, reverse=True):
        center_y = box[1] + box[3] // 2
        if any(abs(center_y - (other[1] + other[3] // 2)) < min_vertical_distance for other in selected):
            continue
        selected.append(box)
        if len(selected) == count:
            break
    selected.sort(key=lambda box: box[1])

    crops: list[ImageArray] = []
    padded_boxes: list[tuple[int, int, int, int]] = []
    for x, y, w, h in selected:
        pad_x = max(4, w // 50)
        pad_y = max(3, h // 3)
        x0 = max(0, x - pad_x)
        y0 = max(0, y - pad_y)
        x1 = min(width, x + w + pad_x)
        y1 = min(height, y + h + pad_y)
        crops.append(image[y0:y1, x0:x1].copy())
        padded_boxes.append((x0, y0, x1 - x0, y1 - y0))
    return crops, padded_boxes


_VALID_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


def _detect_orientation_simple(
    image: ImageArray,
    ocr_backend,
    *,
    language: str = "de",
) -> dict[str, object]:
    timings: dict[str, float] = {}
    probe_search_started = time.monotonic()
    probe_image, probe_bbox, probe_score = _select_text_probe(image)
    timings["orientation_probe_search_sec"] = time.monotonic() - probe_search_started

    probe_ocr_started = time.monotonic()
    lines_0 = ocr_backend.recognize(probe_image, language=language)
    timings["orientation_probe_ocr_0_sec"] = time.monotonic() - probe_ocr_started

    rotate_started = time.monotonic()
    probe_rotated = _rotate_180(probe_image)
    timings["orientation_probe_rotate_sec"] = time.monotonic() - rotate_started

    probe_ocr_started = time.monotonic()
    lines_180 = ocr_backend.recognize(probe_rotated, language=language)
    timings["orientation_probe_ocr_180_sec"] = time.monotonic() - probe_ocr_started

    score_0 = _score_ocr_lines(lines_0)
    score_180 = _score_ocr_lines(lines_180)
    score_delta = score_180 - score_0
    rotation_deg = 180 if score_delta > ORIENTATION_SCORE_EPSILON else 0
    oriented_image = image
    timings["orientation_apply_rotation_sec"] = 0.0
    if rotation_deg == 180:
        apply_started = time.monotonic()
        oriented_image = _rotate_180(image)
        timings["orientation_apply_rotation_sec"] = time.monotonic() - apply_started
    reason = (
        f"probe={probe_bbox}, text_score={probe_score:.3f}, "
        f"ocr0={score_0:.3f} ({len(lines_0)} lines), "
        f"ocr180={score_180:.3f} ({len(lines_180)} lines), "
        f"delta={score_delta:.3f}, epsilon={ORIENTATION_SCORE_EPSILON:.3f}"
    )
    return {
        "rotation_deg": rotation_deg,
        "reason": reason,
        "image": oriented_image,
        "timings": timings,
    }


def _select_text_probe(image: ImageArray) -> tuple[ImageArray, tuple[int, int, int, int], float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    probe_width = min(width, max(640, int(width * 0.52)))
    probe_height = min(height, max(220, int(height * 0.12)))
    x0 = max(0, (width - probe_width) // 2)
    step = max(64, probe_height // 2)
    center_y = max(0, (height - probe_height) // 2)

    positions: list[int] = [center_y]
    current = center_y - step
    while current >= 0:
        positions.append(current)
        current -= step
    current = center_y + step
    while current + probe_height <= height:
        positions.append(current)
        current += step

    best_bbox = (x0, center_y, probe_width, probe_height)
    best_score = float("-inf")
    for y0 in positions:
        crop = gray[y0 : y0 + probe_height, x0 : x0 + probe_width]
        score = _text_presence_score(crop)
        if score > best_score:
            best_score = score
            best_bbox = (x0, y0, probe_width, probe_height)
        if score >= 0.16:
            break

    x, y, w, h = best_bbox
    return image[y : y + h, x : x + w].copy(), best_bbox, best_score


def _text_presence_score(gray_crop: ImageArray) -> float:
    stddev = float(gray_crop.std()) / 255.0
    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark_ratio = float((binary > 0).mean())
    edges = cv2.Canny(gray_crop, 80, 160)
    edge_ratio = float((edges > 0).mean())
    return (stddev * 0.35) + (edge_ratio * 0.45) + (min(dark_ratio, 0.30) * 0.20)


def _score_ocr_lines(lines: list[OCRLine]) -> float:
    if not lines:
        return float("-inf")
    text = " ".join(line.text for line in lines).strip()
    if not text:
        return float("-inf")
    avg_conf = _avg_confidence(lines)
    words = text.split()
    valid_words = sum(1 for word in words if _VALID_WORD.search(word))
    valid_ratio = valid_words / max(1, len(words))
    alpha_chars = sum(1 for char in text if char.isalpha())
    alpha_ratio = alpha_chars / max(1, len(text))
    lowercase_bonus = 0.08 if any(char.islower() for char in text) else 0.0
    punctuation_bonus = 0.08 if any(char in text for char in ".,;:!?") else 0.0
    return (avg_conf * 0.60) + (valid_ratio * 0.24) + (alpha_ratio * 0.08) + lowercase_bonus + punctuation_bonus


def _rotate_180(image: ImageArray) -> ImageArray:
    return cv2.rotate(image, cv2.ROTATE_180)
