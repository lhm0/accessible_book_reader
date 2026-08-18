# Planar ChArUco Remap

Last reviewed: `2026-06-26`

Deutsche Fassung: [Planarer ChArUco-Remap](../docs_DE/PLANAR_CHARUCO_REMAP.md)

## Purpose

This tool uses exactly one `ChArUco` calibration image to generate a smooth,
full-frame rectification map for a fixed camera.

Files:

- [calibration/calibrate_planar_charuco.py](../calibration/calibrate_planar_charuco.py)
- [calibration/apply_saved_remap.py](../calibration/apply_saved_remap.py)

## When to Use This Approach

For ABR, this path is preferable to conventional multi-image camera
calibration when:

- the camera remains mechanically fixed
- the camera assembly will not be changed afterward
- practical full-frame rectification is required from a single reference
  image

This is a better fit for the scanner's fixed camera assembly than the earlier
piecewise planar warp.

The currently verified project state is:

- `cam0` and `cam1` are mechanically aligned
- a current remap is stored for each camera
- these remaps are the preferred basis for actual scanner images

## Principle

The script:

1. detects `ArUco` markers and `ChArUco` corners in the calibration image
2. derives a global camera model with radial distortion
3. smoothly undistorts the entire image with `OpenCV`
4. optionally rectifies the image plane into a true rectangle using a
   perspective transform
5. writes the saved remap and preview images

The important differences are:

- no piecewise triangular warp
- no local discontinuities between control points
- areas between markers are rectified just as smoothly as the markers
  themselves
- the remaining trapezoidal shape of the obliquely photographed board can
  also be removed

## Prerequisites

In the local virtual environment on the Mac:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install opencv-contrib-python numpy
```

## Generate a Remap from One Calibration Image

Example using the existing `cam1_charuco_01.jpg` image:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --alpha 1.0 \
  --preview-width 1600
```

The script writes:

- `calibration/out/cam1_planar.npz`
- `calibration/out/cam1_planar.json`
- `calibration/out/cam1_planar_rectified.jpg`
- `calibration/out/cam1_planar_detected.jpg`

Equivalent command for `cam0`:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam0_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam0_planar \
  --alpha 1.0 \
  --preview-width 1600
```

To reduce black border areas while accepting more cropping:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --alpha 0.0 \
  --crop-valid
```

To apply lens undistortion only and deliberately retain perspective:

```bash
python calibration/calibrate_planar_charuco.py \
  --image calibration/shots/cam1_charuco_01.jpg \
  --board-json calibration/out/charuco_160x240.json \
  --output-prefix calibration/out/cam1_planar \
  --no-perspective-rectify
```

## Apply a Remap to an Image

```bash
python calibration/apply_saved_remap.py \
  --input calibration/shots/cam1_charuco_01.jpg \
  --remap calibration/out/cam1_planar.npz \
  --output calibration/out/cam1_charuco_01_rectified.jpg
```

Example using an actual `cam0` scan:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg
```

If the specified remap does not exist yet, `apply_saved_remap.py` now creates
it automatically, provided that:

- the matching calibration image exists, for example
  `calibration/shots/cam0_charuco_01.jpg`
- the board JSON exists or can be generated automatically as
  `charuco_160x240.json`

For the standard path, this command is therefore often sufficient:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg
```

An explicit calibration image remains optional:

```bash
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg \
  --calibration-image calibration/shots/cam0_charuco_01.jpg
```

## Notes

- Keep the `ChArUco` board as flat as possible.
- Do not change the camera assembly after calibration.
- Regenerate the remap if focus, camera angle, or camera height changes.
- A remap is valid only for its specific camera and mechanical assembly.
- Current remaps:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`
