#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

try:
    import cv2
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise SystemExit(
        "OpenCV ist nicht installiert. Bitte in der lokalen venv "
        "`pip install opencv-contrib-python numpy` ausfuehren."
    ) from exc


DEFAULT_BOARD_WIDTH_MM = 160.0
DEFAULT_BOARD_HEIGHT_MM = 240.0
DEFAULT_SQUARES_X = 8
DEFAULT_SQUARES_Y = 12
DEFAULT_MARKER_RATIO = 0.7
DEFAULT_DPI = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt ein druckbares ChArUco-Board als PNG sowie eine A4-SVG-Druckvorlage "
            "mit exakter physischer Groesse."
        )
    )
    parser.add_argument(
        "--output-prefix",
        required=True,
        help="Ausgabeprefix ohne Endung, z. B. calibration/out/charuco_160x240",
    )
    parser.add_argument(
        "--width-mm",
        type=float,
        default=DEFAULT_BOARD_WIDTH_MM,
        help=f"Physische Board-Breite in mm, Standard: {DEFAULT_BOARD_WIDTH_MM}",
    )
    parser.add_argument(
        "--height-mm",
        type=float,
        default=DEFAULT_BOARD_HEIGHT_MM,
        help=f"Physische Board-Hoehe in mm, Standard: {DEFAULT_BOARD_HEIGHT_MM}",
    )
    parser.add_argument(
        "--squares-x",
        type=int,
        default=DEFAULT_SQUARES_X,
        help=f"Anzahl Schachbrettfelder horizontal, Standard: {DEFAULT_SQUARES_X}",
    )
    parser.add_argument(
        "--squares-y",
        type=int,
        default=DEFAULT_SQUARES_Y,
        help=f"Anzahl Schachbrettfelder vertikal, Standard: {DEFAULT_SQUARES_Y}",
    )
    parser.add_argument(
        "--marker-ratio",
        type=float,
        default=DEFAULT_MARKER_RATIO,
        help=f"Markerlaenge relativ zur Feldgroesse, Standard: {DEFAULT_MARKER_RATIO}",
    )
    parser.add_argument(
        "--dictionary",
        default="DICT_5X5_50",
        help="ArUco-Dictionary-Name aus OpenCV, Standard: DICT_5X5_50",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Rasterauflosung fuer das PNG, Standard: {DEFAULT_DPI}",
    )
    parser.add_argument(
        "--page-width-mm",
        type=float,
        default=210.0,
        help="Breite der SVG-Druckseite in mm, Standard: 210.0 (A4)",
    )
    parser.add_argument(
        "--page-height-mm",
        type=float,
        default=297.0,
        help="Hoehe der SVG-Druckseite in mm, Standard: 297.0 (A4)",
    )
    return parser


def mm_to_px(length_mm: float, dpi: int) -> int:
    return max(1, int(round((length_mm / 25.4) * dpi)))


def require_aruco() -> object:
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        raise SystemExit(
            "cv2.aruco ist nicht verfuegbar. Bitte `opencv-contrib-python` "
            "statt `opencv-python` installieren."
        )
    return aruco


def build_dictionary(aruco: object, name: str):
    try:
        dictionary_id = getattr(aruco, name)
    except AttributeError as exc:
        raise SystemExit(f"Unbekanntes ArUco-Dictionary: {name}") from exc
    return aruco.getPredefinedDictionary(dictionary_id)


def build_board(aruco: object, squares_x: int, squares_y: int, square_length_mm: float, marker_length_mm: float, dictionary):
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


def render_board_png(board, pixel_width: int, pixel_height: int) -> bytes:
    if hasattr(board, "generateImage"):
        image = board.generateImage((pixel_width, pixel_height), marginSize=0, borderBits=1)
    elif hasattr(board, "draw"):
        image = board.draw((pixel_width, pixel_height), marginSize=0, borderBits=1)
    else:
        raise SystemExit("Die installierte OpenCV-Version kann das ChArUco-Board nicht rendern.")

    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise SystemExit("PNG-Encoding des ChArUco-Boards ist fehlgeschlagen.")
    return bytes(encoded)


def build_print_svg(
    png_bytes: bytes,
    board_width_mm: float,
    board_height_mm: float,
    page_width_mm: float,
    page_height_mm: float,
) -> str:
    if board_width_mm > page_width_mm or board_height_mm > page_height_mm:
        raise SystemExit("Board passt nicht auf die konfigurierte Druckseite.")

    offset_x = (page_width_mm - board_width_mm) / 2.0
    offset_y = (page_height_mm - board_height_mm) / 2.0
    png_b64 = base64.b64encode(png_bytes).decode("ascii")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{page_width_mm}mm"
     height="{page_height_mm}mm"
     viewBox="0 0 {page_width_mm} {page_height_mm}">
  <rect x="0" y="0" width="{page_width_mm}" height="{page_height_mm}" fill="#ffffff"/>
  <image
      x="{offset_x}"
      y="{offset_y}"
      width="{board_width_mm}"
      height="{board_height_mm}"
      preserveAspectRatio="none"
      xlink:href="data:image/png;base64,{png_b64}" />
  <rect
      x="{offset_x}"
      y="{offset_y}"
      width="{board_width_mm}"
      height="{board_height_mm}"
      fill="none"
      stroke="#999999"
      stroke-width="0.2" />
</svg>
"""


def write_metadata(
    metadata_path: Path,
    *,
    width_mm: float,
    height_mm: float,
    squares_x: int,
    squares_y: int,
    square_length_mm: float,
    marker_length_mm: float,
    dictionary: str,
    dpi: int,
    pixel_width: int,
    pixel_height: int,
) -> None:
    payload = {
        "board_width_mm": width_mm,
        "board_height_mm": height_mm,
        "squares_x": squares_x,
        "squares_y": squares_y,
        "square_length_mm": square_length_mm,
        "marker_length_mm": marker_length_mm,
        "dictionary": dictionary,
        "dpi": dpi,
        "pixel_width": pixel_width,
        "pixel_height": pixel_height,
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.width_mm <= 0 or args.height_mm <= 0:
        parser.error("--width-mm und --height-mm muessen groesser als 0 sein.")
    if args.squares_x < 2 or args.squares_y < 2:
        parser.error("--squares-x und --squares-y muessen mindestens 2 sein.")
    if not 0.0 < args.marker_ratio < 1.0:
        parser.error("--marker-ratio muss zwischen 0 und 1 liegen.")
    if args.dpi <= 0:
        parser.error("--dpi muss groesser als 0 sein.")

    square_length_x = args.width_mm / args.squares_x
    square_length_y = args.height_mm / args.squares_y
    if abs(square_length_x - square_length_y) > 1e-6:
        parser.error(
            "Breite/Hoehe und squares-x/squares-y passen nicht exakt zusammen. "
            "Bitte ein konsistentes Seitenverhaeltnis waehlen."
        )

    square_length_mm = square_length_x
    marker_length_mm = square_length_mm * args.marker_ratio
    pixel_width = mm_to_px(args.width_mm, args.dpi)
    pixel_height = mm_to_px(args.height_mm, args.dpi)

    aruco = require_aruco()
    dictionary = build_dictionary(aruco, args.dictionary)
    board = build_board(
        aruco,
        args.squares_x,
        args.squares_y,
        square_length_mm,
        marker_length_mm,
        dictionary,
    )
    png_bytes = render_board_png(board, pixel_width, pixel_height)

    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    png_path = output_prefix.with_suffix(".png")
    svg_path = output_prefix.with_name(f"{output_prefix.name}_a4.svg")
    metadata_path = output_prefix.with_suffix(".json")

    png_path.write_bytes(png_bytes)
    svg_path.write_text(
        build_print_svg(
            png_bytes,
            args.width_mm,
            args.height_mm,
            args.page_width_mm,
            args.page_height_mm,
        ),
        encoding="utf-8",
    )
    write_metadata(
        metadata_path,
        width_mm=args.width_mm,
        height_mm=args.height_mm,
        squares_x=args.squares_x,
        squares_y=args.squares_y,
        square_length_mm=square_length_mm,
        marker_length_mm=marker_length_mm,
        dictionary=args.dictionary,
        dpi=args.dpi,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
    )

    print(f"PNG:      {png_path}")
    print(f"SVG:      {svg_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Board:    {args.width_mm:.1f} x {args.height_mm:.1f} mm")
    print(f"Raster:   {pixel_width} x {pixel_height} px @ {args.dpi} dpi")
    print(f"Squares:  {args.squares_x} x {args.squares_y}")
    print(f"Square:   {square_length_mm:.3f} mm")
    print(f"Marker:   {marker_length_mm:.3f} mm")
    print(f"Dict:     {args.dictionary}")
    print("Druckhinweis: Die SVG auf 100% ohne 'An Seite anpassen' drucken.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
