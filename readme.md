# Accessible Book Reader

Software and hardware repository for the `Accessible Book Reader` (`ABR`).

German documentation: [readme_DE.md](readme_DE.md)

## Licence

The Accessible Book Reader is an open-source and open-hardware project with
strong copyleft. Different kinds of project material use a clearly separated
multi-licence model:

- original software and firmware: `GPL-3.0-or-later`
- original electronics, mechanics, and other hardware designs:
  `CERN-OHL-S-2.0`
- documentation and clearly identified original media: `CC-BY-SA-4.0`
- third-party libraries: their respective original licences

The system messages generated with Google Cloud Text-to-Speech have a
dedicated [provenance and usage notice](system_audio/messages/README.md).

GPL and CERN-OHL-S permit commercial use, but distribution of derived
software or hardware requires the corresponding complete source material to
be made available under the applicable copyleft terms. There is no general
exception for closed commercial derivatives.

The binding scope, third-party exceptions, and exclusions are documented in
[LICENSE.md](LICENSE.md). Full licence texts are stored in [`LICENSES/`](LICENSES/),
and bundled third-party components are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions are governed
by [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Contributor License Agreement](CLA.md). Contributors retain ownership while
granting the project owner the additional right to offer parallel commercial
licences for future business cooperation. Any cooperation that departs from
the public licences requires a separate development and licence agreement
with the relevant rights holders.

No patent or freedom-to-operate search has been performed. The licences can
grant only rights controlled by the respective licensor and do not warrant
that making, using, or distributing the project is free from third-party
rights. See [PATENT_NOTICE.md](PATENT_NOTICE.md), in particular for the
distinction between private builds and commercial use.

The project has progressed beyond a basic OCR/TTS prototype:

- the real capture path with two Raspberry Pi cameras has been verified
- `RapidOCR` runs reliably on the Raspberry Pi
- `Google Cloud TTS` is integrated
- the control panel, NFC book context, page storage, and automatic reading are implemented
- remote file maintenance by e-mail is implemented
- multiple saved Wi-Fi profiles can be selected automatically or switched explicitly
- central German and U.S. English book-language profiles control runtime TTS,
  chapter announcements, and RapidOCR model selection; German remains the
  backwards-compatible default
- new NFC books store their language permanently in `book.json`; OCR, ingest,
  chapter assembly, summaries, and TTS reject mixed-language book data

Current development focuses on:

- stabilising and refining the section and summary layer
- long-term testing of the integrated dual-reader PN5180 path with
  `ISO14443A` and `ISO15693`

## Current production path

The preferred real-world setup on a Raspberry Pi 5 is:

- runtime: `hardware/control_panel_service.py`
- page TTS: `Google Cloud TTS`, using the voice from the active language profile
- system messages: pre-generated WAV files from the active language folder
  (`system_audio/messages/de/` or `system_audio/messages/en/`)
- book identification: PN5180 gateway over UART
- audio hardware: MAX98357A over I2S; the system-wide ALSA `default` device
  must address this card by its symbolic card name

The runtime currently behaves as follows:

- PN5180 polling starts immediately with `STATUS_START`
- both photographs are captured before `STATUS_FETCH` retrieves the book identity;
  NFC reader position is no longer used for page orientation
- an `ISO14443A` tag remains the preferred book key; a simultaneously detected
  `ISO15693` tag is stored as an alternative identifier, while a new book can
  also be created directly from a single `ISO15693` tag
- before the normal page OCR, RapidOCR detects three long text lines in the
  prepared left image and classifies them as upright or upside down
- an upside-down result swaps `case/left.jpg` and `case/right.jpg`
- each reliable result updates `library/<TAG_ID>/state/page_orientation.json`;
  text-poor or empty pages use that stored value instead of aborting
- `case/right.jpg` is then rotated by 180 degrees exactly once; OCR
  preprocessing performs no additional fixed page rotation
- both pages are captured completely before processing begins
- the left page is processed before the right page
- image preparation, OCR, `PageIngestor`, and TTS initially run only for the left page
- while the left page is already playing, the right page proceeds through
  image preparation, OCR, `PageIngestor`, and TTS

## Implemented features

### Device runtime

- long-running front-panel monitor
- `Start / Stop / NFC` triggers the real
  `capture -> image preparation -> OCR -> page-ingest` path
- heartbeat while waiting for the first page audio
- interruptible page playback
- EC11 edge-interrupt volume control with a thread-safe target value; it also
  applies block by block while `bing.wav` or page audio is playing
- book-deletion dialogue using the three-button chord and the EC11 push button
- persistent per-book usage statistics for scanned pages, reading time, and
  both summary functions; daily e-mail reports cover 04:00 to 04:00, including
  days without device use

### Book and page data

- one directory per book under `library/<TAG_ID>/`
- alternative ISO15693 mappings under
  `library/<ISO14443A_TAG_ID>/iso15693_tag_ids.txt`
- persistent OCR orientation fallback under
  `library/<TAG_ID>/state/page_orientation.json`
- `BookStore`
- `PageIngestor`
- `ChapterAssembler` for 10-to-20-page sections with mid-page boundaries
- `SummaryManager` for Gemini section and whole-book summaries
- one `PageRecord` per page
- one `ChapterRecord` per section
- one `ScanRecord` per double-page scan
- automatic page playback based on `speak_text`

### Text cases handled explicitly

- a missing page number on only one side of an otherwise complete double-page
  report; provisional `page_1.json`/`page_2.json` files are replaced with the
  inferred four-digit filenames after the second page is available
- multiple chapter markers on one page
- heading-only pages such as `INTERMEZZO`
- incomplete sentence fragments across pages
- hyphenation across lines and across the left/right page boundary
- letter-spaced words such as `U E B E R S C H R I F T` are spoken without the spacing
- short all-uppercase headings are made readable in `speak_text` and marked as separate paragraphs
- German spoken text replaces `Dr.` with `Doktor` and `Notre-Dame` with
  `Notre Damm`; the source-faithful `clean_text` remains unchanged (stored
  pages receive these replacements only after another page ingest)
- short parenthesised OCR artefacts containing digits are not carried over as
  sentence fragments to the next page
- chapter announcements use cardinal numbers, for example `Kapitel zwei`
- clear SSML pauses before and after chapter announcements

Current sentence-fragment behaviour:

- the right-page tail fragment is also kept in
  `library/<TAG_ID>/state/pending_right_tail_fragment.json`
- if an early-ingested single left page has no page number, this pending state
  is used for the transition to the next page

## Section and summary layer

- sections are assembled from existing `PageRecord` objects after every ingest
- a section ends at the first detected chapter boundary within a 10-to-20-page window
- without a chapter marker, a section ends at the last complete paragraph on
  page 20 and the following boundary is stored persistently
- completed sections are stored under `library/<TAG_ID>/chapters/`
- Gemini creates a section summary when a new section is completed
- the chapter/last-pages summary button speaks the latest section summary,
  creates or refreshes it when needed, and provides an intro plus `bing` heartbeat
- if open text exists after the last completed section, the same action
  combines it with the stored summary into a temporary current recap; this is
  spoken but not stored
- before the first completed section, the available open text is summarised temporarily
- the whole-book summary button creates and speaks a current “previously in
  this book” recap in chapter order, also with an intro and `bing` heartbeat
- if no summary is available, the runtime plays `keine_zusammenfassung`

## Installation

This README is the entry point for a new installation. Detailed hardware setup
and the final verification checklist are covered by
[docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md).

### 1. Prepare the Raspberry Pi and clone the repository

Raspberry Pi OS Lite (64-bit) is recommended. After the first boot, update the
system and install the required packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  htop tmux

mkdir -p ~/src
git clone https://github.com/lhm0/accessible_book_reader.git ~/src/abr
cd ~/src/abr
```

The cameras, header UART, and MAX98357A additionally require the entries in
`/boot/firmware/config.txt` and `/etc/asound.conf` described in the Raspberry
Pi setup guide. The repository's `config.txt` is a reference for the verified
hardware and must not blindly replace an existing boot configuration. Reboot,
then verify the cameras, UART, and audio as documented.

Firmware and wiring for the preferred PN5180 gateway are documented in
[hardware/pn5180_gateway/README.md](hardware/pn5180_gateway/README.md). The
alternative PN532 path is documented in
[hardware/pn532_gateway/README.md](hardware/pn532_gateway/README.md).

### 2. Install the Python environment

Create a fresh environment with the normal `python3`, not PlatformIO's Python,
and do not copy a virtual environment from another computer:

```bash
cd ~/src/abr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google]"
```

Optional OCR backends:

```bash
pip install ".[ocr-tesseract]"
pip install ".[ocr-paddle]"
```

### 3. Configure Google Cloud for TTS and summaries

The production service requires Application Default Credentials (`ADC`) for a
Google Cloud project with billing and the required APIs enabled. After
installing the Google Cloud CLI for Raspberry Pi OS:

```bash
gcloud services enable \
  texttospeech.googleapis.com \
  aiplatform.googleapis.com \
  --project YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID
```

These commands store credentials outside the repository under
`~/.config/gcloud/`. Never copy credential files into the project. The systemd
installer sets `HOME` to the installing user's home directory so that the
service finds the same ADC data. A service account may alternatively be
provided through Google's documented ADC mechanism. See the Raspberry Pi
setup guide for details and test commands.

### 4. Configure the device and install services

Run installers from the repository with `sudo`. They derive the user, home
directory, repository location, and `.venv` from the current installation; no
fixed username or absolute project path is required.

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
sudo deploy/install_control_panel_service.sh
```

This creates `~/.config/abr/device.json` with German as the default when the
file is missing and installs the production service. Select the book language
with `sudo abr-language de` or `sudo abr-language en`. See
[docs/LANGUAGE_PROFILES.md](docs/LANGUAGE_PROFILES.md).

Optional features:

```bash
# Configure persistent autoconnect for saved NetworkManager Wi-Fi profiles
sudo deploy/install_wifi_autoconnect.sh

# First run: create mail.ini; edit it, then run the installer again
sudo deploy/install_remote_mail.sh
sudo deploy/install_remote_mail.sh

# Install only after mail.ini has been configured
sudo deploy/install_usage_statistics.sh
```

Wi-Fi credentials remain in NetworkManager. Add profiles interactively using
the commands in [docs/WIFI_PROFILES.md](docs/WIFI_PROFILES.md). E-mail setup is
described below and in
[docs/REMOTE_MAINTENANCE_EMAIL.md](docs/REMOTE_MAINTENANCE_EMAIL.md).

### Local and generated configuration files

| Path | Purpose and creation | Tracked? |
|---|---|---|
| `/boot/firmware/config.txt` | Camera, UART, and I2S configuration; edit according to the Pi setup guide | No |
| `/etc/asound.conf` | ALSA default for MAX98357A; edit according to the Pi setup guide | No |
| `~/.config/gcloud/` | Google ADC and quota project; generated by `gcloud` or a service-account setup | No |
| `~/.config/abr/device.json` | Book language; generated by `install_language_switch.sh` | No |
| `~/.config/abr/mail.ini` | Mail account and recipient; neutral template generated by `install_remote_mail.sh` | No |
| NetworkManager profiles | SSIDs and Wi-Fi passwords; created interactively with `abr.wifi_profiles` | No |
| `/etc/systemd/system/abr-*.service` and `abr-*.timer` | Local user and project paths; generated by the relevant service installers | No |
| `calibration/out/cam0_planar.npz`, `cam1_planar.npz` | Included reference calibration; regenerate for different camera mechanics | Yes |

No `.env` file is required. Optional experimental backends read
`OPENAI_API_KEY` or `ELEVENLABS_API_KEY` only from the local process
environment. The production Google path uses ADC.

### 5. Verify the installation

```bash
cd ~/src/abr
source .venv/bin/activate
python -m pytest -q
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 100 --no-pager
```

Then complete the hardware and runtime verification in
[docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md).

### Local e-mail configuration

Personal addresses, usernames, and passwords are not stored in the
repository. Mail features read `~/.config/abr/mail.ini` on the Raspberry Pi.
The first invocation of `sudo deploy/install_remote_mail.sh` creates a template
with mode `0600`. Edit the local file:

```ini
[mail]
address = abr-device@example.com
recipient = owner@example.com
username = abr-device@example.com
password = MAIL_APP_PASSWORD
smtp_host = smtp.example.com
smtp_port = 465
imap_host = imap.example.com
imap_port = 993
inbox = INBOX
```

`address` and `username` identify the device account. Remote-maintenance files
and usage reports are sent to `recipient`, and uploads are accepted only from
that exact sender. Real values remain exclusively in this local, untracked
file. For backwards compatibility, installations without `recipient` use the
value of `address`.

Important operational notes:

- `rapidocr` and `onnxruntime` are required for the primary OCR path
- Tesseract remains a fallback and comparison backend
- PaddleOCR is currently not a reliable production path on Raspberry Pi
- automatic summaries use the same Google Cloud credentials as TTS
- `target-pages` is converted at 250 words per text page; `0.5` therefore
  targets 125 words
- Gemini receives a generous technical token budget so internal thinking
  tokens do not truncate the visible answer prematurely
- if the first answer exceeds the word limit by more than ten percent, a
  separate shortening pass is performed
- only a response not terminated by the token limit is stored with
  `generation_complete=true`; legacy summaries without this marker are
  regenerated once on their next use
- `/etc/asound.conf` must expose a `plug` PCM named `default` for
  `hw:CARD=MAX98357A,DEV=0`; otherwise `aplay` may open HDMI and fail with
  `Unknown error 524`

## Quick start

### Manual capture and OCR reference run

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

### Full runtime service on the Raspberry Pi

The runtime may be started directly for short manual tests. Continuous
operation uses the SSH-independent `abr-control-panel.service`; installation,
logs, restart testing, and troubleshooting are documented in
[docs/SYSTEMD_CONTROL_PANEL_SERVICE.md](docs/SYSTEMD_CONTROL_PANEL_SERVICE.md).

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-speed 0.85 \
  --chapter-summary-target-pages 1.5 \
  --book-summary-target-pages 1.5
```

### Separate Neural2-H test

The production Google path remains unchanged: backend `google`, voice
`de-DE-Standard-H`, and still the default when no additional option is given.
Neural2-H is an isolated opt-in path:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-neural2 \
  --page-tts-speed 0.85
```

Return to the production path with `--page-tts-backend google` or omit the
option. `--google-neural2-voice-name` selects a different Neural2 voice; the
default is `de-DE-Neural2-H`.

### Standard-H with enhanced SSML preparation

The optional `google-standard-enhanced` path still uses `de-DE-Standard-H` and
the same Google Cloud TTS backend. Only text preparation differs: paragraphs
and sentences are structured, chapters retain their long pause, and short
headings are moderately emphasised and separated from following text. For
questions, the complete final word is experimentally raised by `+3st`. The
renderer verifies that no spoken words were changed and falls back to the
original SSML preparation if validation fails.

Sentences inside a paragraph receive a `900ms` pause. The last sentence of a
paragraph receives `2000ms` instead; pauses are not added together. Paragraph
boundaries come from OCR `layout_blocks` and are stored as blank lines in
`speak_text`. For already stored pages, a simple line break after `.` or `?`
also acts as a fallback paragraph boundary, including a directly following
closing quotation mark. If a fully quoted dialogue sentence in `"..."`,
`»...«`, or `„...“` is followed by a paragraph break, that boundary is spoken
like a normal sentence boundary: `900ms` instead of `2000ms`. Stored paragraph
data is not changed.

Enable the path with:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-standard-enhanced \
  --page-tts-speed 0.9
```

The unchanged Standard-H path remains available through
`--page-tts-backend google` or by omitting the option.

### Page direction and repeated-page checks

The runtime stores, per book, the page numbers of the most recently accepted
double-page scan:

- if a new scan overlaps those page numbers, it plays
  `system_audio/messages/<language>/repeat_page.wav` and cancels page playback
- if the smallest new page number is below the smallest previously read page,
  it plays `system_audio/messages/<language>/wrong_direction.wav` and cancels playback
- the immediately following scan may pass the condition once; the relevant
  override marker is then cleared
- if the right-side partial result arrives after a warning from the same scan,
  it is not played either
- scans without detected page numbers bypass these two checks

Markers and last-read pages are maintained per book and removed when the book
is deleted. These warnings play directly in the ingest path rather than via
the general asynchronous system-audio queue. The runtime logs their start and
successful completion and reports a missing WAV path explicitly. In the
incremental capture path, the runner waits for the left ingest result; if it
triggers a warning, the foreground job stops before right-side preparation and
OCR. After the warning, the normal `CANCELLED` event returns the runtime to
`IDLE`.

### Long summaries

Before Google TTS, chapter and whole-book summaries are split at complete
sentences when the rendered input would otherwise be too large. Summary chunks
are limited to 900 bytes including SSML; the general Google safety limit is
3800 bytes. Chunks use the same audio queue and play in order, with labels such
as `1/N` and `2/N`. Short summaries remain a single TTS request.

The pre-generated summary announcement and first `bing` play synchronously
before the summary job. Pending heartbeat sounds are discarded after summary
audio is activated, preventing a late `bing` after the summary.

The validity of `book_so_far_summary.json` includes a SHA-256 fingerprint of
the content and modification time of every chapter summary. A previous short
book summary is regenerated when its sources change. Legacy files without a
fingerprint are refreshed once on their next use.

Chapter and book summaries follow the active language profile. German uses
German prompts; English uses U.S. English prompts. Persistent summary files
store `metadata.language`. A cache in another language is regenerated, while
legacy cache files without a language field are treated as German.

### Separate Gemini 2.5 Flash TTS test

Gemini TTS is another isolated opt-in path:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-gemini-flash \
  --page-tts-speed 0.85
```

Defaults for this experimental path:

- model `gemini-2.5-flash-tts`
- voice `Charon`
- a dedicated German audiobook prompt
- plain-text rather than SSML input; the prompt controls pauses and delivery

Optional overrides:

```bash
--google-gemini-flash-voice-name Charon
--google-gemini-flash-prompt "Lies ruhig und natuerlich wie ein Hoerbuchsprecher."
```

Google limits both Gemini TTS text and prompt to 4000 bytes. The backend checks
this limit and reports a clear error instead of silently truncating input.
Return to the production path with `--page-tts-backend google` or omit the
option.

### Offline ingest of an existing OCR report

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/page_ingest_debug.py \
  --library-root library \
  --book-tag-id TESTBOOK \
  --report-path captures/scan_xxx/ocr_text/report.json
```

## Generate system messages

Tool: [hardware/generate_audio_message.py](hardware/generate_audio_message.py)

```bash
python hardware/generate_audio_message.py \
  --ssml \
  --output-root ~/tmp_audio_export/de \
  fehler \
  '<speak>Fehler.<break time="700ms"/>Bitte erneut versuchen.</speak>'
```

Generate new messages outside the repository on the Raspberry Pi. Copy them
to the Mac afterwards and only then place them in the relevant
`system_audio/messages/de/` or `system_audio/messages/en/` directory.

## Important documentation

- [German README](readme_DE.md)
- [docs/LANGUAGE_PROFILES.md](docs/LANGUAGE_PROFILES.md)
- [docs/CONTROL_RUNTIME_ARCHITECTURE.md](docs/CONTROL_RUNTIME_ARCHITECTURE.md)
- [docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md](docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [docs/SOFTWARE_STRUCTURE.md](docs/SOFTWARE_STRUCTURE.md)
- [docs/WIFI_PROFILES.md](docs/WIFI_PROFILES.md)
- [docs/REMOTE_MAINTENANCE_EMAIL.md](docs/REMOTE_MAINTENANCE_EMAIL.md)
- [hardware/README.md](hardware/README.md)
