#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit(
        "OpenCV ist nicht installiert. Bitte in der lokalen venv "
        "`pip install opencv-contrib-python numpy` ausfuehren."
    ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wendet eine zuvor gespeicherte Ebenen-Remap auf ein Bild an."
    )
    parser.add_argument("--input", required=True, help="Eingabebild")
    parser.add_argument("--remap", required=True, help="Pfad zur .npz-Remap")
    parser.add_argument("--output", required=True, help="Pfad zum Ausgabebild")
    parser.add_argument(
        "--calibration-image",
        help=(
            "Optionales Kalibrierbild fuer die automatische Remap-Erzeugung, "
            "falls die .npz noch nicht existiert."
        ),
    )
    parser.add_argument(
        "--board-json",
        help=(
            "Optionaler Pfad zur Board-JSON fuer die automatische Remap-Erzeugung. "
            "Standard ist neben der Remap `charuco_160x240.json`."
        ),
    )
    parser.add_argument(
        "--no-auto-generate-remap",
        action="store_true",
        help="Fehlende Remap nicht automatisch erzeugen.",
    )
    parser.add_argument(
        "--calibration-alpha",
        type=float,
        default=1.0,
        help="Alpha-Wert fuer die automatische Remap-Erzeugung, Standard: 1.0",
    )
    parser.add_argument(
        "--calibration-crop-valid",
        action="store_true",
        help="Reicht `--crop-valid` an die automatische Remap-Erzeugung weiter.",
    )
    parser.add_argument(
        "--calibration-no-perspective-rectify",
        action="store_true",
        help="Reicht `--no-perspective-rectify` an die automatische Remap-Erzeugung weiter.",
    )
    parser.add_argument(
        "--calibration-preview-width",
        type=int,
        help=(
            "Optionale Preview-Breite fuer die bei der Auto-Kalibrierung erzeugte "
            "Vorschau."
        ),
    )
    parser.add_argument(
        "--preview-width",
        type=int,
        help="Optional: skaliert das Ausgabebild auf diese Breite.",
    )
    return parser


def resize_for_preview(image, preview_width: int | None):
    if not preview_width:
        return image
    height, width = image.shape[:2]
    if width <= preview_width:
        return image
    scale = preview_width / width
    preview_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (preview_width, preview_height), interpolation=cv2.INTER_AREA)


def script_path(name: str) -> Path:
    return Path(__file__).resolve().with_name(name)


def infer_camera_prefix(input_path: Path, remap_path: Path) -> str | None:
    remap_stem = remap_path.stem
    if remap_stem.endswith("_planar"):
        return remap_stem[: -len("_planar")]

    input_stem = input_path.stem
    if "_" in input_stem:
        prefix = input_stem.split("_", 1)[0]
        if prefix.startswith("cam"):
            return prefix
    return None


def find_calibration_image(input_path: Path, remap_path: Path, explicit: str | None) -> Path:
    if explicit:
        calibration_image = Path(explicit)
        if calibration_image.exists():
            return calibration_image
        raise SystemExit(f"Kalibrierbild nicht gefunden: {calibration_image}")

    camera_prefix = infer_camera_prefix(input_path, remap_path)
    if camera_prefix is None:
        raise SystemExit(
            "Konnte keine Kamera-ID aus Eingabe oder Remap ableiten. "
            "Bitte `--calibration-image` explizit setzen."
        )

    shots_dir = remap_path.resolve().parent.parent / "shots"
    matches = sorted(shots_dir.glob(f"{camera_prefix}_charuco_*.jpg"))
    if matches:
        return matches[0]

    raise SystemExit(
        f"Keine passende Kalibrieraufnahme gefunden. Erwartet wurde z. B. "
        f"`{shots_dir / (camera_prefix + '_charuco_01.jpg')}` oder "
        "`--calibration-image`."
    )


def ensure_board_json(remap_path: Path, explicit: str | None) -> Path:
    if explicit:
        board_json = Path(explicit)
    else:
        board_json = remap_path.with_name("charuco_160x240.json")

    if board_json.exists():
        return board_json

    output_prefix = board_json.with_suffix("")
    command = [
        sys.executable,
        str(script_path("generate_charuco_board.py")),
        "--output-prefix",
        str(output_prefix),
    ]
    print(f"Board-JSON fehlt. Erzeuge Referenzboard mit: {' '.join(command)}")
    subprocess.run(command, check=True)
    if not board_json.exists():
        raise SystemExit(f"Board-JSON konnte nicht erzeugt werden: {board_json}")
    return board_json


def ensure_remap_exists(args: argparse.Namespace, input_path: Path, remap_path: Path) -> None:
    if remap_path.exists():
        return
    if args.no_auto_generate_remap:
        raise SystemExit(f"Remap nicht gefunden: {remap_path}")
    if not 0.0 <= args.calibration_alpha <= 1.0:
        raise SystemExit("--calibration-alpha muss zwischen 0.0 und 1.0 liegen.")

    calibration_image = find_calibration_image(input_path, remap_path, args.calibration_image)
    board_json = ensure_board_json(remap_path, args.board_json)
    output_prefix = remap_path.with_suffix("")

    command = [
        sys.executable,
        str(script_path("calibrate_planar_charuco.py")),
        "--image",
        str(calibration_image),
        "--board-json",
        str(board_json),
        "--output-prefix",
        str(output_prefix),
        "--alpha",
        str(args.calibration_alpha),
    ]
    if args.calibration_crop_valid:
        command.append("--crop-valid")
    if args.calibration_no_perspective_rectify:
        command.append("--no-perspective-rectify")
    if args.calibration_preview_width:
        command.extend(["--preview-width", str(args.calibration_preview_width)])

    print(f"Remap fehlt. Erzeuge sie automatisch mit: {' '.join(command)}")
    subprocess.run(command, check=True)
    if not remap_path.exists():
        raise SystemExit(f"Remap konnte nicht erzeugt werden: {remap_path}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    remap_path = Path(args.remap)
    output_path = Path(args.output)

    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f"Eingabebild konnte nicht gelesen werden: {input_path}")

    ensure_remap_exists(args, input_path, remap_path)
    data = dict(np.load(remap_path))  # type: ignore[name-defined]
    map_x = data["map_x"]
    map_y = data["map_y"]

    rectified = cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    perspective_homography = data.get("perspective_homography")
    perspective_output_width = int(data.get("perspective_output_width", 0))
    perspective_output_height = int(data.get("perspective_output_height", 0))
    if (
        perspective_homography is not None
        and getattr(perspective_homography, "size", 0) == 9
        and perspective_output_width > 0
        and perspective_output_height > 0
    ):
        rectified = cv2.warpPerspective(
            rectified,
            np.asarray(perspective_homography, dtype=np.float64),
            (perspective_output_width, perspective_output_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
    rectified = resize_for_preview(rectified, args.preview_width)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(output_path), rectified)
    if not ok:
        parser.error(f"Ausgabebild konnte nicht geschrieben werden: {output_path}")

    print(f"Eingabe:  {input_path}")
    print(f"Remap:    {remap_path}")
    print(f"Ausgabe:  {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
