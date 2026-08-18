# Software Structure

Last reviewed: `2026-08-18`

Deutsche Fassung: [Softwarestruktur](../docs_DE/SOFTWARE_STRUCTURE.md)

## Purpose

This document explains the current repository structure and maps the principal
modules to the production device path, development tools, and persistent data.

## Runtime Paths

### Production Device Path

The canonical Raspberry Pi entry point is
[hardware/control_panel_service.py](../hardware/control_panel_service.py),
started continuously by the systemd service.

The main flow is:

```text
front-panel event
  -> NFC query through the Pico gateway
  -> capture both cameras
  -> evaluate NFC result and book orientation
  -> prepare, recognize, ingest, and read the left page
  -> process the right page in parallel
  -> update section assembly and summaries
```

### Development and Comparison Path

[run_fallback_pipeline.py](../run_fallback_pipeline.py) runs a complete but
non-production OCR/TTS comparison through `abr.cli` and `abr.pipeline`. It is
retained for backend comparisons, layout tests, and isolated experiments. It
is not the finished device runtime.

## The `abr` Python Package

### `abr/control`: Device Coordination

- [runtime.py](../abr/control/runtime.py)
  - `RuntimeController`, `ForegroundJobManager`, and `PageAudioPlayer`
  - start/stop semantics, heartbeat, and book deletion dialog
  - capture, OCR, ingest, summary, and audio orchestration
  - protection against repeated and backward page scans
- [frontpanel.py](../abr/control/frontpanel.py)
  - long-lived monitor, debounce, and EC11 quadrature decoding
  - hardware events and application-action routing
- [audio_volume.py](../abr/control/audio_volume.py)
  - ten volume levels from 20 to 100 percent
  - thread-safe target value and optional ALSA mixer synchronization
- [artifact_cleanup.py](../abr/control/artifact_cleanup.py)
  - controlled cleanup of short-lived capture and OCR artifacts

### `abr/hardware`: Raspberry Pi Adapters

- [control_panel.py](../abr/hardware/control_panel.py)
  - BCM assignments and the `rpi-gpio`/`pinctrl` backends
- [led_control.py](../abr/hardware/led_control.py)
  - separate lighting for left and right capture
- [double_page_capture.py](../abr/hardware/double_page_capture.py)
  - capture through `rpicam-still`, remapping, and session layout
- [double_page_rectify.py](../abr/hardware/double_page_rectify.py)
  - rectify previously captured raw images
- [pico_gateway_client.py](../abr/hardware/pico_gateway_client.py)
  - shared UART client for the Raspberry Pi Pico gateway
- [nfc_gateway.py](../abr/hardware/nfc_gateway.py)
  - reader status, ISO14443A/ISO15693, and orientation interpretation
  - two-stage `STATUS_START` and `STATUS_FETCH` query

The Raspberry Pi contains no direct PN5180 or PN532 driver. Readers connect
only to the Pico; Pi software sees only the UART protocol.

### `abr/book`: Persistent Book Domain

- [models.py](../abr/book/models.py)
  - `BookRecord`, `ScanRecord`, `PageRecord`, `ChapterRecord`,
    `SummaryRecord`, and chapter markers
- [store.py](../abr/book/store.py)
  - atomic JSON and text storage below `library/<tag_id>/`
  - primary ISO14443A ID and ISO15693 aliases
  - persistent runtime state and language validation
- [session.py](../abr/book/session.py)
  - tag-to-book-session resolution
- [page_ingestor.py](../abr/book/page_ingestor.py)
  - converts OCR reports into semantic `PageRecord`s
  - page numbers, chapter markers, paragraphs, and page transitions
  - separate `clean_text` and `speak_text` fields
  - language-aware TTS preparation
- [chapter_assembler.py](../abr/book/chapter_assembler.py)
  - synthetic sections in a 10-to-20-page window
  - persistent boundaries, including offsets within a page
  - open section text for temporary recaps
- [summary_manager.py](../abr/book/summary_manager.py)
  - Gemini backend for section and book summaries
  - length policy, cache validation, language, and source fingerprint
  - non-persistent summary of the open section
  - optional asynchronous `SummaryService`

See [BOOK_RUNTIME_DATA_ARCHITECTURE.md](BOOK_RUNTIME_DATA_ARCHITECTURE.md) for
the complete data layout.

### Capture, Image Preparation, and OCR

- [capture_ocr.py](../abr/capture_ocr.py)
  - lightweight regular and incremental OCR execution
  - writes reports and optional overlays
- `abr/preprocessing/`
  - `enhance_for_ocr.py`: production per-page preparation
  - `processor.py`: general preprocessing stages
- `abr/orientation/detector.py`
  - optional 0/180-degree detection, disabled in the preferred path
- `abr/ocr/`
  - `base.py` and `factory.py`: backend interface and selection
  - `rapidocr_backend.py`: production local OCR path
  - `tesseract_backend.py`: fallback and comparison
  - `paddle_backend.py`: experimental comparison path
- `abr/layout/basic.py`: basic paragraph and layout blocks
- `abr/input/loader.py`: prepared pipeline input loading
- `abr/debug/`: debug artifacts and visualizations
- `abr/reporting.py`: serialized pipeline reports and timings

The stage boundaries are documented in [IMAGE_PIPELINE.md](IMAGE_PIPELINE.md).

### Text Logic

- [ocr_cleanup.py](../abr/text_logic/ocr_cleanup.py)
  - hyphenation and common OCR artifacts
  - letter-spaced words and all-uppercase headings
  - German pronunciation exceptions `Dr.` → `Doktor` and
    `Notre-Dame` → `Notre Damm`
- [segmenter.py](../abr/text_logic/segmenter.py)
  - sentence and TTS segmentation
- [reading_order.py](../abr/text_logic/reading_order.py)
  - reading order of detected regions

### TTS and Audio Playback

- `abr/tts/base.py`: shared TTS interface
- `abr/tts/command_backend.py`
  - eSpeak, macOS `say`, Piper, OpenAI, and ElevenLabs
  - Google Standard, Neural2, and Gemini Flash TTS
- [audio_playback.py](../abr/audio_playback.py)
  - shared process-wide playback lock
  - block-wise PCM streaming to `aplay`
  - dynamic software volume and underrun protection
- [system_audio.py](../abr/system_audio.py)
  - serial queue for pre-generated system prompts

Production page playback currently uses `google-standard-enhanced`. Its
renderer creates chapter, sentence, paragraph, and dialogue pauses as SSML at
runtime; these annotations are not persisted in book data.

### Language and Google Authentication

- [language_config.py](../abr/language_config.py)
  - immutable German and U.S. English profiles
  - atomic selection in `~/.config/abr/device.json`
- [google_cloud_auth.py](../abr/google_cloud_auth.py)
  - shared ADC access and token, project, and quota-project resolution

Language is propagated through capture, OCR, book, section, summary, and TTS.
Mixed-language data is rejected. See
[LANGUAGE_PROFILES.md](LANGUAGE_PROFILES.md).

### Operational Features

- [wifi_profiles.py](../abr/wifi_profiles.py)
  - NetworkManager profiles, priorities, switching, and persistent autoconnect
- [remote_mail.py](../abr/remote_mail.py), `remote_mail_download.py`, and
  `remote_mail_upload.py`
  - optional validated SMTP/IMAP file transfer
- [usage_statistics.py](../abr/usage_statistics.py)
  - per-book page, audio, and summary counters
- [usage_report.py](../abr/usage_report.py)
  - daily report, e-mail delivery, and archiving

Personal configuration exists only below `~/.config/abr/`, in
`~/.config/gcloud/`, or in NetworkManager, never in the repository.

## Hardware and Diagnostic CLIs

The `hardware/` directory contains thin executable wrappers and diagnostics:

- `control_panel_service.py`: production process entry point
- `capture_double_page.py`, `rectify_double_page.py`: capture and rectification
- `enhance_for_ocr.py`, `run_rapidocr.py`: preparation and OCR
- `camera_test_server.py`: camera live view and artifact review
- `control_panel_test.py`, `led_light_test.py`: hardware diagnostics
- `page_ingest_debug.py`: offline ingest diagnostics
- `generate_audio_message.py`: system-prompt generation
- `pn5180_gateway_client.py`, `pn532_gateway_client.py`: UART terminal wrappers
- `email_download.py`, `email_upload.py`: legacy compatibility wrappers; the
  installed production path uses the `abr.remote_mail_*` modules

## Pico Firmware

- `hardware/pn5180_gateway/`
  - preferred PlatformIO firmware for up to two PN5180 readers
  - shared Pico SPI bus with readers enabled strictly one at a time
- `hardware/pn532_gateway/`
  - alternative PlatformIO firmware using separate Pico I²C buses

Both gateways provide a related line-oriented UART protocol to the Pi. Build
artifacts below `.pio/` are not versioned.

## Calibration

The `calibration/` directory contains:

- `generate_charuco_board.py`: printable reference board
- `calibrate_planar_charuco.py`: camera model and fixed-remap generation
- `apply_saved_remap.py`: remap application to scanner images
- `manual_undistort.py`: manual comparison and fallback path
- `out/`: reference board, remaps, and previews
- `shots/`: calibration captures

## Deployment

The `deploy/` directory contains templates and idempotent installers:

- `install_control_panel_service.sh`: production runtime unit
- `install_language_switch.sh`: global `abr-language` command
- `install_wifi_autoconnect.sh`: one-time privileged NetworkManager setup; no
  permanent ABR unit
- `install_remote_mail.sh`: optional upload timer and download command
- `install_usage_statistics.sh`: optional daily usage report

Installers substitute local user, home, repository, Python, and configuration
paths only when writing units to `/etc/systemd/system/`.

## Hardware Designs, Mechanics, and Audio Assets

- `hardware/electronics/`: KiCad projects and current production data
- `hardware/mechanics/`: CAD sources and exported print files
- `system_audio/messages/de|en/`: pre-generated system prompts
- `system_audio/messages/README.md`: provenance and permitted use of audio

## Runtime and Generated Directories

- `library/`: persistent local book data; do not publish
- `captures/`: short-lived camera and preprocessing artifacts
- `runs/`: manual pipeline and comparison runs
- `temp/`: temporary work data
- `.venv/`, `build/`, `*.egg-info`, `__pycache__/`, `.pytest_cache/`: local
  Python artifacts
- `datasheets/`: deliberately local only, not part of the public repository

The production runtime must write book data only through `BookStore`. Other
generated directories are diagnostic or working areas, not canonical book
data.

## Tests

`tests/` contains unit and integration coverage for all principal layers:

- capture, remapping, image preparation, and OCR backends
- text cleanup, layout, and segmentation
- BookStore, PageIngestor, ChapterAssembler, and SummaryManager
- front panel, runtime, audio, volume, and system prompts
- NFC gateway and UART parsing
- language and the English end-to-end integration path
- Wi-Fi, e-mail, and usage statistics

Run:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m pytest -q
```

Hardware, Google services, and real audio quality are also verified on the Pi;
automated tests replace external services with deterministic test backends.

## Related Architecture Documents

- [CONTROL_PANEL_ARCHITECTURE.md](CONTROL_PANEL_ARCHITECTURE.md)
- [CONTROL_RUNTIME_ARCHITECTURE.md](CONTROL_RUNTIME_ARCHITECTURE.md)
- [BOOK_RUNTIME_DATA_ARCHITECTURE.md](BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [IMAGE_PIPELINE.md](IMAGE_PIPELINE.md)
- [HARDWARE_GPIO_PLAN.md](HARDWARE_GPIO_PLAN.md)
- [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md)
