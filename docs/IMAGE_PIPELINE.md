# Image Pipeline

Last reviewed: `2026-08-19`

Deutsche Fassung: [Bildpipeline](../docs_DE/IMAGE_PIPELINE.md)

## Purpose

This document defines which image operations belong to each processing stage
and identifies the currently preferred path for the Raspberry Pi scanner.

The responsibilities are separated as follows:

- `capture_double_page`: capture, rectify, and prepare OCR images
- `enhance_for_ocr`: isolated image enhancement for existing `case` images
- `run_rapidocr.py`: lightweight OCR run for `ocr/left.png` and
  `ocr/right.png`
- `run_fallback_pipeline.py`: complete comparison and TTS path, but not the
  currently preferred runtime path

`run_fallback_pipeline.py` no longer performs **any** image optimization.

Important context:

- the current production path runs through `hardware/control_panel_service.py`
- it captures both pages first and then processes the left page before the
  right page
- in this path, `capture_double_page.py` runs with `--skip-enhance`
- before per-page preparation, the runtime prepares the raw left case image
  in memory and classifies three detected text lines as `0` or `180` degrees
- it applies the resulting shared page assignment once, then prepares the OCR
  image separately for each page

## Manual Reference Path on the Pi

The manual reference path on the Pi remains:

1. `python hardware/capture_double_page.py --no-denoise`
2. `python hardware/run_rapidocr.py --ocr-dir captures/latest/ocr --output-dir runs/latest_rapidocr --orientation-mode off --overlay`

Rationale for this isolated manual path:

- compared with the previous preprocessing path, `--no-denoise` saves
  approximately `12-13s` per spread
- the lightweight RapidOCR wrapper writes `left.txt` early and then writes
  `right.txt`
- the wrapper's older full per-page orientation comparison is too expensive
  and is therefore not enabled by default

The production front-panel path is different: it uses the fast three-line
RapidOCR angle classifier once per spread before normal OCR. It stores a
reliable result per book and falls back to that marker on text-poor pages.

Measured Raspberry Pi performance on `2026-07-01`:

- `capture_double_page`, including rectification and OCR preprocessing:
  approximately `10.9s`
- OCR preprocessing with `--no-denoise` within that run: approximately `2.8s`
- lightweight RapidOCR wrapper with its older simple orientation comparison:
  approximately
  `24.2s`
- for this wrapper, the recommendation remains `--orientation-mode off`;
  production orientation is handled by the separate shared three-line probe

## 1. `capture_double_page`

Wrapper:

- [hardware/capture_double_page.py](../hardware/capture_double_page.py)

Implementation:

- [abr/hardware/double_page_capture.py](../abr/hardware/double_page_capture.py)

Internal sequence:

1. Capture the left raw image.
2. Capture the right raw image.
3. Rectify both raw images using the saved remaps.
4. Write `case/left.jpg` and `case/right.jpg`.
5. Apply the enhancement routine to the `case` directory.
6. Produce OCR-ready input images and debug stages.
7. Publish `captures/latest/` as the latest stable run.

Input:

- cameras `cam0` and `cam1`
- remaps `calibration/out/cam0_planar.npz` and
  `calibration/out/cam1_planar.npz`

Output below `captures/<session>/`:

```text
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

- `case/left.jpg`, `case/right.jpg`: rectified page images
- `ocr/left.png`, `ocr/right.png`: final OCR input for `run_rapidocr.py` or,
  alternatively, `run_fallback_pipeline.py`
- `ocr/manifest.json`: mapping between OCR files and source images, including
  preprocessing timings
- `debug/page_x/...`: inspectable preprocessing stages
- `metadata.json`: capture, rectification, and enhancement timings for the
  complete run

Currently recommended command on the Pi:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
```

## 2. `enhance_for_ocr`

Wrapper:

- [hardware/enhance_for_ocr.py](../hardware/enhance_for_ocr.py)

Implementation:

- [abr/preprocessing/enhance_for_ocr.py](../abr/preprocessing/enhance_for_ocr.py)

Purpose:

- bring existing `case` images to the same OCR-ready state produced by
  `capture_double_page`

Input:

- `case/left.jpg`
- `case/right.jpg`

Output:

- `ocr/left.png`
- `ocr/right.png`
- `ocr/manifest.json`
- `debug/page_1/01_gray.png`
- `debug/page_1/02_enhanced.png`
- `debug/page_1/03_sharpened.png`
- `debug/page_1/04_binary.png`
- `debug/page_2/01_gray.png`
- `debug/page_2/02_enhanced.png`
- `debug/page_2/03_sharpened.png`
- `debug/page_2/04_binary.png`

Important option:

- `--no-denoise`: disables the former main performance bottleneck,
  `fastNlMeansDenoising`

Example:

```bash
python hardware/enhance_for_ocr.py \
  --case-dir testdata/roman_001 \
  --ocr-dir runs/roman_001_prepare/ocr \
  --debug-dir runs/roman_001_prepare/debug \
  --no-denoise
```

## 3. `run_rapidocr.py`

Wrapper:

- [hardware/run_rapidocr.py](../hardware/run_rapidocr.py)

Implementation:

- [abr/capture_ocr.py](../abr/capture_ocr.py)

Purpose:

- recognize the prepared `ocr/left.png` and `ocr/right.png` with `RapidOCR`
- write text early, one page at a time
- optionally create OCR overlays for the review server
- record timings per page and processing stage

Input:

- a prepared OCR directory containing:
  - `left.png`
  - `right.png`
  - `manifest.json`

Wrapper sequence:

1. Load the prepared OCR images.
2. Optionally check simple 0/180-degree orientation.
3. Run OCR for each page.
4. Write and flush `left.txt` immediately.
5. Write `right.txt` afterward.
6. Produce `report.json` and, optionally, `06_ocr_overlay.png`.

Currently recommended command:

```bash
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

Output below `runs/<run>/`:

```text
left.txt
right.txt
report.json
debug/
  page_1/
    06_ocr_overlay.png
  page_2/
    06_ocr_overlay.png
```

Important decision:

- `--orientation-mode simple` remains available as an experimental option
- the currently preferred default is **`--orientation-mode off`**
- this legacy comparison adds several seconds per page and is not used by the
  production runtime

These options control the wrapper's older per-page 0/180 comparison. They do
not disable the production runtime's shared three-line orientation probe.

## 4. `run_fallback_pipeline.py`

Entry points:

- [run_fallback_pipeline.py](../run_fallback_pipeline.py)
- [abr/cli.py](../abr/cli.py)
- [abr/pipeline.py](../abr/pipeline.py)

Input:

- a prepared OCR directory containing:
  - `left.png`
  - `right.png`
  - `manifest.json`

Typical sources:

- `captures/<session>/ocr/`
- `captures/latest/ocr/`
- `runs/<name>_prepare/ocr/`

`run_fallback_pipeline.py` performs the following steps:

1. Load OCR-ready `left.png` and `right.png`.
2. Run OCR.
3. Build layout and paragraphs.
4. Write reading text and the report.
5. Optionally produce TTS output.

`run_fallback_pipeline.py` no longer performs:

- rectification
- contrast enhancement
- sharpening
- binarization

It remains useful for:

- TTS tests
- comparison runs against the lightweight wrapper
- layout, segmentation, and reading-flow logic

Example:

```bash
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/roman_001
```
