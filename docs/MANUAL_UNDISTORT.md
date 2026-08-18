# Manual Undistortion

Last reviewed: `2026-06-26`

Deutsche Fassung: [Manuelle Entzerrung](../docs_DE/MANUAL_UNDISTORT.md)

## Purpose

This tool undistorts a single image using camera parameters supplied manually.
In the current project, it serves only as a fallback and comparison tool; it
is no longer the preferred calibration path.

File:

- [calibration/manual_undistort.py](../calibration/manual_undistort.py)

## Role in the Current Project

The script is deliberately not a calibration tool.

It accepts:

- camera matrix `K`
- distortion coefficients
- model selection: `fisheye` or `standard`

and uses them to write an undistorted image file.

This allows you to vary values step by step on the Mac and compare their
effects directly.

The currently preferred project path for the Pi cameras is instead:

- generate a `ChArUco` board:
  [CHARUCO_BOARD.md](CHARUCO_BOARD.md)
- calculate a fixed remap from a calibration image:
  [PLANAR_CHARUCO_REMAP.md](PLANAR_CHARUCO_REMAP.md)

## Preparation on the Mac

From the repository:

```bash
cd ~/src/abr
source .venv/bin/activate
```

If `opencv-python` is not yet installed in the local virtual environment:

```bash
pip install opencv-python numpy
```

## Recommendation for the Lens

For a `140-degree` wide-angle lens, start with the `fisheye` model.

It uses:

- `fx`
- `fy`
- `cx`
- `cy`
- `k1,k2,k3,k4`

## Examples

### Fisheye Model

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/fisheye_try_01.jpg \
  --model fisheye \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "0.08,-0.03,0.005,-0.001" \
  --balance 0.2
```

### Standard Model

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/standard_try_01.jpg \
  --model standard \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "-0.25,0.12,0.0,0.0,-0.03" \
  --alpha 0.0
```

## Parameter Notes

### Camera Matrix

- `fx`, `fy`: effective focal lengths in pixels
- `cx`, `cy`: optical center in pixels

A pragmatic starting point for a `4656x3496` image is:

- `cx = 2328`
- `cy = 1748`

This initially assumes that the optical center is at the image center.

### Fisheye Model

- `dist` expects exactly `k1,k2,k3,k4`
- `balance = 0.0`
  - more cropping
  - usually straighter output
- `balance = 1.0`
  - wider field of view
  - potentially more unwanted edge areas

### Standard Model

- `dist` expects exactly `k1,k2,p1,p2,k3`
- `alpha = 0.0`
  - maximum crop to the usable region
- `alpha = 1.0`
  - more of the border retained, with potentially larger black areas

## Practical Workflow

1. Place a test image in `calibration/`.
2. Start with the `fisheye` model.
3. Initially set `cx` and `cy` to the image center.
4. First vary only `k1` and `k2` approximately.
5. Fine-tune `k3` and `k4` afterward.
6. Adjust `balance` to obtain a useful compromise between cropping and
   straight lines.

## Suggested Initial Experiments

For strong barrel distortion with the fisheye model, these values may serve
as approximate search ranges:

- `fx = 1800` to `2600`
- `fy = 1800` to `2600`
- `k1 = 0.02` to `0.20`
- `k2 = -0.20` to `0.05`
- `k3 = -0.05` to `0.05`
- `k4 = -0.02` to `0.02`

These are deliberately only search ranges, not calibration values.

## Optional Faster Comparisons

For quick visual comparison between variants:

```bash
python calibration/manual_undistort.py \
  --input calibration/test_input.jpg \
  --output calibration/out/preview.jpg \
  --model fisheye \
  --fx 2200 \
  --fy 2200 \
  --cx 2328 \
  --cy 1748 \
  --dist "0.08,-0.03,0.005,-0.001" \
  --balance 0.2 \
  --preview-width 1600
```

Only the output file is resized, making visual comparisons faster.
