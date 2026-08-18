# Raspberry Pi Setup

Last reviewed: `2026-08-18`

Deutsche Fassung: [Raspberry-Pi-Setup](../docs_DE/RASPBERRY_PI_SETUP.md)

## Purpose and Target System

This guide describes a reproducible installation of the current ABR system on
a `Raspberry Pi 5`. It replaces the previous chronological setup log;
historical intermediate states and obsolete experiments have been removed.

Verified reference platform:

- 64-bit Debian/Raspberry Pi OS `Trixie` base
- Python `3.13`
- two `Arducam IMX519 16 MP` cameras
- Raspberry Pi Pico as the exclusive NFC gateway
- two PN5180 readers on the Pico; an alternative PN532 Pico path is available
- `MAX98357A` through I²S
- local OCR with RapidOCR
- Google Cloud TTS and Vertex AI/Gemini for summaries
- production runtime as `abr-control-panel.service`

Exact package versions may be newer. On a new installation, perform the
verification at the end of each major section.

## 1. Operating System and Network

`Raspberry Pi OS Lite (64-bit)` is recommended. When writing the SD card:

- set a hostname, for example `abr`
- enable SSH
- create a user account
- configure at least one Wi-Fi network or Ethernet initially

After the first boot:

```bash
ssh <pi-user>@abr.local
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Reconnect and inspect the system:

```bash
cat /etc/os-release
uname -a
df -h
```

## 2. System Packages

```bash
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  python3-picamera2 \
  htop tmux
```

On Trixie, `libopenblas-dev` replaces the unavailable `libatlas-base-dev`.
The current camera test server does not require `python3-opencv`; OpenCV is
installed in the project virtual environment.

Verify:

```bash
python3 --version
git --version
tesseract --version
command -v aplay
command -v espeak-ng
```

## 3. Repository and Python Environment

```bash
mkdir -p ~/src
git clone https://github.com/lhm0/accessible_book_reader.git ~/src/abr
cd ~/src/abr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
```

Optional OCR backends:

```bash
python -m pip install -e ".[ocr-tesseract]"
python -m pip install -e ".[ocr-paddle]"
```

Never copy `.venv` from a Mac or another machine. If an incompatible
environment is present, move it aside and recreate it on the Pi:

```bash
cd ~/src/abr
mv .venv ".venv.incompatible.$(date +%Y%m%d-%H%M%S)"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
```

Verify the software:

```bash
python -c 'import abr, cv2, numpy; print("ABR import OK")'
python -m pytest -q
```

## 4. Boot Configuration for Cameras, UART, and I²S

The repository's `config.txt` is a reference only. Do not replace an existing
`/boot/firmware/config.txt` wholesale. Back it up first:

```bash
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.before-abr
sudo nano /boot/firmware/config.txt
```

The current hardware requires at least these entries in `[all]`:

```text
enable_uart=1
dtparam=i2s=on
dtoverlay=max98357a

camera_auto_detect=0
dtoverlay=imx519,cam0
dtoverlay=imx519,cam1
```

Also configure the header UART:

```bash
sudo raspi-config
```

Under `Interface Options -> Serial Port`:

- serial login shell: `No`
- serial hardware: `Yes`

Then reboot:

```bash
sudo reboot
```

## 5. Verify the Cameras

```bash
rpicam-hello --list-cameras
```

Two IMX519 cameras with indices `0` and `1` should be listed. Their maximum
sensor resolution is `4656x3496`.

The browser test server deliberately uses the system Python because Picamera2
is installed by the OS:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py \
  --camera 0 --port 8000 --width 1920 --height 1080
```

Open `http://abr.local:8000/`. Test camera 1 on port 8001 in the same way. See
[CAMERA_TEST_SERVER.md](CAMERA_TEST_SERVER.md).

The included `calibration/out/cam0_planar.npz` and `cam1_planar.npz` remaps
apply only to the verified mechanical assembly. Regenerate them after changing
a camera, focus, angle, or height.

## 6. Pico NFC Gateway and UART

PN5180 and PN532 readers do not connect directly to the Pi. The Pi
communicates exclusively with the Raspberry Pi Pico over UART:

| Raspberry Pi 5 | Raspberry Pi Pico |
| --- | --- |
| `BCM14 / TXD`, pin 8 | `GP1 / RX` |
| `BCM15 / RXD`, pin 10 | `GP0 / TX` |
| `GND` | `GND` |

Use 3.3 V logic levels only. Complete wiring is documented in
[HARDWARE_GPIO_PLAN.md](HARDWARE_GPIO_PLAN.md). Gateway firmware:

- [PN5180 gateway](../hardware/pn5180_gateway/README.md), the current preferred
  dual-reader path
- [PN532 gateway](../hardware/pn532_gateway/README.md), alternative

ABR defaults to `/dev/ttyAMA0` at `115200 8N1`. Verify it with the shared
client or the compatibility wrapper:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 PING
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 STATUS
```

If access is denied, inspect the device and group membership:

```bash
ls -l /dev/ttyAMA0
groups
```

Changed group membership takes effect only after a new login or reboot.

## 7. MAX98357A and ALSA

Wiring:

```text
Raspberry Pi 5        MAX98357A
5V                    VIN
GND                   GND
BCM18                 BCLK
BCM19                 LRC / LRCLK / WS
BCM21                 DIN
BCM4 (optional)       SD / SD_MODE
SPK+ / SPK-           passive speaker
```

Use a passive `4 ohm / 3 W` or `8 ohm / 1–3 W` speaker. Never connect an
active speaker to `SPK+`/`SPK-`.

Because the runtime starts `aplay` without `-D`, `/etc/asound.conf` must use
the symbolic card name:

```text
pcm.!default {
    type plug
    slave.pcm "hw:CARD=MAX98357A,DEV=0"
}
```

The `plug` layer converts mono WAV files into the format expected by the
hardware path. Do not rely on changing numbers such as `card 2`.

Verify:

```bash
aplay -l
cat /proc/asound/cards
aplay -D default /usr/share/sounds/alsa/Front_Center.wav
```

Explicit comparison:

```bash
aplay -D plughw:CARD=MAX98357A,DEV=0 -vv \
  /usr/share/sounds/alsa/Front_Center.wav
```

For `Unknown error 524`, first check whether the explicit `plughw` command
works and whether `/etc/asound.conf` is correct. Kernel messages:

```bash
journalctl -k -b | grep -Ei 'snd|soc|asoc|i2s|max98357|pcm|dma'
```

## 8. Configure Google Cloud

The production runtime requires Application Default Credentials (`ADC`) for
Google Cloud Text-to-Speech and Vertex AI. Configure a Google Cloud project,
billing, and these APIs:

- `texttospeech.googleapis.com`
- `aiplatform.googleapis.com`

After installing the current Google Cloud CLI for Raspberry Pi OS:

```bash
gcloud services enable \
  texttospeech.googleapis.com \
  aiplatform.googleapis.com \
  --project YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID
```

Credentials remain outside the repository in `~/.config/gcloud/`. Never copy
or commit them. A service account can alternatively be supplied through
Google's standard ADC mechanism.

Verify without printing secret tokens:

```bash
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
gcloud config get-value project
```

The systemd installer sets `HOME` to the service user's home directory so the
same ADC store is available to the service.

## 9. Local Device Configuration and Language

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
.venv/bin/python -m abr.language_config status
```

When missing, the installer creates `~/.config/abr/device.json` with mode
`0600` and German as the default. After installing the production service,
switch with:

```bash
sudo abr-language en
sudo abr-language de
abr-language status
```

The command restarts `abr-control-panel.service`; the selection applies to the
next scan and an active scan is terminated. Books are permanently bound to
the language active on their first scan. See
[LANGUAGE_PROFILES.md](LANGUAGE_PROFILES.md).

## 10. Install the Production Service

First stop any manually started runtime:

```bash
pgrep -af control_panel_service.py
```

Install and verify:

```bash
cd ~/src/abr
sudo deploy/install_control_panel_service.sh
sudo systemd-analyze verify /etc/systemd/system/abr-control-panel.service
systemctl status abr-control-panel.service --no-pager -l
```

The installer derives the user, group, home, repository, and `.venv` locally.
The unit starts the runtime at boot, sets `HOME` for ADC, uses the Pico UART
path, and restarts five seconds after an unexpected exit.

Operations and logs:

```bash
sudo systemctl restart abr-control-panel.service
sudo systemctl stop abr-control-panel.service
journalctl -u abr-control-panel.service -f
journalctl -u abr-control-panel.service -n 200 --no-pager
systemctl show abr-control-panel.service -p MainPID -p NRestarts
```

After a `git pull` containing code changes only:

```bash
cd ~/src/abr
sudo systemctl restart abr-control-panel.service
```

If dependencies or unit templates changed, update the virtual environment or
rerun the installer. See
[SYSTEMD_CONTROL_PANEL_SERVICE.md](SYSTEMD_CONTROL_PANEL_SERVICE.md) for
complete operating and diagnostic instructions.

## 11. Wi-Fi Profiles and Automatic Failover

Wi-Fi credentials remain exclusively in NetworkManager profiles. Add and
inspect profiles interactively:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.wifi_profiles list
python -m abr.wifi_profiles add
```

Configure persistent autoconnect for all stored profiles:

```bash
sudo deploy/install_wifi_autoconnect.sh
```

The current installer does **not** install a permanent
`abr-wifi-autoconnect.service`. It removes an old unit if present and performs
the persistent NetworkManager configuration once with root privileges. This
avoids the former `Insufficient privileges` error.

See [WIFI_PROFILES.md](WIFI_PROFILES.md) for profile creation, safe switching,
and diagnostics.

## 12. Optional E-Mail Remote Maintenance

```bash
cd ~/src/abr
sudo deploy/install_remote_mail.sh
```

The first run creates `~/.config/abr/mail.ini` with mode `0600` and exits so
the file can be completed locally:

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

Run the installer again afterward. Personal addresses and passwords remain
only in this untracked file.

```bash
sudo deploy/install_remote_mail.sh
systemctl status abr-email-upload.timer --no-pager
```

See [REMOTE_MAINTENANCE_EMAIL.md](REMOTE_MAINTENANCE_EMAIL.md) for complete
operating and security details.

## 13. Optional Usage Statistics

Install only after completing the mail configuration:

```bash
cd ~/src/abr
sudo deploy/install_usage_statistics.sh
systemctl status abr-usage-report.timer --no-pager
```

Statistics are stored below `library/`, use reporting periods from 04:00 to
04:00 in `Europe/Berlin`, and send reports through the local mail
configuration. See [USAGE_STATISTICS.md](USAGE_STATISTICS.md) for storage,
delivery, and diagnostic details.

## 14. Complete Verification

```bash
cd ~/src/abr
source .venv/bin/activate
python -m pytest -q
rpicam-hello --list-cameras
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 STATUS
aplay -D default /usr/share/sounds/alsa/Front_Center.wav
abr-language status
systemctl is-active abr-control-panel.service
journalctl -u abr-control-panel.service -n 100 --no-pager
```

This checklist verifies the installation path itself. The final acceptance
test is normal operation through the front panel: identify a book, scan a
spread, hear both pages in order, stop playback, and invoke both summary
buttons while monitoring the service journal for errors.

## Local and Generated Configuration

| Path | Purpose | In repository? |
| --- | --- | --- |
| `/boot/firmware/config.txt` | cameras, UART, and I²S | No |
| `/etc/asound.conf` | ALSA default for MAX98357A | No |
| `~/.config/gcloud/` | Google ADC and project configuration | No |
| `~/.config/abr/device.json` | active book language | No |
| `~/.config/abr/mail.ini` | optional mail credentials | No |
| NetworkManager profiles | Wi-Fi credentials | No |
| `/etc/systemd/system/abr-*` | locally generated units and timers | No |
| `calibration/out/*_planar.npz` | mechanics-specific remaps | reference files included |

No `.env` file is required. Experimental backends read optional API keys only
from the local process environment. The production Google path uses ADC.

## Updating an Existing Installation

After the one-time history cleanup of the public repository, old local
branches may diverge from the new `origin/main`. Back up local changes before
a hard synchronization. If no local changes need to be retained:

```bash
cd ~/src/abr
git fetch origin
git reset --hard origin/main
```

For ordinary later updates:

```bash
cd ~/src/abr
git pull --ff-only
source .venv/bin/activate
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
sudo deploy/install_language_switch.sh
sudo deploy/install_control_panel_service.sh
sudo systemctl restart abr-control-panel.service
```

Optional installers need to be rerun only if their templates or configuration
changed.
