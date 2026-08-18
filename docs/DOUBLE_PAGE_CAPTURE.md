# Double-Page Capture

Last reviewed: `2026-07-01`

Deutsche Fassung: [Doppelseitenaufnahme](../docs_DE/DOUBLE_PAGE_CAPTURE.md)

## Purpose

This tool is the first production adapter between the physical Raspberry Pi
cameras and the existing OCR/TTS pipeline.

It implements `Sprint 1`:

- capture two real camera images
- apply the existing remaps automatically
- create a standardized `case` directory containing `left.jpg` and
  `right.jpg`
- then create an OCR directory containing `left.png`, `right.png`, and
  `manifest.json`
- then create OCR preprocessing images below `debug/page_1` and `page_2`
- enable the LED channel assigned to each page only while that page is being
  captured

The current debugging phase also provides a simple raw-image mode:

- capture only the two raw images
- default to the resolution stored in the remap file
- store them at the stable path `captures/latest/raw/` for quick download to
  the Mac

The currently preferred OCR path subsequently processes the generated `ocr`
directory with `hardware/run_rapidocr.py`.

OCR preprocessing is also available as a separate tool and is used internally
by `capture_double_page`. `run_fallback_pipeline.py` now processes prepared
OCR images only; for quick runs on the Pi, the lightweight
`hardware/run_rapidocr.py` wrapper is currently preferred.

Important behavior of the production front-panel path:

- `capture_double_page.py` initially captures camera 0 as `case/left.jpg` and
  camera 1 as `case/right.jpg` using the normal assignment.
- After capture, the runtime fetches the result of the previously started
  PN5180 query.
- With orientation 1, the two `case` files keep their assignment.
- With orientation 2, `case/left.jpg` and `case/right.jpg` are swapped.
- The runtime then rotates `case/right.jpg` once by `180` degrees.
- In the NFC runtime path, shared OCR preprocessing does not rotate either
  page again.

## Files

- Module: [abr/hardware/double_page_capture.py](../abr/hardware/double_page_capture.py)
- Wrapper: [hardware/capture_double_page.py](../hardware/capture_double_page.py)
- Shared preprocessing module: [abr/preprocessing/enhance_for_ocr.py](../abr/preprocessing/enhance_for_ocr.py)
- CLI wrapper for isolated preprocessing: [hardware/enhance_for_ocr.py](../hardware/enhance_for_ocr.py)
- Lightweight RapidOCR wrapper: [hardware/run_rapidocr.py](../hardware/run_rapidocr.py)

## Prerequisites on the Pi

- both cameras are detected by `rpicam-hello --list-cameras`
- `rpicam-still` is available
- the project virtual environment is installed
- `opencv-contrib-python` and `numpy` are installed in the virtual environment
- the remaps are available at:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`

Important:

- this tool does **not** require `Picamera2` for capture
- it invokes `rpicam-still` for capture
- without an explicit exposure time, `rpicam-still` retains its normal
  automatic behavior
- without an explicit `--gain`, gain control also remains automatic
- rectification then uses the existing
  [calibration/apply_saved_remap.py](../calibration/apply_saved_remap.py)

## Standard Output

One run creates the following structure below `captures/<session-name>/`:

```text
captures/
  scan_20260626_153000/
    raw/
      cam0_raw.jpg
      cam1_raw.jpg
    rectified/
      cam0_rectified.jpg
      cam1_rectified.jpg
    case/
      left.jpg
      right.jpg
    ocr/
      left.png
      right.png
      manifest.json
    debug/
      page_1/
        01_gray.png
        02_enhanced.png
        03_sharpened.png
        04_binary.png
      page_2/
        01_gray.png
        02_enhanced.png
        03_sharpened.png
        04_binary.png
    metadata.json
```

Meaning:

- `raw/`: raw camera images directly from `rpicam-still`
- `rectified/`: images rectified with the remap
- `case/`: rectified pages before final OCR preparation
- `ocr/`: final input for `python hardware/run_rapidocr.py --ocr-dir ...`
- `debug/`: inspectable OCR preprocessing for both pages
- `metadata.json`: camera indices, remaps, invoked commands, and runtime
  metrics

A stable mirror of the latest run is also always created under
`captures/latest/`.

This path is also the default source for the camera test server's review mode.

## Typical Run on the Pi

From the project's virtual environment:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
```

The tool defaults to:

- left page: camera `0`
- right page: camera `1`
- `LED-left` on `BCM12` during left-page capture
- `LED-right` on `BCM13` during right-page capture
- remaps:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`

The session automatically receives a timestamped name such as
`scan_20260626_153000`.

Measured Raspberry Pi runtime on `2026-07-01` for this mode:

- total capture: approximately `3.85s`
- total rectification: approximately `3.86s`
- total OCR preprocessing with `--no-denoise`: approximately `2.77s`
- complete capture path through `ocr/*.png`: approximately `10.9s`

For comparison:

- the same preprocessing stage previously took approximately `15.5s` with
  denoising enabled
- `--no-denoise` is therefore the currently preferred setting

## Step-by-Step Raw-Image Test

For the current image-quality check, capture raw images first:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.hardware.double_page_capture --raw-only
```

Important:

- without `--width/--height`, the tool now defaults to the calibration
  resolution stored in each remap
- this should select the full-resolution path for the current setup
- the resulting images are stored at:
  - `captures/latest/raw/cam0_raw.jpg`
  - `captures/latest/raw/cam1_raw.jpg`

These two files are the preferred first download path to the Mac.

## Step-by-Step Rectification Test

Once the raw images look correct, rectify the existing images without
capturing them again:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.hardware.double_page_rectify
```

Alternatively, use the wrapper:

```bash
python hardware/rectify_double_page.py
```

The default path:

- reads from `captures/latest/raw/`
- writes to:
  - `captures/latest/rectified/`
  - `captures/latest/case/`
  - `captures/latest/ocr/`
  - `captures/latest/debug/`

Expected files:

```text
captures/latest/rectified/cam0_rectified.jpg
captures/latest/rectified/cam1_rectified.jpg
captures/latest/case/left.jpg
captures/latest/case/right.jpg
captures/latest/ocr/left.png
captures/latest/ocr/right.png
captures/latest/ocr/manifest.json
captures/latest/debug/page_1/02_enhanced.png
captures/latest/debug/page_2/02_enhanced.png
captures/latest/metadata.json
```

These paths make it easy to copy the rectified images back to the Mac.

If one page is upside down after rectification, a fixed post-rotation can be
specified per page.

Typical case for the current setup:

```bash
python -m abr.hardware.double_page_rectify --right-rotate 180
```

This rotates only the right page by `180` degrees after rectification and
before writing `case/right.jpg`.

This manual parameter is intended for isolated capture and rectification
tests. In the production front-panel path, the right page is rotated
automatically after NFC-based assignment.

## Current Follow-Up Command

After a successful capture, the currently preferred OCR run is:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

Important:

- the wrapper still provides optional additional orientation detection
- it is currently **not** part of the preferred standard path
- it presently costs several seconds per page and is intended for separate
  optimization later

## Important Options

Fixed session name:

```bash
python hardware/capture_double_page.py --session-name first_book_scan
```

Different camera assignment:

```bash
python hardware/capture_double_page.py --left-camera 1 --right-camera 0
```

Different remaps:

```bash
python hardware/capture_double_page.py \
  --left-remap calibration/out/cam1_planar.npz \
  --right-remap calibration/out/cam0_planar.npz
```

Higher JPEG quality or a longer timeout:

```bash
python hardware/capture_double_page.py \
  --jpeg-quality 98 \
  --timeout-ms 2000
```

Shared manual exposure time for both cameras:

```bash
python hardware/capture_double_page.py \
  --shutter-us 8000
```

Notes:

- `--shutter-us` sets the exposure time in microseconds for both pages
- without `--shutter-us`, automatic exposure remains active

Shared manual gain for both cameras:

```bash
python hardware/capture_double_page.py \
  --gain 1.5
```

Fully manual baseline for both cameras:

```bash
python hardware/capture_double_page.py \
  --shutter-us 8000 \
  --gain 1.5
```

Notes:

- `--gain` sets analog gain for both pages
- without `--gain`, automatic gain control remains active

Run OCR preprocessing in isolation on an existing `case` directory:

```bash
python hardware/enhance_for_ocr.py \
  --case-dir captures/latest/case \
  --ocr-dir captures/latest/ocr \
  --debug-dir captures/latest/debug
```

This is the same preprocessing path used internally by
`capture_double_page`.

Capture raw images only, without rectification or case generation:

```bash
python -m abr.hardware.double_page_capture --raw-only
```

Rectify a specific session directory instead of `captures/latest/`:

```bash
python -m abr.hardware.double_page_rectify --session-dir captures/scan_20260626_184412
```

## Continuing Through the Pipeline

After a successful capture, pass the generated `ocr` directory to the
existing OCR/TTS pipeline.

Example using the complete fallback path:

```bash
python run_fallback_pipeline.py \
  --case-dir captures/scan_20260626_153000/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/scan_20260626_153000
```

For a direct OCR comparison, the same prepared `ocr` directory can be
processed with Tesseract:

```bash
python run_fallback_pipeline.py \
  --case-dir captures/scan_20260626_153000/ocr \
  --ocr-backend tesseract \
  --output-dir runs/scan_20260626_153000_tesseract
```

Or with live TTS:

```bash
export GOOGLE_CLOUD_QUOTA_PROJECT=YOUR_PROJECT_ID
python run_fallback_pipeline.py \
  --case-dir captures/scan_20260626_153000/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --speak \
  --live-tts-max-chars 700 \
  --no-debug-artifacts \
  --output-dir runs/scan_20260626_153000_live
```

## Sprint 1 Acceptance Criteria

`Sprint 1` is successful when:

- `hardware/capture_double_page.py` creates two raw images
- both raw images are rectified automatically
- `case/left.jpg` and `case/right.jpg` are created
- `ocr/left.png` and `ocr/right.png` are created
- `python run_fallback_pipeline.py --case-dir ...` runs on the resulting
  `ocr` directory
