#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
        description=(
            "Erzeugt aus genau einem ChArUco-Bild eine glatte Vollbild-Entzerrung "
            "fuer einen starren Kameraaufbau."
        )
    )
    parser.add_argument("--image", required=True, help="Kalibrierbild mit ChArUco-Board")
    parser.add_argument(
        "--board-json",
        required=True,
        help="Board-Metadaten aus generate_charuco_board.py",
    )
    parser.add_argument(
        "--output-prefix",
        required=True,
        help="Ausgabeprefix ohne Endung, z. B. calibration/out/cam1_planar",
    )
    parser.add_argument(
        "--min-corners",
        type=int,
        default=24,
        help="Minimale Anzahl detektierter ChArUco-Ecken, Standard: 24",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=1.0,
        help=(
            "0.0 bis 1.0 fuer Beschnitt gegen Sichtfeld. "
            "1.0 behaelt den Randbereich, Standard: 1.0"
        ),
    )
    parser.add_argument(
        "--crop-valid",
        action="store_true",
        help="Schneidet die entzerrte Vorschau auf die gueltige OpenCV-ROI zu.",
    )
    parser.add_argument(
        "--no-perspective-rectify",
        action="store_true",
        help="Ueberspringt die zusaetzliche planare Perspektivkorrektur.",
    )
    parser.add_argument(
        "--pixels-per-mm",
        type=float,
        help=(
            "Optionale Zielpixeldichte fuer die perspektivisch entzerrte Ausgabe. "
            "Ohne Angabe wird sie aus den undistorteten ChArUco-Ecken geschaetzt."
        ),
    )
    parser.add_argument(
        "--preview-width",
        type=int,
        help="Optional: skaliert die Debug-/Preview-Bilder auf diese Breite.",
    )
    return parser


def require_aruco() -> object:
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        raise SystemExit(
            "cv2.aruco ist nicht verfuegbar. Bitte `opencv-contrib-python` "
            "statt `opencv-python` installieren."
        )
    return aruco


def load_board_metadata(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_dictionary(aruco: object, name: str):
    try:
        dictionary_id = getattr(aruco, name)
    except AttributeError as exc:
        raise SystemExit(f"Unbekanntes ArUco-Dictionary: {name}") from exc
    return aruco.getPredefinedDictionary(dictionary_id)


def build_board(aruco: object, metadata: dict[str, object], dictionary):
    squares_x = int(metadata["squares_x"])
    squares_y = int(metadata["squares_y"])
    square_length_mm = float(metadata["square_length_mm"])
    marker_length_mm = float(metadata["marker_length_mm"])

    square_length = square_length_mm / 1000.0
    marker_length = marker_length_mm / 1000.0

    if hasattr(aruco, "CharucoBoard"):
        try:
            return aruco.CharucoBoard(
                (squares_x, squares_y),
                square_length,
                marker_length,
                dictionary,
            )
        except TypeError:
            pass

    if hasattr(aruco, "CharucoBoard_create"):
        return aruco.CharucoBoard_create(
            squares_x,
            squares_y,
            square_length,
            marker_length,
            dictionary,
        )

    raise SystemExit("Die installierte OpenCV-Version unterstuetzt kein ChArUco-Board.")


def make_detector_parameters(aruco: object):
    if hasattr(aruco, "DetectorParameters"):
        return aruco.DetectorParameters()
    return aruco.DetectorParameters_create()


def detect_markers(aruco: object, image: np.ndarray, dictionary):
    parameters = make_detector_parameters(aruco)
    if hasattr(aruco, "ArucoDetector"):
        detector = aruco.ArucoDetector(dictionary, parameters)
        return detector.detectMarkers(image)
    return aruco.detectMarkers(image, dictionary, parameters=parameters)


def interpolate_charuco(aruco: object, marker_corners, marker_ids, gray: np.ndarray, board):
    result = aruco.interpolateCornersCharuco(marker_corners, marker_ids, gray, board)
    if len(result) >= 3:
        return int(result[0]), result[1], result[2]
    raise SystemExit("ChArUco-Interpolation lieferte ein unerwartetes Rueckgabeformat.")


def draw_debug_overlay(image: np.ndarray, marker_corners, marker_ids, charuco_corners, charuco_ids) -> np.ndarray:
    aruco = require_aruco()
    overlay = image.copy()
    if marker_ids is not None and len(marker_ids) > 0 and hasattr(aruco, "drawDetectedMarkers"):
        marker_ids = np.asarray(marker_ids, dtype=np.int32).reshape(-1, 1)
        overlay = aruco.drawDetectedMarkers(overlay, marker_corners, marker_ids)
    if charuco_ids is not None and len(charuco_ids) > 0 and hasattr(aruco, "drawDetectedCornersCharuco"):
        charuco_corners = np.asarray(charuco_corners, dtype=np.float32).reshape(-1, 1, 2)
        charuco_ids = np.asarray(charuco_ids, dtype=np.int32).reshape(-1, 1)
        overlay = aruco.drawDetectedCornersCharuco(overlay, charuco_corners, charuco_ids, (0, 0, 255))
    return overlay


def resize_for_preview(image: np.ndarray, preview_width: int | None) -> np.ndarray:
    if not preview_width:
        return image
    height, width = image.shape[:2]
    if width <= preview_width:
        return image
    scale = preview_width / width
    preview_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (preview_width, preview_height), interpolation=cv2.INTER_AREA)


def crop_to_roi(image: np.ndarray, roi: tuple[int, int, int, int], enabled: bool) -> np.ndarray:
    if not enabled:
        return image
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        return image
    return image[y : y + h, x : x + w]


def build_destination_points(
    metadata: dict[str, object],
    output_width: int,
    output_height: int,
    charuco_ids: np.ndarray,
    board_corners_mm: np.ndarray,
) -> np.ndarray:
    board_width_mm = float(metadata["board_width_mm"])
    board_height_mm = float(metadata["board_height_mm"])
    scale_x = (output_width - 1) / board_width_mm
    scale_y = (output_height - 1) / board_height_mm

    object_points_mm = board_corners_mm[charuco_ids.reshape(-1), :2]
    dst = np.empty((len(charuco_ids), 2), dtype=np.float32)
    dst[:, 0] = object_points_mm[:, 0] * scale_x
    dst[:, 1] = object_points_mm[:, 1] * scale_y
    return dst


def estimate_pixels_per_mm(
    metadata: dict[str, object],
    charuco_ids: np.ndarray,
    charuco_points: np.ndarray,
) -> float:
    squares_x = int(metadata["squares_x"])
    squares_y = int(metadata["squares_y"])
    square_length_mm = float(metadata["square_length_mm"])
    inner_cols = squares_x - 1
    inner_rows = squares_y - 1

    point_by_id = {
        int(point_id): np.asarray(point, dtype=np.float32)
        for point_id, point in zip(charuco_ids.reshape(-1).tolist(), charuco_points.tolist())
    }
    estimates: list[float] = []

    for point_id, point in point_by_id.items():
        col = point_id % inner_cols
        row = point_id // inner_cols

        right_id = point_id + 1
        if col < (inner_cols - 1) and right_id in point_by_id:
            distance = float(np.linalg.norm(point - point_by_id[right_id]))
            estimates.append(distance / square_length_mm)

        down_id = point_id + inner_cols
        if row < (inner_rows - 1) and down_id in point_by_id:
            distance = float(np.linalg.norm(point - point_by_id[down_id]))
            estimates.append(distance / square_length_mm)

    if estimates:
        return float(np.median(np.asarray(estimates, dtype=np.float32)))

    return 10.0


def initial_camera_matrix(image_width: int, image_height: int) -> np.ndarray:
    focal_guess = max(image_width, image_height) * 1.8
    return np.array(
        [
            [focal_guess, 0.0, image_width / 2.0],
            [0.0, focal_guess, image_height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def calibrate_single_view(
    board,
    image_size: tuple[int, int],
    charuco_corners: np.ndarray,
    charuco_ids: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray]:
    object_points, image_points = board.matchImagePoints(charuco_corners, charuco_ids)
    object_points = [np.asarray(object_points, dtype=np.float32).reshape(-1, 1, 3)]
    image_points = [np.asarray(image_points, dtype=np.float32).reshape(-1, 1, 2)]

    camera_matrix = initial_camera_matrix(image_size[0], image_size[1])
    dist_coeffs = np.zeros((5, 1), dtype=np.float64)
    flags = cv2.CALIB_ZERO_TANGENT_DIST
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 200, 1e-8)

    rms, camera_matrix, dist_coeffs, _rvecs, _tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        camera_matrix,
        dist_coeffs,
        flags=flags,
        criteria=criteria,
    )
    return float(rms), camera_matrix, dist_coeffs


def create_undistort_maps(
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    image_size: tuple[int, int],
    alpha: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
        camera_matrix,
        dist_coeffs,
        image_size,
        alpha,
        image_size,
    )
    map_x, map_y = cv2.initUndistortRectifyMap(
        camera_matrix,
        dist_coeffs,
        None,
        new_camera_matrix,
        image_size,
        cv2.CV_32FC1,
    )
    return map_x, map_y, new_camera_matrix, roi


def remap_image(image: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    return cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def undistort_points(
    points: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    new_camera_matrix: np.ndarray,
) -> np.ndarray:
    undistorted = cv2.undistortPoints(
        points.astype(np.float32).reshape(-1, 1, 2),
        camera_matrix,
        dist_coeffs,
        P=new_camera_matrix,
    )
    return undistorted.reshape(-1, 2)


def perspective_rectify(
    image: np.ndarray,
    metadata: dict[str, object],
    charuco_ids: np.ndarray,
    undistorted_charuco: np.ndarray,
    pixels_per_mm: float | None,
) -> tuple[np.ndarray, np.ndarray, tuple[int, int], float]:
    board_width_mm = float(metadata["board_width_mm"])
    board_height_mm = float(metadata["board_height_mm"])
    board_corners_mm = get_chessboard_corners_from_metadata(metadata)

    ppm = pixels_per_mm or estimate_pixels_per_mm(metadata, charuco_ids, undistorted_charuco)
    output_width = max(2, int(round(board_width_mm * ppm)) + 1)
    output_height = max(2, int(round(board_height_mm * ppm)) + 1)
    destination = build_destination_points(
        metadata,
        output_width,
        output_height,
        charuco_ids,
        board_corners_mm,
    )
    homography, _mask = cv2.findHomography(undistorted_charuco, destination, method=0)
    if homography is None:
        raise RuntimeError("Perspektiv-Homographie konnte nicht bestimmt werden.")
    rectified = cv2.warpPerspective(
        image,
        homography,
        (output_width, output_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return rectified, homography, (output_width, output_height), ppm


def get_chessboard_corners_from_metadata(metadata: dict[str, object]) -> np.ndarray:
    squares_x = int(metadata["squares_x"])
    squares_y = int(metadata["squares_y"])
    square_length_mm = float(metadata["square_length_mm"])
    inner_cols = squares_x - 1
    inner_rows = squares_y - 1
    corners: list[list[float]] = []
    for row in range(inner_rows):
        for col in range(inner_cols):
            corners.append(
                [
                    float((col + 1) * square_length_mm),
                    float((row + 1) * square_length_mm),
                    0.0,
                ]
            )
    return np.asarray(corners, dtype=np.float32)


def write_metadata(
    path: Path,
    *,
    input_image: Path,
    board_json: Path,
    image_width: int,
    image_height: int,
    alpha: float,
    crop_valid: bool,
    perspective_rectified: bool,
    perspective_pixels_per_mm: float | None,
    perspective_output_size: tuple[int, int] | None,
    charuco_corner_count: int,
    reprojection_rms_px: float,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    new_camera_matrix: np.ndarray,
    roi: tuple[int, int, int, int],
) -> None:
    payload = {
        "mode": "single_view_charuco_global_undistort",
        "input_image": str(input_image),
        "board_json": str(board_json),
        "image_width": image_width,
        "image_height": image_height,
        "alpha": alpha,
        "crop_valid": crop_valid,
        "perspective_rectified": perspective_rectified,
        "perspective_pixels_per_mm": perspective_pixels_per_mm,
        "perspective_output_size": list(perspective_output_size) if perspective_output_size else None,
        "charuco_corner_count": charuco_corner_count,
        "reprojection_rms_px": reprojection_rms_px,
        "camera_matrix": camera_matrix.tolist(),
        "dist_coeffs": dist_coeffs.reshape(-1).tolist(),
        "new_camera_matrix": new_camera_matrix.tolist(),
        "valid_roi": list(roi),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not 0.0 <= args.alpha <= 1.0:
        parser.error("--alpha muss zwischen 0.0 und 1.0 liegen.")

    input_path = Path(args.image)
    board_json_path = Path(args.board_json)
    output_prefix = Path(args.output_prefix)

    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f"Kalibrierbild konnte nicht gelesen werden: {input_path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image_height, image_width = gray.shape
    image_size = (image_width, image_height)

    metadata = load_board_metadata(board_json_path)
    aruco = require_aruco()
    dictionary = build_dictionary(aruco, str(metadata["dictionary"]))
    board = build_board(aruco, metadata, dictionary)

    marker_corners, marker_ids, _rejected = detect_markers(aruco, gray, dictionary)
    if marker_ids is None or len(marker_ids) == 0:
        parser.error("Keine ArUco-Marker erkannt. Bild, Druck oder Dictionary pruefen.")

    _interpolated_count, charuco_corners, charuco_ids = interpolate_charuco(
        aruco,
        marker_corners,
        marker_ids,
        gray,
        board,
    )
    if charuco_ids is None or charuco_corners is None:
        parser.error("Keine ChArUco-Ecken interpolierbar. Bild oder Board pruefen.")

    charuco_ids = np.asarray(charuco_ids, dtype=np.int32).reshape(-1, 1)
    charuco_corners = np.asarray(charuco_corners, dtype=np.float32).reshape(-1, 1, 2)
    if len(charuco_ids) < args.min_corners:
        parser.error(
            f"Zu wenige ChArUco-Ecken erkannt: {len(charuco_ids)} < {args.min_corners}. "
            "Board groesser, scharfer oder kontrastreicher aufnehmen."
        )

    reprojection_rms_px, camera_matrix, dist_coeffs = calibrate_single_view(
        board,
        image_size,
        charuco_corners,
        charuco_ids,
    )
    map_x, map_y, new_camera_matrix, roi = create_undistort_maps(
        camera_matrix,
        dist_coeffs,
        image_size,
        args.alpha,
    )

    undistorted_full = remap_image(image, map_x, map_y)
    undistorted = crop_to_roi(undistorted_full, roi, args.crop_valid)
    perspective_homography: np.ndarray | None = None
    perspective_output_size: tuple[int, int] | None = None
    perspective_pixels_per_mm: float | None = None
    if not args.no_perspective_rectify:
        undistorted_charuco = undistort_points(
            charuco_corners,
            camera_matrix,
            dist_coeffs,
            new_camera_matrix,
        )
        undistorted, perspective_homography, perspective_output_size, perspective_pixels_per_mm = perspective_rectify(
            undistorted_full,
            metadata,
            charuco_ids,
            undistorted_charuco,
            args.pixels_per_mm,
        )
    overlay = draw_debug_overlay(image, marker_corners, marker_ids, charuco_corners, charuco_ids)

    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    remap_path = output_prefix.with_suffix(".npz")
    metadata_path = output_prefix.with_suffix(".json")
    rectified_path = output_prefix.with_name(f"{output_prefix.name}_rectified.jpg")
    overlay_path = output_prefix.with_name(f"{output_prefix.name}_detected.jpg")

    np.savez_compressed(
        remap_path,
        map_x=map_x,
        map_y=map_y,
        image_width=np.int32(image_width),
        image_height=np.int32(image_height),
        perspective_homography=perspective_homography if perspective_homography is not None else np.empty((0, 0), dtype=np.float32),
        perspective_output_width=np.int32(perspective_output_size[0]) if perspective_output_size else np.int32(0),
        perspective_output_height=np.int32(perspective_output_size[1]) if perspective_output_size else np.int32(0),
    )
    write_metadata(
        metadata_path,
        input_image=input_path,
        board_json=board_json_path,
        image_width=image_width,
        image_height=image_height,
        alpha=args.alpha,
        crop_valid=args.crop_valid,
        perspective_rectified=not args.no_perspective_rectify,
        perspective_pixels_per_mm=perspective_pixels_per_mm,
        perspective_output_size=perspective_output_size,
        charuco_corner_count=len(charuco_ids),
        reprojection_rms_px=reprojection_rms_px,
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        new_camera_matrix=new_camera_matrix,
        roi=roi,
    )
    cv2.imwrite(str(rectified_path), resize_for_preview(undistorted, args.preview_width))
    cv2.imwrite(str(overlay_path), resize_for_preview(overlay, args.preview_width))

    print(f"Remap:     {remap_path}")
    print(f"Metadata:  {metadata_path}")
    print(f"Rectified: {rectified_path}")
    print(f"Detected:  {overlay_path}")
    print(f"Corners:   {len(charuco_ids)}")
    print(f"RMS:       {reprojection_rms_px:.3f} px")
    print(f"Alpha:     {args.alpha:.2f}")
    if perspective_output_size and perspective_pixels_per_mm:
        print(f"Planar:    {perspective_output_size[0]}x{perspective_output_size[1]} @ {perspective_pixels_per_mm:.3f} px/mm")
    print(f"Input:     {image_width}x{image_height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
