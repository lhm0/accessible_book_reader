# Raspberry Pi Setup

## Zweck

Dieses Dokument dient gleichzeitig als:

- Einrichtungsprotokoll fuer den aktuell verwendeten Raspberry Pi
- reproduzierbarer Setup-Guide fuer spaetere Neuinstallationen
- Grundlage fuer eine spaetere Veroeffentlichung des Projekts

Wichtig:

- Ein Schritt gilt hier erst dann als abgeschlossen, wenn er auf dem Geraet tatsaechlich ausgefuehrt und verifiziert wurde.
- Dieses Dokument trennt deshalb zwischen:
  - `Erledigt`
  - `In Arbeit`
  - `Geplant`

Stand dieses Dokuments:

- Datum: `2026-07-01`
- Projekt: `abr`
- Zielgeraet: `Raspberry Pi 5`

## Aktueller Geraetestand

Bekannt und bestaetigt:

- Es wurde eine neue SD-Karte vorbereitet.
- Der Raspberry Pi bootet.
- SSH-Zugriff funktioniert.
- Aktueller Login:

```bash
ssh <pi-user>@abr.local
```

- Der Raspberry Pi ist als ABR-Basis inzwischen eingerichtet.
- Der Projektpfad, die Python-venv, Google-TTS und die Audioausgabe sind erfolgreich verifiziert.

Noch nicht in diesem Dokument bestaetigt:

- exakte Kernel-Version
- exakte Firmware-/EEPROM-Staende

Aktuell zusaetzlich bestaetigt:

- `RapidOCR` funktioniert auf den aktuellen Testseiten sehr zuverlaessig und ist jetzt der Standardpfad
- `Google Cloud TTS` funktioniert auf dem Pi
- Audioausgabe ueber `MAX98357A` funktioniert
- produktionsnaher Live-Pfad mit `--live-tts-max-chars 700` und `--no-debug-artifacts` funktioniert
- beide `IMX519`-Kameras werden erkannt
- lokaler Kamera-Testserver mit Browser-Livebild funktioniert fuer `cam0` und `cam1`
- feste Entzerrungs-Remaps fuer `cam0` und `cam1` sind erzeugt
- NFC-Pfad laeuft jetzt ueber einen `RP2040`-Gateway-Controller per UART statt ueber direkte PN532-Anbindung am Pi

## Zielbild Fuer Den Pi

Der Raspberry Pi soll den aktuellen ABR-Prototyp reproduzierbar ausfuehren koennen:

- OCR lokal mit `rapidocr`
- Bildvorverarbeitung mit `OpenCV`
- Python-Projektlauf in virtueller Umgebung
- optional cloudbasiertes TTS mit `Google Cloud Text-to-Speech`

## Einrichtungsprotokoll

### 1. OS-Auswahl

Status: `Erledigt`

Entscheidung im Chat:

- empfohlenes System: `Raspberry Pi OS Lite (64-bit)`

Hinweis:

- Die exakte installierte Variante sollte auf dem Pi noch mit `cat /etc/os-release` dokumentiert werden.

### 2. SSH-Zugang

Status: `Erledigt`

Bestaetigter Zugriff:

```bash
ssh <pi-user>@abr.local
```

### 3. Initiales Systemupdate

Status: `Erledigt`

Auszufuehrende Kommandos:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Begruendung:

- Raspberry Pi empfiehlt fuer regulaere Updates `apt update` plus `apt full-upgrade`.
- `rpi-update` wird bewusst nicht fuer den Normalfall verwendet.

Nach dem Reboot erneut verbinden:

```bash
ssh <pi-user>@abr.local
```

### 4. Basis- und Projektpakete

Status: `Erledigt`

Auszufuehrendes Paketset:

```bash
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  htop tmux
```

Zweck der Pakete:

- `git`, `curl`, `ca-certificates`: Grundwerkzeuge fuer Checkout und Downloads
- `build-essential`, `pkg-config`: Build-Hilfen fuer Python-/Native-Abhaengigkeiten
- `python3`, `python3-venv`, `python3-pip`, `python3-dev`: Python-Basis fuer das Projekt
- `tesseract-ocr`, `tesseract-ocr-deu`: optionaler Fallback-/Vergleichspfad fuer OCR
- `libgl1`, `libopenblas-dev`: typische Laufzeit-/Build-Abhaengigkeiten fuer `opencv-python` und numerische Pakete
- `espeak-ng`: lokaler TTS-Fallback
- `alsa-utils`, `pulseaudio-utils`: liefern lokale Audioplayer wie `aplay` und `paplay`
- `htop`, `tmux`: hilfreiche Betriebswerkzeuge fuer SSH-Administration

### 5. Erstpruefung Der Systemwerkzeuge

Status: `Erledigt`

Nach der Paketinstallation ausfuehren:

```bash
python3 --version
pip3 --version
which aplay
which paplay
which espeak-ng
```

Optional fuer den Tesseract-Fallback:

```bash
tesseract --version
```

Diese Befehle sollen spaeter mit ihren echten Ausgaben hier dokumentiert werden.

Dokumentierter Ist-Stand auf dem aktuellen Pi:

`cat /etc/os-release`

```text
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.5
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
```

`python3 --version`

```text
Python 3.13.5
```

`tesseract --version`

```text
tesseract 5.5.0
 leptonica-1.84.1
  libgif 5.2.2 : libjpeg 6b (libjpeg-turbo 2.1.5) : libpng 1.6.48 : libtiff 4.7.0 : zlib 1.3.1 : libwebp 1.5.0 : libopenjp2 2.5.3
 Found NEON
 Found OpenMP 201511
 Found libarchive 3.7.4 zlib/1.3.1 liblzma/5.8.1 bz2lib/1.0.8 liblz4/1.10.0 libzstd/1.5.7
 Found libcurl/8.14.1 OpenSSL/3.5.6 zlib/1.3.1 brotli/1.1.0 zstd/1.5.7 libidn2/2.3.8 libpsl/0.21.2 libssh2/1.11.1 nghttp2/1.64.0 nghttp3/1.8.0 librtmp/2.3 OpenLDAP/2.6.10
```

Vorhandene lokale Audiowerkzeuge:

```text
/usr/bin/aplay
/usr/bin/paplay
/usr/bin/espeak-ng
```

## Reproduzierbarer Minimal-Setup

Wenn ein neuer Raspberry Pi von Grund auf eingerichtet werden soll, ist die bisher definierte Reihenfolge:

1. `Raspberry Pi OS Lite (64-bit)` auf SD-Karte schreiben
2. SSH aktivieren und Netzwerkzugang herstellen
3. per SSH verbinden:

```bash
ssh <pi-user>@abr.local
```

4. System aktualisieren:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

5. erneut per SSH verbinden
6. Basis- und ABR-Pakete installieren:

```bash
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  htop tmux
```

## Optional: RP2040-NFC-Gateway Auf Dem Pi Nutzen

Ein moeglicher NFC-Pfad auf dem Zielgeraet ist:

- `Raspberry Pi 5` <-> `UART` <-> `Raspberry Pi Pico / RP2040`
- `RP2040` <-> `I2C` <-> `1 oder 2 x PN532`

Alternativ ist inzwischen auch folgender Pfad dokumentiert:

- `Raspberry Pi 5` <-> `UART` <-> `Raspberry Pi Pico / RP2040`
- `RP2040` <-> `SPI0` <-> `1 oder 2 x PN5180`

Pi-seitig relevant:

- `GPIO14 / Pin 8` -> Pico `GP1 / RX`
- `GPIO15 / Pin 10` <- Pico `GP0 / TX`
- gemeinsames `GND`

Die Header-UART muss auf dem Pi aktiviert sein:

```bash
sudo raspi-config
```

Dann:

1. `Interface Options`
2. `Serial Port`
3. Login-Shell ueber Serial: `No`
4. Serial-Hardware: `Yes`

Danach rebooten.

Python-Abhaengigkeit fuer den Client:

```bash
cd /pfad/zu/abr
source .venv/bin/activate
pip install ".[nfc-pn532]"
```

Statusabfrage:

```bash
python hardware/pn532_gateway_client.py STATUS
python hardware/pn5180_gateway_client.py STATUS
```

Wenn auf dem konkreten Pi `serial0` nicht auf den Header-UART zeigt, direkt `ttyAMA0` angeben:

```bash
python hardware/pn532_gateway_client.py --device /dev/ttyAMA0 STATUS
python hardware/pn5180_gateway_client.py --device /dev/ttyAMA0 STATUS
```

## Bekannte Abweichung Auf Trixie

Beim ersten Installationsversuch auf dem frisch eingerichteten Pi trat folgender Fehler auf:

```text
Package libatlas-base-dev is not available, but is referred to by another package.
This may mean that the package is missing, has been obsoleted, or
is only available from another source

Error: Package 'libatlas-base-dev' has no installation candidate
```

Interpretation:

- `libatlas-base-dev` war frueher auf Debian-/Raspberry-Pi-OS-Systemen gaengig.
- Auf dem aktuellen `Trixie`-Stand ist dieses Paket im praktischen Setup-Pfad nicht mehr verfuegbar.
- Als aktuelle Alternative verwenden wir `libopenblas-dev`.

Korrigierter Befehl:

```bash
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  htop tmux
```

## Aktueller Einrichtungsstand

Der urspruenglich geplante Pi-Basisaufbau ist inzwischen abgeschlossen:

- `gcloud` / ADC-Nutzung fuer Google-TTS funktioniert
- Projekt liegt unter `~/src/abr`
- Python-venv ist angelegt
- Projektabhaengigkeiten sind installiert
- lokaler OCR-Pfad und Google-TTS-Livepfad sind verifiziert

## Offene Verifikation

Noch sinnvoll nachzutragen:

- Ausgabe von `uname -a`
- verfuegbarer freier Speicher mit `df -h`
- zweiter Kamerapfad an `CAM1`

## Spaetere Erweiterungen Dieses Dokuments

Sobald wir weitergehen, sollte dieses Dokument zusaetzlich enthalten:

- Projekt-Checkout auf dem Pi
- Anlegen der Python-venv
- `pip install -e .`
- `pip install ".[ocr-rapidocr,dev,tts-google]"`
- Google-TTS-Authentifizierung
- erster erfolgreicher ABR-Testlauf
- gemessene Laufzeiten auf dem Pi
- Kamera-Overlay- und Livebild-Testpfad

## Naechster Geplanter Schritt

Der Pi selbst ist als Software- und Audiobasis jetzt weitgehend eingerichtet.

Die fruehere Hardware-Inbetriebnahme ist inzwischen weitgehend erfolgt. Aktueller Folgefokus nach dem erreichten Hardware- und OCR-Stand:

1. Laufzeit des bestehenden `rapidocr`-Pfads optimieren
2. danach Bedienelemente integrieren
3. anschliessend den produktionsnahen Gesamtablauf umsetzen

Wichtiger Hinweis fuer Transfer per `rsync`:

- keine lokale virtuelle Umgebung vom Mac uebernehmen
- `.venv` auf dem Pi immer neu anlegen
- am besten schon beim Transfer ausschliessen:

```bash
rsync -av --progress \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'build' \
  ~/src/abr/ \
  <pi-user>@abr.local:~/src/abr/
```

## Bekannter Fehler Beim Ersten venv-Anlauf

Beim ersten Versuch auf dem Pi trat folgender Fehler auf:

```text
Error: [Errno 2] No such file or directory: '~/src/abr/.venv/bin/python3'
error: externally-managed-environment
```

Wahrscheinliche Ursache:

- das Projekt wurde mitsamt einer bereits auf dem Mac erzeugten `.venv` auf den Pi kopiert
- diese Umgebung enthaelt unpassende Interpreterpfade und ist auf dem Pi nicht gueltig
- nach dem Aktivieren fiel der Aufruf auf das System-Python zurueck, wodurch die Debian-PEP-668-Meldung erschien

Korrektur:

```bash
cd ~/src/abr
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

## Projekt-Setup Auf Dem Pi

### 6. Projektverzeichnis

Status: `Erledigt`

Aktueller Projektpfad auf dem Pi:

```text
~/src/abr
```

### 7. Virtuelle Python-Umgebung

Status: `Erledigt`

Erfolgreich ausgefuehrte Befehle:

```bash
cd ~/src/abr
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 8. Python-Paketinstallation Fuer ABR

Status: `Erledigt`

Erfolgreich ausgefuehrte Befehle:

```bash
pip install -e .
pip install ".[ocr-rapidocr,dev,tts-google]"
pip install ".[ocr-tesseract]"
```

## Historischer Verifikationsschritt

Als naechster grosser Verifikationsschritt wurde der erste lokale OCR-Referenzlauf ohne Cloud-TTS verwendet. Ziel war, die Pi-Installation fuer:

- Python-Projektimport
- OpenCV
- Tesseract
- Reporting

mit einem echten End-to-End-Lauf zu bestaetigen.

Referenzbefehl:

```bash
cd ~/src/abr
source .venv/bin/activate
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/pi_first_text
```

## Kamerainbetriebnahme Auf Dem Pi

### 9a. Verwendetes Kameramodul

Status: `Erledigt`

Aktuell verifizierte erste Kamera:

- `Arducam IMX519 16 MP`
- angeschlossen an `CAM0`

Wichtiger Praxisbefund:

- mit `camera_auto_detect=1` wurde die Kamera nicht erkannt
- `rpicam-hello --list-cameras` lieferte zuerst:

```text
No cameras available!
```

### 9b. Manuelle Kamera-Konfiguration Fuer IMX519 An CAM0

Status: `Erledigt`

Verifizierte Aenderung in `/boot/firmware/config.txt`:

```text
camera_auto_detect=0
dtoverlay=imx519,cam0
```

Interpretation:

- fuer diese `Arducam IMX519` war die automatische Erkennung auf dem aktuellen Pi-Setup nicht ausreichend
- mit manuellem `imx519`-Overlay und explizitem `,cam0` fuer den verwendeten Port wurde die Kamera korrekt erkannt

Danach Reboot:

```bash
sudo reboot
```

### 9c. Kameraverifikation Mit rpicam

Status: `Erledigt`

Verifizierter Test:

```bash
rpicam-hello --list-cameras
```

Ergebnis:

```text
Available cameras
-----------------
0 : imx519 [4656x3496 10-bit RGGB]
    Modes:
      1280x720 @ 80.01 fps
      1920x1080 @ 60.05 fps
      2328x1748 @ 30.00 fps
      3840x2160 @ 18.00 fps
      4656x3496 @ 9.00 fps
```

Wesentliche Erkenntnisse:

- Kameraindex fuer `CAM0` ist aktuell `0`
- maximale Sensoraufloesung: `4656x3496`
- fuer fluessige Vorschau sind `1920x1080` oder `1280x720` deutlich praktischer als Vollaufloesung

### 9d. Python-Umgebung Fuer Kameratests

Status: `Erledigt`

Beim ersten Start des Kamera-Testskripts traten zwei gegenlaeufige Probleme auf:

- in der Projekt-`venv` fehlte `picamera2`
- fuer den ersten Skriptstand waere im System-Python zusaetzlich `cv2` noetig gewesen

Verifizierter Loesungsweg auf dem Pi:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv
```

Spaeterer vereinfachter Projektstand:

- der Kamera-Testserver wurde auf `Picamera2` mit `JpegEncoder` und `FileOutput` umgestellt
- dadurch ist `python3-opencv` fuer den aktuellen Testserver nicht mehr zwingend noetig
- fuer den aktuellen Skriptstand reicht fuer den Kamera-Webtest der Pi-Systempfad mit `python3-picamera2`

Wichtige Projektentscheidung fuer Kameratests:

- Kamera- und Browser-Livebildtests auf dem Pi mit dem System-Python starten
- also bewusst:

```bash
/usr/bin/python3 ...
```

und nicht mit der Projekt-`venv`, solange `Picamera2` dort nicht sauber verfuegbar ist

### 9e. Kamera-Testserver Mit Browser-Livebild

Status: `Erledigt`

Eigenes Skript im Repo:

- [hardware/camera_test_server.py](../hardware/camera_test_server.py)

Kurzdoku:

- [docs/CAMERA_TEST_SERVER.md](../docs/CAMERA_TEST_SERVER.md)

Verifizierter Startbefehl:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py \
  --camera 0 \
  --port 8000 \
  --width 1920 \
  --height 1080
```

Verifizierter Zugriff vom Mac:

```text
http://abr.local:8000/
```

Ergebnis:

- Livebild wird im Browser angezeigt
- damit ist der erste Kamerapfad `Pi -> Picamera2 -> HTTP-Server -> Mac-Browser` erfolgreich verifiziert

### 9f. Zweite Kamera An `CAM1`

Status: `Erledigt`

Fuer den realen Scanneraufbau wurde die Pi-Konfiguration anschliessend auf beide Kameraports erweitert:

```text
camera_auto_detect=0
dtoverlay=imx519,cam0
dtoverlay=imx519,cam1
```

Verifizierter Check:

```bash
rpicam-hello --list-cameras
```

Ergebnis:

- `0 : imx519`
- `1 : imx519`

Interpretation:

- beide `IMX519`-Kameramodule werden am `Raspberry Pi 5` sauber erkannt
- `CAM0` und `CAM1` sind damit als Hardwarebasis verifiziert

### 9g. Fadenkreuz Und Vollaufloesung Fuer Die Kamerajustage

Status: `Erledigt`

Der Kamera-Testserver wurde fuer die mechanische Justage erweitert:

- optionales Fadenkreuz im Browserbild
- Vollaufloesungsbetrieb ohne `--width/--height`
- Snapshots ueber `/snapshot.jpg`

Typische Vollaufloesungsstarts:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --crosshair
/usr/bin/python3 hardware/camera_test_server.py --camera 1 --port 8001 --crosshair
```

### 9h. ChArUco-Kalibrierung Und Gespeicherte Remaps

Status: `Erledigt`

Fuer den aktuellen starren Scanneraufbau wurde der bevorzugte Kalibrierpfad auf ein `160 x 240 mm`-`ChArUco`-Board plus gespeicherte Remaps umgestellt.

Relevante Werkzeuge im Repo:

- [calibration/generate_charuco_board.py](../calibration/generate_charuco_board.py)
- [calibration/calibrate_planar_charuco.py](../calibration/calibrate_planar_charuco.py)
- [calibration/apply_saved_remap.py](../calibration/apply_saved_remap.py)

Aktuelle Kalibrierbilder:

- `calibration/shots/cam0_charuco_01.jpg`
- `calibration/shots/cam1_charuco_01.jpg`

Aktuell gespeicherte Remaps:

- `calibration/out/cam0_planar.npz`
- `calibration/out/cam1_planar.npz`

Interpretation:

- die Kamerajustage gilt momentan als ausreichend gut
- die gespeicherten Remaps sind die aktuelle Arbeitsbasis fuer reale Scannerbilder
- bei Aenderungen an Fokus, Winkel oder mechanischer Hoehe muessen diese Remaps neu erzeugt werden

## Erster Erfolgreicher OCR-Referenzlauf

### 9. End-to-End-Lauf Ohne Cloud-TTS

Status: `Erledigt`

Ausgefuehrter Befehl:

```bash
cd ~/src/abr
source .venv/bin/activate
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/pi_first_text
```

Erzeugte Artefakte:

- `runs/pi_first_text/combined_text.txt`
- `runs/pi_first_text/report.json`
- `runs/pi_first_text/debug/page_1/...`
- `runs/pi_first_text/debug/page_2/...`

Beobachtete Statuszeiten:

```text
[status 16:01:50 +  0.10s] 2 Seite(n) geladen.
[status 16:01:50 +  0.10s] Starte Analyse von left (left.jpg).
[status 16:01:55 +  5.17s] Analyse von left abgeschlossen: 33 OCR-Zeilen, 15 Absatz/Absaetze.
[status 16:01:55 +  5.17s] left: 28 vollstaendige(s) Segment(e) fuer TTS bereit (1582 Zeichen).
[status 16:01:55 +  5.17s] Starte Analyse von right (right.jpg).
[status 16:02:01 + 11.60s] Analyse von right abgeschlossen: 33 OCR-Zeilen, 7 Absatz/Absaetze.
[status 16:02:01 + 11.60s] right: 25 vollstaendige(s) Segment(e) fuer TTS bereit (1794 Zeichen).
[status 16:02:01 + 11.60s] Report geschrieben: runs/pi_first_text/report.json
```

Gemessene Gesamtzeiten:

```text
page_processing_sec: 11.491s
report_write_sec: 0.001s
text_assembly_sec: 0.000s
total_pipeline_sec: 11.598s
```

Qualitative Ersteinschaetzung:

- Der Lauf ist technisch erfolgreich.
- OCR, Layoutanalyse, Reporting und Debug-Artefakte funktionieren auf dem Pi.
- Die Erkennungsqualitaet ist bereits brauchbar bis gut.
- Typische OCR-Artefakte sind weiterhin sichtbar, aber keine grundsaetzlichen Portierungsprobleme.

Beobachtete OCR-Artefakte im Referenzlauf:

- isoliertes `>` als eigener Absatz
- einzelne Satz-/Wortfehler wie `Mundwinke|`
- fehlerhafte Gross-/Kleinschreibung wie `Oder`, `Mit`, `Der`
- unguenstige Zeilentrennung wie `Wir.` / `ken`
- punktuelle Interpunktionsartefakte wie einzelne `.`-Zeilen

Interpretation:

- Die Pi-Portierung ist fuer den OCR-Pfad erfolgreich bestaetigt.
- Die verbleibenden Probleme liegen derzeit eher in OCR-Feinbereinigung und Segmentierung als in der Plattform.

## Google Cloud TTS Auf Dem Pi

Der bevorzugte Zielpfad mit Google Cloud Text-to-Speech wurde auf dem Pi inzwischen erfolgreich verifiziert.

Die dabei relevanten Teilaufgaben waren:

1. `gcloud` CLI auf dem Pi installieren
2. Application Default Credentials (`ADC`) fuer den Pi einrichten
3. Quota-Projekt setzen
4. Google-TTS-Live-Lauf auf dem Pi starten
5. `time_to_first_audio_sec` und `time_to_first_playback_sec` auswerten

Geplanter Referenzlauf:

```bash
cd ~/src/abr
source .venv/bin/activate
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --speak \
  --output-dir runs/pi_google_live_01
```

Optimierter Folgelauf fuer kuerzere Wartezeit vor dem ersten Ton:

```bash
cd ~/src/abr
source .venv/bin/activate
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --speak \
  --live-tts-max-chars 700 \
  --no-debug-artifacts \
  --output-dir runs/pi_google_live_02
```

## Audio-Hardware-Entscheidung

Vor dem Google-TTS-Live-Test wurde die Audio-Hardware-Strategie konkretisiert.

Entscheidung:

- kein Bluetooth-Lautsprecher
- kein HDMI-Audio als Zielpfad
- stattdessen `MAX98357A` ueber `I2S` am GPIO-Header des Raspberry Pi 5

Begruendung:

- fuer ein integriertes Geraet ist `I2S` mechanisch und elektrisch sauberer als USB-Audio
- Raspberry Pi 5 hat keinen analogen 3.5-mm-Audioausgang
- der `MAX98357A` ist fuer Sprachwiedergabe kompakt und ausreichend

### Verdrahtung

Pfad fuer Mono-Ausgabe:

```text
Raspberry Pi 5        MAX98357A
5V                    VIN
GND                   GND
GPIO18                BCLK
GPIO19                LRC / LRCLK / WS
GPIO21                DIN
GPIO4 (optional)      SD / SD_MODE
SPK+                  Lautsprecher +
SPK-                  Lautsprecher -
```

### SD_MODE-Varianten

Es gibt zwei sinnvolle Betriebsarten:

1. Einfachste Hardware:
   - `SD_MODE` fest auf `5V`
   - Software mit `dtoverlay=max98357a,no-sdmode`

2. Sauberere Zielintegration:
   - `SD_MODE` an `GPIO4`
   - Software mit `dtoverlay=max98357a`
   - der Treiber kann den Amp dann aktiv muten/aufwecken

Fuer das Zielgeraet ist Variante 2 die bevorzugte Richtung.

### Lautsprecher

Fuer die Audioausgabe wird ein passiver Lautsprecher benoetigt.

Empfohlene Groessenordnung:

- `4 Ohm / 3 W` oder
- `8 Ohm / 1 W` bis `3 W`

Wichtig:

- kein Aktivlautsprecher an `SPK+` / `SPK-`
- die `MAX98357A`-Ausgaenge gehen direkt an einen passiven Lautsprecher

### Audio-Ausgabe Verifiziert

Status: `Erledigt`

Die `MAX98357A`-basierte I2S-Ausgabe ist verifiziert. Auf einem Pi mit den zwei
HDMI-Soundkarten darf man sich dabei nicht auf die wechselbare ALSA-Kartennummer
verlassen. Die Runtime startet `aplay` ohne explizites `-D` und benoetigt deshalb
ein korrekt konfiguriertes systemweites ALSA-`default`.

Auf dem Referenzsystem waren die Karten zuletzt:

```text
card 0: vc4-hdmi-0
card 1: vc4-hdmi-1
card 2: MAX98357A
```

Diese Nummerierung kann sich aendern. Immer den symbolischen Namen
`MAX98357A` verwenden.

Systemweite Datei `/etc/asound.conf`:

```text
pcm.!default {
    type plug
    slave.pcm "hw:CARD=MAX98357A,DEV=0"
}
```

Der `plug`-Layer ist erforderlich: typische TTS- und Test-WAVs sind mono, der
direkte MAX98357A-ASoC-Hardwarepfad erwartet aber zwei Kanaele. Deshalb ist
`hw:CARD=MAX98357A,DEV=0` kein geeigneter direkter Test fuer eine Mono-Datei;
`plughw:` beziehungsweise der oben definierte `default`-Plug konvertiert Mono
korrekt auf Stereo.

Verbindlicher Test des Produktionsdefaults:

```bash
aplay -D default /usr/share/sounds/alsa/Front_Center.wav
```

Ergebnis:

- Wiedergabe funktioniert
- damit ist die Standardausgabe fuer den Projektpfad ausreichend bestaetigt

Expliziter Gegencheck unabhaengig vom globalen Default:

```bash
aplay -D plughw:CARD=MAX98357A,DEV=0 -vv \
  /usr/share/sounds/alsa/Front_Center.wav
```

Diagnose bei `aplay: audio open error: Unknown error 524`:

1. `aplay -l` und `cat /proc/asound/cards` pruefen.
2. Den expliziten `plughw:CARD=MAX98357A,DEV=0`-Test ausfuehren.
3. Funktioniert dieser, aber `aplay -D default` nicht, zeigt ALSA-`default`
   falsch auf HDMI oder `/etc/asound.conf` fehlt.
4. Die ALSA-Konfiguration gehoert in die Datei; den Block mit
   `pcm.!default` nicht als Bash-Befehle in die Shell kopieren.
5. Scheitert auch der explizite Test, Kernelmeldungen mit
   `journalctl -k -b | grep -Ei 'snd|soc|asoc|i2s|max98357|pcm|dma'` pruefen.

## Google-TTS-Live-Lauf Auf Dem Pi

### 10. Erster Erfolgreicher Live-Lauf Mit Google TTS

Status: `Erledigt`

Referenzlauf:

```bash
cd ~/src/abr
source .venv/bin/activate
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --speak \
  --output-dir runs/pi_google_live_01
```

Wesentliche Messwerte:

- `time_to_first_audio_sec`: `14.19s`
- `page_processing_sec`: `11.91s`
- `total_pipeline_sec`: `227.65s`

Interpretation:

- der Pi-Zielpfad mit Cloud-TTS funktioniert technisch
- die groesste wahrgenommene Wartezeit entstand vor dem ersten Ton durch einen zu grossen ersten TTS-Block

### 11. Optimierter Live-Lauf

Status: `Erledigt`

Ziel:

- frueheren Audio-Start erreichen
- Debug-I/O fuer produktionsnahe Laeufe abschalten
- dabei die natuerliche Prosodie moeglichst erhalten

Getestete Optimierungen:

- kleinere Live-TTS-Bloecke
- `--no-debug-artifacts`
- internes Google-Token-Caching

Zwischenergebnis mit `--live-tts-max-chars 500`:

- `time_to_first_audio_sec`: `9.37s`
- `page_processing_sec`: `11.03s`
- erster Ton rund `4.8s` frueher als im grossen Block-Lauf

Subjektive Beobachtung:

- frueherer Tonstart klar besser
- aber leichte Tendenz zu staerkerer Zerstueckelung der Prosodie

Aktuell bevorzugter Produktionswert:

```bash
--live-tts-max-chars 700
```

Begruendung:

- frueher Tonstart bleibt erhalten
- Hoereindruck wirkte natuerlicher als bei `500`
- deutlich weniger Risiko, die Sprachwirkung durch zu kleine Segmente zu verschlechtern

Empfohlener Pi-Produktionslauf:

```bash
cd ~/src/abr
source .venv/bin/activate
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --speak \
  --live-tts-max-chars 700 \
  --no-debug-artifacts \
  --output-dir runs/pi_google_live_02
```

Qualitative Projektentscheidung nach diesem Lauf:

- `rapidocr` als Standardbackend verwenden
- im naechsten Schritt die Laufzeit des stabilen Pfads optimieren
- danach Bedienelemente und produktionsnahen Ablauf integrieren

## E-Mail-Fernwartung

### 12. Dateiuebertragung Fuer Fernwartung

Status: `Implementiert und auf dem Pi getestet`

Die E-Mail-Fernwartung ergaenzt SSH, wenn kein direkter SCP-/SFTP-Zugriff auf
den Pi moeglich ist. Installation:

```bash
cd ~/src/abr
sudo deploy/install_remote_mail.sh
```

Beim ersten Lauf wird `~/.config/abr/mail.ini` aus einer neutralen Vorlage
angelegt. Dort werden die Daten des eigenen Mailanbieters nur lokal eingetragen:

```ini
[mail]
address = owner@example.com
recipient = owner@example.com
username = owner@example.com
password = PASSWORT_FUER_E_MAIL_PROGRAMME
smtp_host = smtp.example.com
smtp_port = 465
imap_host = imap.example.com
imap_port = 993
inbox = INBOX
```

Nach dem Ausfuellen den Installer erneut starten. Er installiert:

- `/usr/local/bin/email_download`
- `/etc/systemd/system/abr-email-upload.service`
- `/etc/systemd/system/abr-email-upload.timer`

Download-Beispiel:

```bash
cd ~/src/abr/captures/latest/raw
email_download cam0_raw.jpg
```

Upload-Beispiel:

```text
Betreff: save src/abr/
Anhang: test1.txt
Ergebnis: ~/src/abr/test1.txt
```

Der Zielordner muss existieren. Eine vorhandene Datei wird nicht
ueberschrieben. Erfolgreich gespeicherte Upload-Mails werden aus dem
IMAP-Postfach geloescht.

Diagnose:

```bash
systemctl status abr-email-upload.timer
sudo systemctl start abr-email-upload.service
journalctl -u abr-email-upload.service -n 50 --no-pager
```

Die vollstaendige Betriebs- und Sicherheitsdokumentation steht in
`docs/REMOTE_MAINTENANCE_EMAIL.md`.

## Control-Panel als systemd-Dienst

### 13. SSH-unabhaengiger Dauerbetrieb

Der produktive `hardware/control_panel_service.py` darf im Dauerbetrieb nicht
als Vordergrundprozess einer SSH-Sitzung laufen. Eine WLAN-Unterbrechung kann
sonst spaeter zum SSH-Timeout fuehren; beim Abbau der Sitzung wird auch die
daran gekoppelte Runtime beendet, obwohl der Raspberry Pi weiterlaeuft.

Der Dienst `abr-control-panel.service` behebt dies und bietet:

- automatischen Start beim Booten
- Unabhaengigkeit von WLAN und SSH
- Neustart nach unerwartetem Prozessende nach `5s`
- dauerhaftes stdout-/stderr-Log im systemd-Journal
- geordnetes Stoppen ueber `SIGINT`

Die kanonische Unit, Installation, Betriebsbefehle und Diagnose stehen in
[SYSTEMD_CONTROL_PANEL_SERVICE.md](../docs/SYSTEMD_CONTROL_PANEL_SERVICE.md).

Kurzdiagnose:

```bash
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 100 --no-pager
systemctl show abr-control-panel.service -p MainPID -p NRestarts
```
