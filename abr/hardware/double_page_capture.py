from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from abr.hardware.double_page_rectify import apply_rotation_in_place
from abr.hardware.led_control import LEDController
from abr.preprocessing.enhance_for_ocr import enhance_case_dir
from abr.preprocessing.processor import PreprocessorConfig


DEFAULT_OUTPUT_ROOT = Path("captures")
DEFAULT_STILL_COMMAND = "rpicam-still"


@dataclass(slots=True)
class CaptureSlot:
    slot_name: str
    camera_index: int
    remap_path: Path
    rotate_deg: int = 0
    led_channel: str | None = None


@dataclass(slots=True)
class CaptureSessionResult:
    session_dir: Path
    case_dir: Path | None
    ocr_dir: Path | None
    metadata_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erfasst eine Buchdoppelseite mit zwei Pi-Kameras, entzerrt beide Bilder "
            "und erzeugt einen left/right-Case-Ordner fuer die bestehende ABR-Pipeline."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Zielwurzel fuer Scan-Sessions, Standard: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--session-name",
        help="Optionaler fester Session-Name statt des Zeitstempels.",
    )
    parser.add_argument(
        "--left-camera",
        type=int,
        default=0,
        help="Kameraindex fuer die linke Buchseite, Standard: 0",
    )
    parser.add_argument(
        "--right-camera",
        type=int,
        default=1,
        help="Kameraindex fuer die rechte Buchseite, Standard: 1",
    )
    parser.add_argument(
        "--left-remap",
        type=Path,
        help="Optionale Remap-Datei fuer die linke Seite. Standard: calibration/out/cam<left-camera>_planar.npz",
    )
    parser.add_argument(
        "--right-remap",
        type=Path,
        help="Optionale Remap-Datei fuer die rechte Seite. Standard: calibration/out/cam<right-camera>_planar.npz",
    )
    parser.add_argument(
        "--width",
        type=int,
        help="Optionale Capture-Breite fuer rpicam-still.",
    )
    parser.add_argument(
        "--height",
        type=int,
        help="Optionale Capture-Hoehe fuer rpicam-still.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=1200,
        help="Capture-Timeout fuer rpicam-still in Millisekunden, Standard: 1200",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=95,
        help="JPEG-Qualitaet fuer rpicam-still, Standard: 95",
    )
    parser.add_argument(
        "--shutter-us",
        type=int,
        help=(
            "Optionale manuelle Belichtungszeit fuer beide Kameras in Mikrosekunden. "
            "Ohne Angabe bleibt rpicam-still bei der normalen Automatik."
        ),
    )
    parser.add_argument(
        "--gain",
        type=float,
        help=(
            "Optionaler analoger Gain fuer beide Kameras. "
            "Ohne Angabe bleibt die Gain-Regelung im normalen Automatikpfad."
        ),
    )
    parser.add_argument(
        "--still-command",
        default=DEFAULT_STILL_COMMAND,
        help=f"Capture-Kommando, Standard: {DEFAULT_STILL_COMMAND}",
    )
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="Python fuer die Remap-Anwendung, Standard: aktueller Interpreter",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Nur Rohbilder aufnehmen und keinen Rectify-/Case-Ordner erzeugen.",
    )
    parser.add_argument(
        "--left-rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Optionale Nachrotation der linken Seite in Grad, Standard: 0",
    )
    parser.add_argument(
        "--right-rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Optionale Nachrotation der rechten Seite in Grad, Standard: 0",
    )
    parser.add_argument(
        "--no-denoise",
        action="store_true",
        help="Deaktiviert das langsame De-Noising in der OCR-Vorverarbeitung.",
    )
    parser.add_argument(
        "--skip-enhance",
        action="store_true",
        help="Nur Capture/Rectify/Case erzeugen und die OCR-Vorverarbeitung spaeter ausfuehren.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.width is None and args.height is not None:
        raise SystemExit("--height erfordert auch --width.")
    if args.width is not None and args.height is None:
        raise SystemExit("--width erfordert auch --height.")
    if args.left_camera == args.right_camera:
        raise SystemExit("--left-camera und --right-camera muessen verschieden sein.")
    if not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("--jpeg-quality muss zwischen 1 und 100 liegen.")
    if args.shutter_us is not None and args.shutter_us <= 0:
        raise SystemExit("--shutter-us muss groesser als 0 sein.")
    if args.gain is not None and args.gain <= 0:
        raise SystemExit("--gain muss groesser als 0 sein.")
    if args.timeout_ms < 0:
        raise SystemExit("--timeout-ms darf nicht negativ sein.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = args.output_root.expanduser().resolve()
    session_name = args.session_name or timestamp_session_name()
    left_remap = resolve_remap_path(args.left_remap, args.left_camera)
    right_remap = resolve_remap_path(args.right_remap, args.right_camera)
    slots = [
        CaptureSlot(
            slot_name="left",
            camera_index=args.left_camera,
            remap_path=left_remap,
            rotate_deg=args.left_rotate,
            led_channel="left",
        ),
        CaptureSlot(
            slot_name="right",
            camera_index=args.right_camera,
            remap_path=right_remap,
            rotate_deg=args.right_rotate,
            led_channel="right",
        ),
    ]

    result = run_capture_session(
        output_root=output_root,
        session_name=session_name,
        slots=slots,
        width=args.width,
        height=args.height,
        timeout_ms=args.timeout_ms,
        jpeg_quality=args.jpeg_quality,
        shutter_us=args.shutter_us,
        gain=args.gain,
        still_command=args.still_command,
        python_executable=args.python_executable,
        raw_only=args.raw_only,
        enhance_after_capture=not args.skip_enhance,
        preprocessor_config=PreprocessorConfig(denoise_enabled=not args.no_denoise),
    )

    print(f"Session:   {result.session_dir}")
    if result.case_dir is not None:
        print(f"Case-Dir:  {result.case_dir}")
    if result.ocr_dir is not None:
        print(f"OCR-Dir:   {result.ocr_dir}")
    print(f"Metadata:  {result.metadata_path}")
    return 0


def run_capture_session(
    *,
    output_root: Path,
    session_name: str,
    slots: list[CaptureSlot],
    width: int | None,
    height: int | None,
    timeout_ms: int,
    jpeg_quality: int,
    shutter_us: int | None,
    gain: float | None,
    still_command: str,
    python_executable: str,
    raw_only: bool = False,
    enhance_after_capture: bool = True,
    preprocessor_config: PreprocessorConfig | None = None,
    capture_func: Callable[[CaptureSlot, Path], list[str]] | None = None,
    rectify_func: Callable[[CaptureSlot, Path, Path], list[str]] | None = None,
    led_controller: LEDController | None = None,
    enhance_func: Callable[[Path, Path, Path], object] | None = None,
) -> CaptureSessionResult:
    session_dir = output_root / session_name
    raw_dir = session_dir / "raw"
    rectified_dir = session_dir / "rectified"
    case_dir = session_dir / "case"
    ocr_dir = session_dir / "ocr"
    debug_dir = session_dir / "debug"
    latest_dir = output_root / "latest"
    metadata_path = session_dir / "metadata.json"

    if session_dir.exists():
        raise FileExistsError(f"Session-Verzeichnis existiert bereits: {session_dir}")

    raw_dir.mkdir(parents=True)
    if not raw_only:
        rectified_dir.mkdir(parents=True)
        case_dir.mkdir(parents=True)
        ocr_dir.mkdir(parents=True)
        debug_dir.mkdir(parents=True)

    capture_runner = capture_func or _build_capture_runner(
        still_command=still_command,
        width=width,
        height=height,
        timeout_ms=timeout_ms,
        jpeg_quality=jpeg_quality,
        shutter_us=shutter_us,
        gain=gain,
    )
    rectify_runner = rectify_func or _build_rectify_runner(python_executable=python_executable)
    enhance_runner = enhance_func or (
        lambda current_case_dir, current_ocr_dir, current_debug_dir: enhance_case_dir(
            current_case_dir,
            ocr_dir=current_ocr_dir,
            debug_dir=current_debug_dir,
            config=preprocessor_config or PreprocessorConfig(),
        )
    )
    active_led_controller = led_controller or (
        LEDController() if any(slot.led_channel is not None for slot in slots) else None
    )

    metadata = {
        "session_name": session_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "session_dir": str(session_dir),
        "case_dir": str(case_dir) if not raw_only else None,
        "ocr_dir": str(ocr_dir) if not raw_only else None,
        "debug_dir": str(debug_dir) if not raw_only else None,
        "capture": {
            "still_command": still_command,
            "width": width,
            "height": height,
            "timeout_ms": timeout_ms,
            "jpeg_quality": jpeg_quality,
            "shutter_us": shutter_us,
            "gain": gain,
            "python_executable": python_executable,
            "raw_only": raw_only,
            "led_control": any(slot.led_channel is not None for slot in slots),
        },
        "timings": {},
        "enhancement": None,
        "slots": {},
    }
    session_started = time.monotonic()
    session_timings: dict[str, float] = {
        "capture_total_sec": 0.0,
        "rectify_total_sec": 0.0,
        "rotate_total_sec": 0.0,
        "copy_case_total_sec": 0.0,
        "enhancement_total_sec": 0.0,
        "publish_latest_sec": 0.0,
        "metadata_write_sec": 0.0,
        "session_total_sec": 0.0,
    }
    metadata["timings"] = session_timings

    for slot in slots:
        slot_started = time.monotonic()
        slot_timings: dict[str, float] = {}
        raw_path = raw_dir / f"cam{slot.camera_index}_raw.jpg"
        capture_started = time.monotonic()
        capture_command = _capture_with_led(
            slot=slot,
            raw_path=raw_path,
            capture_runner=capture_runner,
            led_controller=active_led_controller,
        )
        slot_timings["capture_sec"] = time.monotonic() - capture_started
        session_timings["capture_total_sec"] += slot_timings["capture_sec"]
        capture_size = determine_capture_size(slot.remap_path, width, height)
        slot_metadata = {
            "camera_index": slot.camera_index,
            "remap_path": str(slot.remap_path),
            "raw_path": str(raw_path),
            "capture_command": capture_command,
            "led_channel": slot.led_channel,
            "capture_size": {
                "width": capture_size[0],
                "height": capture_size[1],
            }
            if capture_size is not None
            else None,
        }
        if raw_only:
            slot_metadata["rectified_path"] = None
            slot_metadata["case_path"] = None
            slot_timings["slot_total_sec"] = time.monotonic() - slot_started
            slot_metadata["timings"] = slot_timings
            metadata["slots"][slot.slot_name] = slot_metadata
            continue

        rectified_path = rectified_dir / f"cam{slot.camera_index}_rectified.jpg"
        case_path = case_dir / f"{slot.slot_name}.jpg"
        rectify_started = time.monotonic()
        rectify_command = rectify_runner(slot, raw_path, rectified_path)
        slot_timings["rectify_sec"] = time.monotonic() - rectify_started
        session_timings["rectify_total_sec"] += slot_timings["rectify_sec"]

        rotate_started = time.monotonic()
        apply_rotation_in_place(rectified_path, slot.rotate_deg)
        slot_timings["rotate_sec"] = time.monotonic() - rotate_started
        session_timings["rotate_total_sec"] += slot_timings["rotate_sec"]

        copy_started = time.monotonic()
        shutil.copy2(rectified_path, case_path)
        slot_timings["copy_case_sec"] = time.monotonic() - copy_started
        session_timings["copy_case_total_sec"] += slot_timings["copy_case_sec"]

        slot_metadata["rectified_path"] = str(rectified_path)
        slot_metadata["case_path"] = str(case_path)
        slot_metadata["rectify_command"] = rectify_command
        slot_metadata["rotate_deg"] = slot.rotate_deg
        slot_timings["slot_total_sec"] = time.monotonic() - slot_started
        slot_metadata["timings"] = slot_timings
        metadata["slots"][slot.slot_name] = slot_metadata

    if not raw_only and enhance_after_capture:
        enhancement_started = time.monotonic()
        enhancement_result = enhance_runner(case_dir, ocr_dir, debug_dir)
        session_timings["enhancement_total_sec"] = time.monotonic() - enhancement_started
        metadata["enhancement"] = _serialize_enhancement_result(enhancement_result)

    publish_started = time.monotonic()
    publish_latest(session_dir, latest_dir, raw_only=raw_only)
    session_timings["publish_latest_sec"] = time.monotonic() - publish_started
    session_timings["session_total_sec"] = time.monotonic() - session_started
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    metadata_write_started = time.monotonic()
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    session_timings["metadata_write_sec"] = time.monotonic() - metadata_write_started
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(metadata_path, latest_dir / "metadata.json")
    return CaptureSessionResult(
        session_dir=session_dir,
        case_dir=None if raw_only else case_dir,
        ocr_dir=None if raw_only else ocr_dir,
        metadata_path=metadata_path,
    )


def timestamp_session_name() -> str:
    return datetime.now().strftime("scan_%Y%m%d_%H%M%S")


def resolve_remap_path(explicit: Path | None, camera_index: int) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return (Path("calibration") / "out" / f"cam{camera_index}_planar.npz").resolve()


def determine_capture_size(
    remap_path: Path,
    override_width: int | None,
    override_height: int | None,
) -> tuple[int, int] | None:
    if override_width is not None and override_height is not None:
        return override_width, override_height
    if not remap_path.exists():
        return None
    data = np.load(remap_path)
    width = int(data.get("image_width", 0))
    height = int(data.get("image_height", 0))
    if width <= 0 or height <= 0:
        return None
    return width, height


def publish_latest(session_dir: Path, latest_dir: Path, *, raw_only: bool) -> None:
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    latest_dir.mkdir(parents=True)
    shutil.copytree(session_dir / "raw", latest_dir / "raw")
    if not raw_only:
        shutil.copytree(session_dir / "rectified", latest_dir / "rectified")
        shutil.copytree(session_dir / "case", latest_dir / "case")
        shutil.copytree(session_dir / "ocr", latest_dir / "ocr")
        shutil.copytree(session_dir / "debug", latest_dir / "debug")


def _capture_with_led(
    *,
    slot: CaptureSlot,
    raw_path: Path,
    capture_runner: Callable[[CaptureSlot, Path], list[str]],
    led_controller: LEDController | None,
) -> list[str]:
    if slot.led_channel is None or led_controller is None:
        return capture_runner(slot, raw_path)

    led_controller.set_channel(slot.led_channel, True)
    try:
        return capture_runner(slot, raw_path)
    finally:
        led_controller.set_channel(slot.led_channel, False)


def _build_capture_runner(
    *,
    still_command: str,
    width: int | None,
    height: int | None,
    timeout_ms: int,
    jpeg_quality: int,
    shutter_us: int | None,
    gain: float | None,
) -> Callable[[CaptureSlot, Path], list[str]]:
    def _capture(slot: CaptureSlot, raw_path: Path) -> list[str]:
        capture_size = determine_capture_size(slot.remap_path, width, height)
        command = [
            still_command,
            "--camera",
            str(slot.camera_index),
            "--nopreview",
            "--timeout",
            str(timeout_ms),
            "--quality",
            str(jpeg_quality),
            "--output",
            str(raw_path),
        ]
        if shutter_us is not None:
            command.extend(["--shutter", str(shutter_us)])
        if gain is not None:
            command.extend(["--gain", str(gain)])
        if capture_size is not None:
            command.extend(["--width", str(capture_size[0]), "--height", str(capture_size[1])])
        subprocess.run(command, check=True)
        if not raw_path.exists():
            raise FileNotFoundError(f"Capture-Ausgabe fehlt: {raw_path}")
        return command

    return _capture


def _build_rectify_runner(
    *,
    python_executable: str,
) -> Callable[[CaptureSlot, Path, Path], list[str]]:
    remap_script = Path(__file__).resolve().parents[2] / "calibration" / "apply_saved_remap.py"

    def _rectify(slot: CaptureSlot, raw_path: Path, rectified_path: Path) -> list[str]:
        command = [
            python_executable,
            str(remap_script),
            "--input",
            str(raw_path),
            "--remap",
            str(slot.remap_path),
            "--output",
            str(rectified_path),
        ]
        subprocess.run(command, check=True)
        if not rectified_path.exists():
            raise FileNotFoundError(f"Rectified-Ausgabe fehlt: {rectified_path}")
        return command

    return _rectify


def _serialize_enhancement_result(result: object) -> dict[str, object] | None:
    manifest_path = getattr(result, "manifest_path", None)
    pages = getattr(result, "pages", None)
    timings = getattr(result, "timings", None)
    config = getattr(result, "config", None)
    if manifest_path is None and pages is None and timings is None and config is None:
        return None

    payload: dict[str, object] = {}
    if manifest_path is not None:
        payload["manifest_path"] = str(manifest_path)
    if config is not None:
        payload["config"] = {
            "ocr_input_mode": getattr(config, "ocr_input_mode", None),
            "denoise_enabled": getattr(config, "denoise_enabled", None),
            "sharpen_alpha": getattr(config, "sharpen_alpha", None),
            "sharpen_sigma": getattr(config, "sharpen_sigma", None),
            "threshold_block_size": getattr(config, "threshold_block_size", None),
            "threshold_c": getattr(config, "threshold_c", None),
        }
    if isinstance(timings, dict):
        payload["timings"] = timings
    if isinstance(pages, list):
        payload["pages"] = [
            {
                "page_id": getattr(page, "page_id", None),
                "source_path": str(getattr(page, "source_path")) if getattr(page, "source_path", None) else None,
                "ocr_output_path": str(getattr(page, "ocr_output_path")) if getattr(page, "ocr_output_path", None) else None,
                "debug_paths": {
                    stage: str(path)
                    for stage, path in getattr(page, "debug_paths", {}).items()
                },
                "timings": getattr(page, "timings", {}),
            }
            for page in pages
        ]
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
