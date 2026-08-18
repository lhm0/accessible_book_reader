# ChArUco Board

Last reviewed: `2026-06-26`

Deutsche Fassung: [ChArUco-Board](../docs_DE/CHARUCO_BOARD.md)

## Purpose

This tool generates a printable `ChArUco` board for camera calibration.

File:

- [calibration/generate_charuco_board.py](../calibration/generate_charuco_board.py)

## Recommended Approach for ABR

For the current `IMX519` cameras with `140-degree` wide-angle lenses, a
`ChArUco` board is the most practical calibration approach:

- more robust with strong distortion than a plain checkerboard
- reliable corner detection even when the board is only partially visible
- well suited to later automation with `OpenCV`

The current ABR standard is:

- board size: `160 x 240 mm`
- checkerboard squares: `8 x 12`
- square size: `20 x 20 mm`
- marker length: `14 mm`
- dictionary: `DICT_5X5_50`

The generated reference files are already available under:

- `calibration/out/charuco_160x240.png`
- `calibration/out/charuco_160x240_a4.svg`
- `calibration/out/charuco_160x240.json`

This combination fills the target dimensions exactly:

- `160 / 8 = 20 mm`
- `240 / 12 = 20 mm`

## Preparation

In the local virtual environment on the Mac:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install opencv-contrib-python numpy
```

Important:

- `opencv-python` is not sufficient because it usually does not include
  `cv2.aruco`.
- `opencv-contrib-python` is required.

## Generating the 160 x 240 mm Board

```bash
python calibration/generate_charuco_board.py \
  --output-prefix calibration/out/charuco_160x240
```

The script writes:

- `calibration/out/charuco_160x240.png`
- `calibration/out/charuco_160x240_a4.svg`
- `calibration/out/charuco_160x240.json`

The current calibration images in the repository use this exact board:

- `calibration/shots/cam0_charuco_01.jpg`
- `calibration/shots/cam1_charuco_01.jpg`

## Output Files

- `PNG`: raster image containing only the board
- `A4 SVG`: print-ready page with the `160 x 240 mm` board centered at its
  exact physical size
- `JSON`: board parameters for later calibration and documentation

## Printing Instructions

Print the SVG:

- at `100%`
- without `Fit to page`
- without automatic scaling

Then verify the dimensions with a ruler:

- total board width: `160 mm`
- total board height: `240 mm`
- one checkerboard square: `20 mm`

If these measurements are incorrect, the printout is not suitable for
accurate calibration.
