# Camera Test Server

Last reviewed: `2026-07-01`

Deutsche Fassung: [Kamera-Testserver](../docs_DE/CAMERA_TEST_SERVER.md)

## Purpose

This script starts a small HTTP server on the `Raspberry Pi 5` and provides
two functional modes:

- `live`: displays the live image from a connected camera in a browser
- `review`: displays two images, one below the other, on a shared page and
  uses radio buttons at the top to switch between four sources:
  - `raw images`
  - `rectified images`
  - `enhanced images`
  - `OCR overlay`

The former `capture-review`, `ocr-review`, and `ocr-words-review` modes now
start the same review page with different initial selections.

The currently verified target setup is:

- `2` cameras connected to the `Raspberry Pi 5`
- one test server per camera running on the Pi
- test pages viewed from a Mac over the network
- review of the most recent capture results through `captures/latest/`
- review of the most recent OCR overlays through an appropriate OCR debug
  directory, currently usually `runs/latest_rapidocr/debug/`

## File

- Script: [hardware/camera_test_server.py](../hardware/camera_test_server.py)

## Prerequisites on the Pi

- at least one camera physically connected to `CAM0` or `CAM1`
- `Picamera2` installed on the Pi
- the camera detected by the Pi

For `--mode review`, the requirements are different:

- no active camera is required
- no `Picamera2` dependency is required
- the default sources are:
  - `captures/latest/raw/` for `raw images`
  - `captures/latest/case/` for `rectified images`
  - `captures/latest/debug/page_1|page_2/02_enhanced.png` for `enhanced images`
  - `runs/latest/debug/page_1|page_2/06_ocr_overlay.png` or
    `runs/latest_rapidocr/debug/page_1|page_2/06_ocr_overlay.png` for
    `OCR overlay`

Important driver and overlay findings for the hardware currently in use:

- camera: `Arducam IMX519 16 MP`
- `camera_auto_detect=1` was not sufficient on the current Pi setup
- verified configuration in `/boot/firmware/config.txt`:

```text
camera_auto_detect=0
dtoverlay=imx519,cam0
dtoverlay=imx519,cam1
```

Useful quick check on the Pi:

```bash
rpicam-hello --list-cameras
```

If `Picamera2` is not yet available in the system Python installation:

```bash
sudo apt update
sudo apt install -y python3-picamera2
```

Important notes:

- On Raspberry Pi OS, `Picamera2` is often more reliably available through
  the system Python installation than through an isolated virtual environment.
- `picamera2` was not available in the project's `.venv`.
- The verified test path therefore deliberately uses the system Python:

```bash
/usr/bin/python3 hardware/camera_test_server.py ...
```

Current implementation details:

- The server uses `Picamera2` directly with `JpegEncoder` and `FileOutput`.
- It no longer re-encodes frames through `OpenCV`.
- Consequently, `python3-opencv` is no longer required by the current camera
  test server.

## Starting the Server on the Pi

### Live mode

Typical preview for `CAM0`:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --width 1920 --height 1080
```

Typical preview for `CAM1`:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --camera 1 --port 8001 --width 1920 --height 1080
```

By default, the server binds to `0.0.0.0`, making it available on all network
interfaces.

At startup, the script reports information including:

- camera model
- selected resolution
- a Bonjour URL such as `http://abr.local:8000/`

### Review mode

Combined review page:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010
```

With `raw images` selected initially:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --review-source raw
```

With `enhanced images` selected initially:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --review-source enhanced
```

Using a different capture session directory:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --capture-session-dir captures/latest
```

Using a different OCR debug directory, for example for the lightweight
RapidOCR wrapper:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --ocr-debug-dir runs/latest_rapidocr/debug
```

## Access from a Mac

Open the following addresses in a browser on the Mac:

```text
http://abr.local:8000/
http://abr.local:8001/
http://abr.local:8010/
```

Alternatively, replace `abr.local` with the Pi's IP address.

## Behavior

Default script behavior:

- uses camera index `0`
- selects the largest detected sensor resolution unless an explicit size is
  provided
- streams the image as `MJPEG`
- updates as quickly as the camera, JPEG encoding, and network permit

In `review` mode, the script:

- reads the current state below `captures/latest/` and the configured OCR
  debug directory for every status request
- always displays exactly two images, one below the other
- switches between four sources using radio buttons at the top:
  - `raw`
  - `rectified`
  - `enhanced`
  - `ocr-overlay`
- uses the undistorted camera images from `raw/` for `raw`
- uses the rectified `case/left.jpg` and `case/right.jpg` for `rectified`
- uses `02_enhanced.png`, generated by `capture_double_page` or
  `enhance_for_ocr.py`, for `enhanced`
- uses `06_ocr_overlay.png`, generated by `run_fallback_pipeline.py`, for
  `ocr-overlay`; it may originate from either `run_fallback_pipeline.py` or
  `hardware/run_rapidocr.py`
- refreshes the browser view automatically when a new capture or OCR run
  writes new overlays
- displays the concrete left and right file paths, as well as missing files,
  below the images for the selected source; this makes an `ocr-overlay` path
  problem directly visible in the browser

For the first live test:

- do not start at full resolution
- `1920x1080` is a good starting point for a responsive preview with the
  `IMX519`
- the Pi-reported full resolution of `4656x3496` works for an MJPEG live view
  but is considerably slower

Additional endpoints:

- `/snapshot.jpg`
- `/status.json`
- `/review-status.json`

For example, snapshots can be saved directly from the Mac:

```bash
curl http://abr.local:8000/snapshot.jpg -o calibration/shots/cam0_charuco_01.jpg
curl http://abr.local:8001/snapshot.jpg -o calibration/shots/cam1_charuco_01.jpg
```

For camera alignment, an optional crosshair can be overlaid at the center of
the browser image. Starting the server with `--crosshair` enables it initially;
it can then be toggled on the page using a checkbox.

## Optional Parameters

```bash
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --width 2304 --height 1296
```

Important options:

- `--mode`: `live` or `review`
- the legacy names `capture-review`, `ocr-review`, and `ocr-words-review`
  remain available as aliases that start `review`
- `--camera`: camera index, for example `0`
- `--host`: bind address, default `0.0.0.0`
- `--port`: HTTP port, default `8000`
- `--width` and `--height`: explicit target resolution instead of full
  resolution
- `--crosshair`: initially display the crosshair in the browser image
- `--frame-timeout`: maximum time without a new JPEG frame, default `3.0`
- `--jpeg-quality`: JPEG quality, default `90`
- `--capture-session-dir`: capture source for `--mode review`, default
  `captures/latest`
- `--ocr-debug-dir`: OCR overlay source for `--mode review`, default
  `runs/latest/debug`; usually `runs/latest_rapidocr/debug` for the current
  standard Pi workflow
- `--review-source`: initial selection: `raw`, `rectified`, `enhanced`, or
  `ocr-overlay`
- `--ocr-stage`: obsolete compatibility option from the former `ocr-review`
  mode; ignored

Full sensor resolution with a crosshair:

```bash
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --crosshair
/usr/bin/python3 hardware/camera_test_server.py --camera 1 --port 8001 --crosshair
```

The full resolution of the `IMX519` cameras currently in use is:

- `4656 x 3496`

## Intended Use

The test server is deliberately limited to diagnostics during hardware setup:

- check framing
- check sharpness
- test exposure and lighting
- assess focus and distortion
- capture individual `ChArUco` calibration snapshots
- compare the latest rectified capture results in the browser without
  downloading files separately
- compare per-page OCR preprocessing directly from the actual debug artifacts
  in the browser
- compare the backend-independent OCR text overlay from
  `06_ocr_overlay.png` for both pages directly in the browser

It is not part of the production OCR/TTS pipeline.

## Useful Basic Camera Checks

Before investigating a Python problem, check the basic camera stack directly:

```bash
rpicam-hello --list-cameras
rpicam-hello -t 15000 -n
```

Note for the `Raspberry Pi 5`:

- `rpicam-vid -o test.h264` is not a useful basic check for this project if
  only the H.264 codec path fails.
- For a camera-only check, `rpicam-hello -t 15000 -n` is more informative.
