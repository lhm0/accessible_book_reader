#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_csv_floats(value: str, expected_count: int, name: str) -> list[float]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if len(parts) != expected_count:
        raise argparse.ArgumentTypeError(
            f"{name} muss genau {expected_count} kommagetrennte Werte enthalten."
        )
    try:
        return [float(item) for item in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} enthaelt ungueltige Zahlenwerte.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Entzerrt ein Bild mit manuell gesetzten Kameraparametern. "
            "Unterstuetzt Standardmodell und OpenCV-Fisheye-Modell."
        )
    )
    parser.add_argument("--input", required=True, help="Pfad zum Eingabebild")
    parser.add_argument("--output", required=True, help="Pfad zum Ausgabebild")
    parser.add_argument(
        "--model",
        choices=["standard", "fisheye"],
        default="fisheye",
        help="Entzerrungsmodell, Standard: fisheye",
    )
    parser.add_argument("--fx", type=float, required=True, help="Brennweite fx in Pixel")
    parser.add_argument("--fy", type=float, required=True, help="Brennweite fy in Pixel")
    parser.add_argument("--cx", type=float, required=True, help="Hauptpunkt cx in Pixel")
    parser.add_argument("--cy", type=float, required=True, help="Hauptpunkt cy in Pixel")
    parser.add_argument(
        "--dist",
        required=True,
        help=(
            "Verzeichnungskoeffizienten als CSV. "
            "Fisheye: k1,k2,k3,k4. Standard: k1,k2,p1,p2,k3."
        ),
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=0.0,
        help="Nur fisheye: 0.0 bis 1.0, Sichtfeld gegen Beschnitt, Standard: 0.0",
    )
    parser.add_argument(
        "--fov-scale",
        type=float,
        default=1.0,
        help="Nur fisheye: skaliert das neue Kameramodell, Standard: 1.0",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.0,
        help="Nur Standardmodell: 0.0 bis 1.0 fuer neuen Kamerarahmen, Standard: 0.0",
    )
    parser.add_argument(
        "--crop-roi",
        action="store_true",
        help="Nur Standardmodell: schneidet auf die von OpenCV empfohlene ROI zu.",
    )
    parser.add_argument(
        "--preview-width",
        type=int,
        help="Optional: skaliert das Ausgabebild auf diese Breite fuer schnelle Vergleiche.",
    )
    return parser


def build_camera_matrix(args: argparse.Namespace) -> np.ndarray:
    return np.array(
        [
            [args.fx, 0.0, args.cx],
            [0.0, args.fy, args.cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def standard_undistort(
    image: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    alpha: float,
    crop_roi: bool,
) -> np.ndarray:
    height, width = image.shape[:2]
    new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
        camera_matrix,
        dist_coeffs,
        (width, height),
        alpha,
        (width, height),
    )
    undistorted = cv2.undistort(image, camera_matrix, dist_coeffs, None, new_camera_matrix)

    if crop_roi:
        x, y, w, h = roi
        if w > 0 and h > 0:
            undistorted = undistorted[y : y + h, x : x + w]

    return undistorted


def fisheye_undistort(
    image: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    balance: float,
    fov_scale: float,
) -> np.ndarray:
    height, width = image.shape[:2]
    identity = np.eye(3, dtype=np.float64)
    new_camera_matrix = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
        camera_matrix,
        dist_coeffs,
        (width, height),
        identity,
        balance=balance,
        fov_scale=fov_scale,
    )
    map1, map2 = cv2.fisheye.initUndistortRectifyMap(
        camera_matrix,
        dist_coeffs,
        identity,
        new_camera_matrix,
        (width, height),
        cv2.CV_16SC2,
    )
    return cv2.remap(image, map1, map2, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f"Eingabebild konnte nicht gelesen werden: {input_path}")

    camera_matrix = build_camera_matrix(args)

    if args.model == "fisheye":
        dist_values = parse_csv_floats(args.dist, 4, "dist")
        dist_coeffs = np.array(dist_values, dtype=np.float64).reshape(4, 1)
        undistorted = fisheye_undistort(
            image=image,
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs,
            balance=args.balance,
            fov_scale=args.fov_scale,
        )
    else:
        dist_values = parse_csv_floats(args.dist, 5, "dist")
        dist_coeffs = np.array(dist_values, dtype=np.float64).reshape(1, 5)
        undistorted = standard_undistort(
            image=image,
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs,
            alpha=args.alpha,
            crop_roi=args.crop_roi,
        )

    if args.preview_width:
        height, width = undistorted.shape[:2]
        scale = args.preview_width / width
        preview_height = max(1, int(round(height * scale)))
        undistorted = cv2.resize(
            undistorted,
            (args.preview_width, preview_height),
            interpolation=cv2.INTER_AREA,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(output_path), undistorted)
    if not ok:
        parser.error(f"Ausgabebild konnte nicht geschrieben werden: {output_path}")

    print(f"Eingabe:  {input_path}")
    print(f"Ausgabe:  {output_path}")
    print(f"Modell:   {args.model}")
    print(f"Matrix K: fx={args.fx}, fy={args.fy}, cx={args.cx}, cy={args.cy}")
    print(f"Dist:     {args.dist}")
    if args.model == "fisheye":
        print(f"Balance:  {args.balance}")
        print(f"FOVScale: {args.fov_scale}")
    else:
        print(f"Alpha:    {args.alpha}")
        print(f"Crop ROI: {args.crop_roi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
