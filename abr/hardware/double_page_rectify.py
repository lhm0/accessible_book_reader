from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2


@dataclass(slots=True)
class RectifySlot:
    slot_name: str
    camera_index: int
    remap_path: Path
    rotate_deg: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Entzerrt vorhandene Rohbilder einer Buchdoppelseite und erzeugt "
            "einen left/right-Case-Ordner fuer die ABR-Pipeline."
        )
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=Path("captures/latest"),
        help="Session-Ordner mit raw/, Standard: captures/latest",
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
        "--python-executable",
        default=sys.executable,
        help="Python fuer die Remap-Anwendung, Standard: aktueller Interpreter",
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
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.left_camera == args.right_camera:
        raise SystemExit("--left-camera und --right-camera muessen verschieden sein.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session_dir = args.session_dir.expanduser().resolve()
    slots = [
        RectifySlot("left", args.left_camera, resolve_remap_path(args.left_remap, args.left_camera), args.left_rotate),
        RectifySlot("right", args.right_camera, resolve_remap_path(args.right_remap, args.right_camera), args.right_rotate),
    ]
    rectify_existing_capture(
        session_dir=session_dir,
        slots=slots,
        python_executable=args.python_executable,
    )
    print(f"Session:   {session_dir}")
    print(f"Rectified: {session_dir / 'rectified'}")
    print(f"Case-Dir:  {session_dir / 'case'}")
    print(f"Metadata:  {session_dir / 'metadata.json'}")
    return 0


def rectify_existing_capture(
    *,
    session_dir: Path,
    slots: list[RectifySlot],
    python_executable: str,
    rectify_func: Callable[[RectifySlot, Path, Path], list[str]] | None = None,
) -> None:
    raw_dir = session_dir / "raw"
    rectified_dir = session_dir / "rectified"
    case_dir = session_dir / "case"
    metadata_path = session_dir / "metadata.json"

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw-Verzeichnis nicht gefunden: {raw_dir}")

    rectified_dir.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)
    rectify_runner = rectify_func or _build_rectify_runner(python_executable=python_executable)

    metadata = load_metadata(metadata_path)
    metadata["case_dir"] = str(case_dir)
    metadata.setdefault("rectify", {})
    metadata["rectify"]["python_executable"] = python_executable

    slots_metadata = metadata.setdefault("slots", {})

    for slot in slots:
        raw_path = raw_dir / f"cam{slot.camera_index}_raw.jpg"
        if not raw_path.exists():
            raise FileNotFoundError(f"Rohbild nicht gefunden: {raw_path}")

        rectified_path = rectified_dir / f"cam{slot.camera_index}_rectified.jpg"
        case_path = case_dir / f"{slot.slot_name}.jpg"
        rectify_command = rectify_runner(slot, raw_path, rectified_path)
        apply_rotation_in_place(rectified_path, slot.rotate_deg)
        shutil.copy2(rectified_path, case_path)

        slot_metadata = slots_metadata.setdefault(slot.slot_name, {})
        slot_metadata["camera_index"] = slot.camera_index
        slot_metadata["remap_path"] = str(slot.remap_path)
        slot_metadata["raw_path"] = str(raw_path)
        slot_metadata["rectified_path"] = str(rectified_path)
        slot_metadata["case_path"] = str(case_path)
        slot_metadata["rectify_command"] = rectify_command
        slot_metadata["rotate_deg"] = slot.rotate_deg

    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_remap_path(explicit: Path | None, camera_index: int) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return (Path("calibration") / "out" / f"cam{camera_index}_planar.npz").resolve()


def load_metadata(metadata_path: Path) -> dict:
    if not metadata_path.exists():
        return {"session_dir": str(metadata_path.parent), "slots": {}}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def apply_rotation_in_place(image_path: Path, rotate_deg: int) -> None:
    if rotate_deg == 0:
        return
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Bild fuer Rotation nicht lesbar: {image_path}")
    rotated = rotate_image(image, rotate_deg)
    ok = cv2.imwrite(str(image_path), rotated)
    if not ok:
        raise OSError(f"Rotiertes Bild konnte nicht geschrieben werden: {image_path}")


def rotate_image(image, rotate_deg: int):
    if rotate_deg == 0:
        return image
    if rotate_deg == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotate_deg == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotate_deg == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Nicht unterstuetzte Rotation: {rotate_deg}")


def _build_rectify_runner(
    *,
    python_executable: str,
) -> Callable[[RectifySlot, Path, Path], list[str]]:
    remap_script = Path(__file__).resolve().parents[2] / "calibration" / "apply_saved_remap.py"

    def _rectify(slot: RectifySlot, raw_path: Path, rectified_path: Path) -> list[str]:
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


if __name__ == "__main__":
    raise SystemExit(main())
