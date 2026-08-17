from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from abr.debug import DebugArtifactWriter
from abr.models import ImageArray, PreprocessArtifacts
from abr.testdata import resolve_input_images

from .processor import ImagePreprocessor, PreprocessorConfig, apply_configured_page_rotation


PREPROCESS_STAGE_FIELDS: tuple[tuple[str, str], ...] = (
    ("01_gray", "gray"),
    ("02_enhanced", "enhanced"),
    ("03_sharpened", "sharpened"),
    ("04_binary", "binary"),
)
PAGE_OUTPUT_NAMES: dict[str, str] = {
    "page_1": "left",
    "page_2": "right",
}


@dataclass(slots=True)
class EnhancedPageArtifacts:
    page_id: str
    source_path: Path
    ocr_output_path: Path
    debug_paths: dict[str, Path]
    preprocessing: PreprocessArtifacts
    timings: dict[str, float]


@dataclass(slots=True)
class EnhanceRunResult:
    debug_dir: Path
    ocr_dir: Path
    manifest_path: Path
    config: PreprocessorConfig
    pages: list[EnhancedPageArtifacts]
    timings: dict[str, float]


def preprocess_image(
    image: ImageArray,
    config: PreprocessorConfig | None = None,
    *,
    page_id: str | None = None,
    source_path: Path | None = None,
) -> PreprocessArtifacts:
    artifacts, _ = preprocess_image_with_timings(
        image,
        config=config,
        page_id=page_id,
        source_path=source_path,
    )
    return artifacts


def preprocess_image_with_timings(
    image: ImageArray,
    config: PreprocessorConfig | None = None,
    *,
    page_id: str | None = None,
    source_path: Path | None = None,
) -> tuple[PreprocessArtifacts, dict[str, float]]:
    active_config = config or PreprocessorConfig()
    timings: dict[str, float] = {}

    rotation_started = time.monotonic()
    rotated_image = apply_configured_page_rotation(
        image,
        page_id=page_id,
        source_path=source_path,
        config=active_config,
    )
    timings["page_rotation_sec"] = time.monotonic() - rotation_started

    preprocess_started = time.monotonic()
    artifacts, processor_timings = ImagePreprocessor(config=active_config).run_with_timings(rotated_image)
    timings["processor_sec"] = time.monotonic() - preprocess_started
    timings.update(processor_timings)
    timings["preprocess_image_total_sec"] = timings["page_rotation_sec"] + timings["processor_sec"]
    return artifacts, timings


def write_preprocess_debug_artifacts(
    debug_writer: DebugArtifactWriter,
    page_id: str,
    preprocessing: PreprocessArtifacts,
) -> dict[str, Path]:
    debug_paths: dict[str, Path] = {}
    for stage_name, field_name in PREPROCESS_STAGE_FIELDS:
        image = getattr(preprocessing, field_name)
        path = debug_writer.write_image(page_id, stage_name, image)
        if path:
            debug_paths[stage_name] = path
    return debug_paths


def enhance_page_image_path(
    source_path: str | Path,
    *,
    page_id: str,
    debug_dir: Path,
    ocr_dir: Path,
    config: PreprocessorConfig | None = None,
) -> EnhancedPageArtifacts:
    writer = DebugArtifactWriter(debug_dir)
    resolved_debug_dir = writer.output_dir
    if resolved_debug_dir is None:
        raise RuntimeError("Debug-Ausgabeverzeichnis konnte nicht initialisiert werden.")
    resolved_ocr_dir = ocr_dir.expanduser().resolve()
    resolved_ocr_dir.mkdir(parents=True, exist_ok=True)
    return _enhance_page(
        Path(source_path).expanduser().resolve(),
        page_id=page_id,
        debug_writer=writer,
        ocr_dir=resolved_ocr_dir,
        config=config or PreprocessorConfig(),
    )


def enhance_image_paths(
    image_paths: Sequence[str | Path],
    *,
    debug_dir: Path,
    ocr_dir: Path,
    config: PreprocessorConfig | None = None,
) -> EnhanceRunResult:
    import cv2

    run_started = time.monotonic()
    writer = DebugArtifactWriter(debug_dir)
    resolved_debug_dir = writer.output_dir
    if resolved_debug_dir is None:
        raise RuntimeError("Debug-Ausgabeverzeichnis konnte nicht initialisiert werden.")
    resolved_ocr_dir = ocr_dir.expanduser().resolve()
    resolved_ocr_dir.mkdir(parents=True, exist_ok=True)

    pages: list[EnhancedPageArtifacts] = []
    run_timings: dict[str, float] = {}
    for index, image_path in enumerate(image_paths, start=1):
        page_id = f"page_{index}"
        pages.append(
            _enhance_page(
                Path(image_path).expanduser().resolve(),
                page_id=page_id,
                debug_writer=writer,
                ocr_dir=resolved_ocr_dir,
                config=config or PreprocessorConfig(),
            )
        )
    run_timings["page_processing_sec"] = sum(page.timings.get("page_total_sec", 0.0) for page in pages)
    run_timings["manifest_write_sec"] = 0.0
    run_timings["total_sec"] = 0.0
    manifest_started = time.monotonic()
    manifest_path = _write_manifest(
        resolved_ocr_dir,
        pages,
        config=config or PreprocessorConfig(),
        timings=run_timings,
    )
    run_timings["manifest_write_sec"] = time.monotonic() - manifest_started
    run_timings["total_sec"] = time.monotonic() - run_started
    _write_manifest(
        resolved_ocr_dir,
        pages,
        config=config or PreprocessorConfig(),
        timings=run_timings,
    )
    return EnhanceRunResult(
        debug_dir=resolved_debug_dir,
        ocr_dir=resolved_ocr_dir,
        manifest_path=manifest_path,
        config=config or PreprocessorConfig(),
        pages=pages,
        timings=run_timings,
    )


def enhance_case_dir(
    case_dir: Path,
    *,
    debug_dir: Path,
    ocr_dir: Path,
    config: PreprocessorConfig | None = None,
) -> EnhanceRunResult:
    image_paths = resolve_input_images([], case_dir=str(case_dir))
    return enhance_image_paths(
        image_paths,
        debug_dir=debug_dir,
        ocr_dir=ocr_dir,
        config=config,
    )


def _enhance_page(
    source_path: Path,
    *,
    page_id: str,
    debug_writer: DebugArtifactWriter,
    ocr_dir: Path,
    config: PreprocessorConfig,
) -> EnhancedPageArtifacts:
    import cv2

    page_started = time.monotonic()
    imread_started = time.monotonic()
    image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    imread_sec = time.monotonic() - imread_started
    if image is None:
        raise FileNotFoundError(f"Bild konnte nicht geladen werden: {source_path}")

    output_name = PAGE_OUTPUT_NAMES.get(page_id, page_id)
    preprocessing, page_timings = preprocess_image_with_timings(
        image,
        config=config,
        page_id=page_id,
        source_path=source_path,
    )
    page_timings["imread_sec"] = imread_sec

    debug_started = time.monotonic()
    debug_paths = write_preprocess_debug_artifacts(debug_writer, page_id, preprocessing)
    page_timings["debug_write_sec"] = time.monotonic() - debug_started

    ocr_output_path = ocr_dir / f"{output_name}.png"
    ocr_write_started = time.monotonic()
    if not cv2.imwrite(str(ocr_output_path), preprocessing.ocr_input):
        raise RuntimeError(f"OCR-Ausgabebild konnte nicht geschrieben werden: {ocr_output_path}")
    page_timings["ocr_write_sec"] = time.monotonic() - ocr_write_started
    page_timings["page_total_sec"] = time.monotonic() - page_started
    return EnhancedPageArtifacts(
        page_id=page_id,
        source_path=source_path,
        ocr_output_path=ocr_output_path,
        debug_paths=debug_paths,
        preprocessing=preprocessing,
        timings=page_timings,
    )


def _write_manifest(
    ocr_dir: Path,
    pages: Sequence[EnhancedPageArtifacts],
    *,
    config: PreprocessorConfig,
    timings: dict[str, float] | None = None,
) -> Path:
    manifest_path = ocr_dir / "manifest.json"
    payload = {
        "ocr_input_mode": config.ocr_input_mode,
        "denoise_enabled": config.denoise_enabled,
        "timings": timings or {},
        "pages": [
            {
                "page_id": page.page_id,
                "source_path": str(page.source_path),
                "ocr_output_path": str(page.ocr_output_path),
                "debug_paths": {stage: str(path) for stage, path in sorted(page.debug_paths.items())},
                "timings": page.timings,
            }
            for page in pages
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt OCR-fertige left/right-Bilder sowie die Vorverarbeitungsbilder "
            "gray, enhanced, sharpened und binary fuer eine left/right-Case-Struktur "
            "oder explizite Bildpfade."
        )
    )
    parser.add_argument("images", nargs="*", help="Optionale Eingabebilder, wenn --case-dir nicht verwendet wird")
    parser.add_argument("--case-dir", type=Path, help="Case-Ordner mit left/right-Bildern")
    parser.add_argument(
        "--debug-dir",
        type=Path,
        help="Zielverzeichnis fuer debug/page_1 und debug/page_2",
    )
    parser.add_argument(
        "--ocr-dir",
        type=Path,
        required=True,
        help="Zielverzeichnis fuer die finalen OCR-Eingabebilder left.png und right.png",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Veralteter Alias fuer --debug-dir",
    )
    parser.add_argument(
        "--ocr-input-mode",
        default="enhanced",
        choices=["enhanced", "sharpened", "binary"],
        help="Bevorzugte OCR-Quelle fuer spaetere Aufrufer, Standard: enhanced",
    )
    parser.add_argument(
        "--no-denoise",
        action="store_true",
        help="Deaktiviert das langsame De-Noising fuer Vergleichslaufe.",
    )
    parser.add_argument("--sharpen-alpha", type=float, default=1.2, help="Schaerfungsgewicht, Standard: 1.2")
    parser.add_argument("--sharpen-sigma", type=float, default=1.0, help="Gaussian-Sigma fuer Unscharfmaske, Standard: 1.0")
    parser.add_argument(
        "--threshold-block-size",
        type=int,
        default=35,
        help="Blockgroesse fuer adaptive Binarisierung, Standard: 35",
    )
    parser.add_argument(
        "--threshold-c",
        type=int,
        default=11,
        help="C-Wert fuer adaptive Binarisierung, Standard: 11",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.case_dir and not args.images:
        parser.error("Bitte entweder --case-dir oder mindestens ein Bild angeben.")
    if args.debug_dir and args.output_dir:
        parser.error("Bitte nur --debug-dir oder --output-dir verwenden, nicht beides.")
    debug_dir = args.debug_dir or args.output_dir
    if debug_dir is None:
        parser.error("--debug-dir ist erforderlich.")

    config = PreprocessorConfig(
        ocr_input_mode=args.ocr_input_mode,
        denoise_enabled=not args.no_denoise,
        sharpen_alpha=args.sharpen_alpha,
        sharpen_sigma=args.sharpen_sigma,
        threshold_block_size=args.threshold_block_size,
        threshold_c=args.threshold_c,
    )

    if args.case_dir:
        result = enhance_case_dir(
            args.case_dir,
            debug_dir=debug_dir,
            ocr_dir=args.ocr_dir,
            config=config,
        )
    else:
        result = enhance_image_paths(
            args.images,
            debug_dir=debug_dir,
            ocr_dir=args.ocr_dir,
            config=config,
        )

    print(f"Debug-Dir: {result.debug_dir}")
    print(f"OCR-Dir: {result.ocr_dir}")
    print(f"Manifest: {result.manifest_path}")
    for page in result.pages:
        print(f"{page.page_id}: {page.source_path}")
        print(f"  ocr: {page.ocr_output_path}")
        enhanced_path = page.debug_paths.get("02_enhanced")
        if enhanced_path is not None:
            print(f"  enhanced: {enhanced_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
