# Raspberry-Pi-Setup

Stand: `2026-08-18`

English version: [Raspberry Pi Setup](../docs/RASPBERRY_PI_SETUP.md)

## Zweck und Zielsystem

Diese Anleitung beschreibt eine reproduzierbare Neuinstallation des aktuellen
ABR-Systems auf einem `Raspberry Pi 5`. Sie ersetzt das frühere chronologische
Einrichtungsprotokoll; historische Zwischenstände und bereits überholte
Versuchswege wurden entfernt.

Verifizierte Referenzplattform:

- Debian/Raspberry-Pi-OS-Basis `Trixie`, 64 Bit
- Python `3.13`
- zwei `Arducam IMX519 16 MP`
- Raspberry Pi Pico als ausschließliches NFC-Gateway
- zwei PN5180 am Pico; alternativer PN532-Pico-Pfad vorhanden
- `MAX98357A` über I²S
- lokale OCR mit RapidOCR
- Google Cloud TTS und Vertex AI/Gemini für Zusammenfassungen
- produktive Runtime als `abr-control-panel.service`

Die genauen Paketversionen dürfen neuer sein. Bei einer Neuinstallation soll
nach jedem Hauptabschnitt die angegebene Prüfung durchgeführt werden.

## 1. Betriebssystem und Netzwerk

Empfohlen wird `Raspberry Pi OS Lite (64-bit)`. Beim Schreiben der SD-Karte:

- Hostname, beispielsweise `abr`, setzen
- SSH aktivieren
- Benutzerkonto anlegen
- zunächst mindestens ein WLAN oder Ethernet konfigurieren

Nach dem ersten Boot:

```bash
ssh <pi-user>@abr.local
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Nach dem Neustart erneut anmelden und den Stand prüfen:

```bash
cat /etc/os-release
uname -a
df -h
```

## 2. Systempakete

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

`libopenblas-dev` ersetzt auf Trixie das nicht mehr verfügbare
`libatlas-base-dev`. `python3-opencv` ist für den aktuellen Kamera-Testserver
nicht erforderlich; OpenCV wird in der Projekt-venv installiert.

Prüfung:

```bash
python3 --version
git --version
tesseract --version
command -v aplay
command -v espeak-ng
```

## 3. Repository und Python-Umgebung

```bash
mkdir -p ~/src
git clone https://github.com/lhm0/accessible_book_reader.git ~/src/abr
cd ~/src/abr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
```

Optionale OCR-Backends:

```bash
python -m pip install -e ".[ocr-tesseract]"
python -m pip install -e ".[ocr-paddle]"
```

Die `.venv` darf nicht von einem Mac oder einem anderen Rechner kopiert
werden. Ist versehentlich eine fremde Umgebung vorhanden, diese zunächst
beiseitelegen und auf dem Pi neu erzeugen:

```bash
cd ~/src/abr
mv .venv ".venv.incompatible.$(date +%Y%m%d-%H%M%S)"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
```

Softwareprüfung:

```bash
python -c 'import abr, cv2, numpy; print("ABR import OK")'
python -m pytest -q
```

## 4. Boot-Konfiguration für Kamera, UART und I²S

Die Repository-Datei `config.txt` ist nur eine Referenz und darf eine
bestehende `/boot/firmware/config.txt` nicht vollständig ersetzen. Vor einer
Änderung eine Sicherung anlegen:

```bash
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.before-abr
sudo nano /boot/firmware/config.txt
```

Im Abschnitt `[all]` werden für den aktuellen Aufbau mindestens diese Einträge
benötigt:

```text
enable_uart=1
dtparam=i2s=on
dtoverlay=max98357a

camera_auto_detect=0
dtoverlay=imx519,cam0
dtoverlay=imx519,cam1
```

Für den Header-UART zusätzlich über `raspi-config` sicherstellen:

```bash
sudo raspi-config
```

Unter `Interface Options -> Serial Port`:

- Login-Shell über Serial: `No`
- Serial-Hardware: `Yes`

Danach neu starten:

```bash
sudo reboot
```

## 5. Kameras prüfen

```bash
rpicam-hello --list-cameras
```

Erwartet werden zwei IMX519 mit den Indizes `0` und `1`. Die maximale
Sensorauflösung ist `4656x3496`.

Der Browser-Testserver verwendet bewusst das System-Python, weil Picamera2
über das OS installiert ist:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py \
  --camera 0 --port 8000 --width 1920 --height 1080
```

Im Browser `http://abr.local:8000/` öffnen. Kamera 1 kann analog auf Port 8001
getestet werden. Details:
[CAMERA_TEST_SERVER.md](CAMERA_TEST_SERVER.md).

Die mitgelieferten Remaps
`calibration/out/cam0_planar.npz` und `cam1_planar.npz` gelten nur für den
verifizierten mechanischen Aufbau. Nach Änderungen an Kamera, Fokus, Winkel
oder Höhe müssen sie neu erzeugt werden.

## 6. Pico-NFC-Gateway und UART

PN5180 und PN532 werden nicht direkt mit dem Pi verbunden. Der Pi kommuniziert
ausschließlich per UART mit dem Raspberry Pi Pico:

| Raspberry Pi 5 | Raspberry Pi Pico |
| --- | --- |
| `BCM14 / TXD`, Pin 8 | `GP1 / RX` |
| `BCM15 / RXD`, Pin 10 | `GP0 / TX` |
| `GND` | `GND` |

Nur 3,3-V-Pegel verwenden. Die vollständige Verdrahtung steht in
[HARDWARE_GPIO_PLAN.md](HARDWARE_GPIO_PLAN.md). Gateway-Firmware:

- [PN5180-Gateway](../hardware/pn5180_gateway/README.md), aktueller
  bevorzugter Zwei-Reader-Pfad
- [PN532-Gateway](../hardware/pn532_gateway/README.md), Alternative

Auf dem Pi verwendet ABR standardmäßig `/dev/ttyAMA0` mit `115200 8N1`.
Prüfung mit dem gemeinsamen Client beziehungsweise den Kompatibilitäts-
Wrappern:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 PING
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 STATUS
```

Falls `Permission denied` erscheint, Gruppen und Gerätezugriff prüfen:

```bash
ls -l /dev/ttyAMA0
groups
```

Eine geänderte Gruppenzugehörigkeit wird erst nach einer neuen Anmeldung oder
einem Neustart wirksam.

## 7. MAX98357A und ALSA

Verdrahtung:

```text
Raspberry Pi 5        MAX98357A
5V                    VIN
GND                   GND
BCM18                 BCLK
BCM19                 LRC / LRCLK / WS
BCM21                 DIN
BCM4 (optional)       SD / SD_MODE
SPK+ / SPK-           passiver Lautsprecher
```

Empfohlen ist ein passiver Lautsprecher mit `4 Ohm / 3 W` oder
`8 Ohm / 1–3 W`. Niemals einen Aktivlautsprecher an `SPK+`/`SPK-` anschließen.

Da `aplay` in der Runtime ohne `-D` gestartet wird, muss
`/etc/asound.conf` den symbolischen Kartennamen verwenden:

```text
pcm.!default {
    type plug
    slave.pcm "hw:CARD=MAX98357A,DEV=0"
}
```

Der `plug`-Layer konvertiert mono erzeugte WAV-Dateien in das vom
Hardwarepfad erwartete Format. Nicht auf wechselnde Nummern wie `card 2`
verlassen.

Prüfung:

```bash
aplay -l
cat /proc/asound/cards
aplay -D default /usr/share/sounds/alsa/Front_Center.wav
```

Expliziter Gegencheck:

```bash
aplay -D plughw:CARD=MAX98357A,DEV=0 -vv \
  /usr/share/sounds/alsa/Front_Center.wav
```

Bei `Unknown error 524` zuerst prüfen, ob der explizite `plughw`-Test
funktioniert und `/etc/asound.conf` korrekt ist. Kernelmeldungen:

```bash
journalctl -k -b | grep -Ei 'snd|soc|asoc|i2s|max98357|pcm|dma'
```

## 8. Google Cloud konfigurieren

Die produktive Runtime benötigt Application Default Credentials (`ADC`) für
Google Cloud Text-to-Speech und Vertex AI. Google-Cloud-Projekt, Abrechnung
und folgende APIs müssen eingerichtet sein:

- `texttospeech.googleapis.com`
- `aiplatform.googleapis.com`

Nach Installation der aktuellen Google Cloud CLI für Raspberry Pi OS:

```bash
gcloud services enable \
  texttospeech.googleapis.com \
  aiplatform.googleapis.com \
  --project YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID
```

Die Anmeldedaten liegen außerhalb des Repositorys unter `~/.config/gcloud/`.
Sie dürfen niemals ins Projekt kopiert oder committet werden. Alternativ ist
ein Service Account über Googles regulären ADC-Mechanismus möglich.

Prüfung ohne Ausgabe geheimer Token:

```bash
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
gcloud config get-value project
```

Der systemd-Installer setzt `HOME` auf das Home-Verzeichnis des
Dienstbenutzers, damit derselbe ADC-Speicher gefunden wird.

## 9. Lokale Gerätekonfiguration und Sprache

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
.venv/bin/python -m abr.language_config status
```

Der Installer erzeugt bei Bedarf `~/.config/abr/device.json` mit Modus `0600`
und deutschem Default. Nach Installation des Produktionsdienstes kann mit den folgenden Befehlen
umgeschaltet werden:

```bash
sudo abr-language en
sudo abr-language de
abr-language status
```

Der Wechsel startet `abr-control-panel.service` neu und gilt ab dem nächsten
Scan. Ein laufender Scan wird dabei beendet. Bücher sind dauerhaft an die beim
ersten Scan aktive Sprache gebunden. Details:
[LANGUAGE_PROFILES.md](LANGUAGE_PROFILES.md).

## 10. Produktionsdienst installieren

Vorher eine eventuell manuell gestartete Runtime beenden:

```bash
pgrep -af control_panel_service.py
```

Dann installieren:

```bash
cd ~/src/abr
sudo deploy/install_control_panel_service.sh
sudo systemd-analyze verify /etc/systemd/system/abr-control-panel.service
systemctl status abr-control-panel.service --no-pager -l
```

Der Installer ermittelt Benutzer, Gruppe, Home, Repository und `.venv`
lokal. Die Unit startet die Runtime beim Boot, setzt `HOME` für ADC, verwendet
den Pico-UART-Pfad und startet nach unerwartetem Ende nach fünf Sekunden neu.

Betrieb und Log:

```bash
sudo systemctl restart abr-control-panel.service
sudo systemctl stop abr-control-panel.service
journalctl -u abr-control-panel.service -f
journalctl -u abr-control-panel.service -n 200 --no-pager
systemctl show abr-control-panel.service -p MainPID -p NRestarts
```

Nach einem `git pull` genügt bei reinen Codeänderungen:

```bash
cd ~/src/abr
sudo systemctl restart abr-control-panel.service
```

Wurden Abhängigkeiten oder Unit-Vorlagen geändert, stattdessen die venv
aktualisieren beziehungsweise den Installer erneut ausführen. Weitere Details
stehen derzeit in der deutschen
[SYSTEMD_CONTROL_PANEL_SERVICE.md](SYSTEMD_CONTROL_PANEL_SERVICE.md).

## 11. WLAN-Profile und automatisches Failover

WLAN-Zugangsdaten bleiben ausschließlich in NetworkManager-Profilen. Profile
interaktiv anlegen und prüfen:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.wifi_profiles list
python -m abr.wifi_profiles add
```

Autoconnect persistent für alle gespeicherten Profile konfigurieren:

```bash
sudo deploy/install_wifi_autoconnect.sh
```

Wichtig: Der aktuelle Installer installiert **keinen** dauerhaften
`abr-wifi-autoconnect.service`. Er entfernt eine alte Unit gegebenenfalls und
führt die persistente NetworkManager-Konfiguration einmal mit Root-Rechten
aus. Dadurch wird der frühere Fehler `Insufficient privileges` vermieden.

Details stehen derzeit in der deutschen
[WIFI_PROFILES.md](WIFI_PROFILES.md).

## 12. Optionale E-Mail-Fernwartung

```bash
cd ~/src/abr
sudo deploy/install_remote_mail.sh
```

Der erste Lauf erzeugt `~/.config/abr/mail.ini` mit Modus `0600` und beendet
sich, damit die Datei lokal ausgefüllt werden kann:

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

Danach den Installer erneut starten. Persönliche Adressen und Passwörter
bleiben ausschließlich in dieser nicht versionierten Datei.

```bash
sudo deploy/install_remote_mail.sh
systemctl status abr-email-upload.timer --no-pager
```

Details stehen derzeit in der deutschen
[REMOTE_MAINTENANCE_EMAIL.md](REMOTE_MAINTENANCE_EMAIL.md).

## 13. Optionale Nutzungsstatistik

Erst nach vollständiger Mail-Konfiguration installieren:

```bash
cd ~/src/abr
sudo deploy/install_usage_statistics.sh
systemctl status abr-usage-report.timer --no-pager
```

Die Statistik liegt unterhalb von `library/`, verwendet Zeiträume von 04:00
bis 04:00 Uhr in `Europe/Berlin` und versendet Berichte über die lokale
Mail-Konfiguration. Details stehen derzeit in der deutschen
[USAGE_STATISTICS.md](USAGE_STATISTICS.md).

## 14. Vollständige Prüfung

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

Diese Prüfliste verifiziert den Installationspfad. Der abschließende
Abnahmetest erfolgt über das Bedienpanel: Buch erkennen, eine Doppelseite
scannen, beide Seiten in richtiger Reihenfolge hören, die Wiedergabe stoppen
und beide Zusammenfassungstasten auslösen. Dabei das Dienstjournal auf Fehler
beobachten.

## Lokale und generierte Konfigurationen

| Pfad | Zweck | Im Repository? |
| --- | --- | --- |
| `/boot/firmware/config.txt` | Kamera, UART und I²S | Nein |
| `/etc/asound.conf` | ALSA-Default für MAX98357A | Nein |
| `~/.config/gcloud/` | Google ADC und Projektkonfiguration | Nein |
| `~/.config/abr/device.json` | aktive Buchsprache | Nein |
| `~/.config/abr/mail.ini` | optionale Mail-Zugangsdaten | Nein |
| NetworkManager-Profile | WLAN-Zugangsdaten | Nein |
| `/etc/systemd/system/abr-*` | lokal erzeugte Units und Timer | Nein |
| `calibration/out/*_planar.npz` | mechanikspezifische Remaps | Referenzdateien enthalten |

Eine `.env`-Datei ist nicht erforderlich. Experimentelle Backends lesen
optionale API-Schlüssel nur aus der lokalen Prozessumgebung. Der produktive
Google-Pfad verwendet ADC.

## Aktualisieren einer bestehenden Installation

Nach der einmaligen Historienbereinigung des öffentlichen Repositorys können
alte lokale Branches vom neuen `origin/main` abweichen. Vor einem harten
Abgleich eigene lokale Änderungen sichern. Wenn keine lokalen Änderungen
erhalten werden müssen:

```bash
cd ~/src/abr
git fetch origin
git reset --hard origin/main
```

Für normale spätere Aktualisierungen:

```bash
cd ~/src/abr
git pull --ff-only
source .venv/bin/activate
python -m pip install -e ".[ocr-rapidocr,dev,tts-google,nfc-pn532]"
sudo deploy/install_language_switch.sh
sudo deploy/install_control_panel_service.sh
sudo systemctl restart abr-control-panel.service
```

Optionale Installer müssen nur erneut laufen, wenn ihre Vorlagen oder
Konfiguration geändert wurden.
