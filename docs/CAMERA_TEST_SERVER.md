# Camera Test Server

Stand: `2026-07-01`

## Zweck

Dieses Skript startet auf dem `Raspberry Pi 5` einen kleinen HTTP-Server und
arbeitet jetzt in zwei funktionalen Modi:

- `live`: zeigt das Livebild einer angeschlossenen Kamera im Browser
- `review`: zeigt auf einer gemeinsamen Seite immer zwei Bilder untereinander
  an und schaltet oben per Radio-Buttons zwischen vier Quellen um:
  - `raw images`
  - `entzerrte Bilder`
  - `enhanced images`
  - `OCR overlay`

Die frueheren Modi `capture-review`, `ocr-review` und `ocr-words-review`
starten jetzt dieselbe Review-Seite nur mit unterschiedlicher Vorauswahl.

Der aktuell verifizierte Zielpfad fuer den Hardwareaufbau ist:

- `2` Kameras am `Raspberry Pi 5`
- Start eines Testservers pro Kamera auf dem Pi
- Anzeige der Testseiten vom Mac aus ueber das Netzwerk
- Review der letzten Capture-Ergebnisse ueber `captures/latest/`
- Review der letzten OCR-Overlays ueber ein passendes OCR-Debug-Verzeichnis,
  aktuell meist `runs/latest_rapidocr/debug/`

## Datei

- Skript: [hardware/camera_test_server.py](../hardware/camera_test_server.py)

## Vorbedingungen Auf Dem Pi

- mindestens eine Kamera physisch an `CAM0` oder `CAM1` angeschlossen
- `Picamera2` ist auf dem Pi installiert
- die Kamera wird vom Pi erkannt

Fuer `--mode review` gilt stattdessen:

- keine laufende Kamera erforderlich
- keine `Picamera2`-Abhaengigkeit erforderlich
- verwendet standardmaessig:
  - `captures/latest/raw/` fuer `raw images`
  - `captures/latest/case/` fuer `entzerrte Bilder`
  - `captures/latest/debug/page_1|page_2/02_enhanced.png` fuer `enhanced images`
  - `runs/latest/debug/page_1|page_2/06_ocr_overlay.png` oder
    `runs/latest_rapidocr/debug/page_1|page_2/06_ocr_overlay.png` fuer `OCR overlay`

Wichtiger Treiber-/Overlay-Befund fuer die aktuell verwendete Hardware:

- Kamera: `Arducam IMX519 16 MP`
- auf dem aktuellen Pi-Setup war `camera_auto_detect=1` nicht ausreichend
- verifizierte Konfiguration in `/boot/firmware/config.txt`:

```text
camera_auto_detect=0
dtoverlay=imx519,cam0
dtoverlay=imx519,cam1
```

Sinnvolle Kurzpruefung auf dem Pi:

```bash
rpicam-hello --list-cameras
```

Wenn `Picamera2` im System-Python noch fehlt:

```bash
sudo apt update
sudo apt install -y python3-picamera2
```

Wichtig:

- auf Raspberry Pi OS ist `Picamera2` oft ueber das System-Python sauberer verfuegbar als in einer isolierten `venv`
- in der Projekt-`venv` war `picamera2` nicht verfuegbar
- der verifizierte Testpfad ist deshalb bewusst das System-Python:

```bash
/usr/bin/python3 hardware/camera_test_server.py ...
```

Aktueller Implementierungsstand des Testservers:

- der Server nutzt direkt `Picamera2` mit `JpegEncoder` und `FileOutput`
- er re-encodiert die Frames nicht mehr ueber `OpenCV`
- `python3-opencv` ist fuer den aktuellen Kamera-Testserver deshalb nicht mehr erforderlich

## Start Auf Dem Pi

### Live-Modus

Typische Vorschau fuer `CAM0`:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --width 1920 --height 1080
```

Typische Vorschau fuer `CAM1`:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --camera 1 --port 8001 --width 1920 --height 1080
```

Der Server bindet standardmaessig auf `0.0.0.0`, also auf allen Netzwerkschnittstellen.

Beim Start gibt das Skript unter anderem aus:

- Kameramodell
- verwendete Aufloesung
- Bonjour-Link wie `http://abr.local:8000/`

### Review-Modus

Gemeinsame Review-Seite:

```bash
cd ~/src/abr
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010
```

Mit initialer Vorauswahl `raw images`:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --review-source raw
```

Mit initialer Vorauswahl `enhanced images`:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --review-source enhanced
```

Abweichendes Capture-Session-Verzeichnis:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --capture-session-dir captures/latest
```

Abweichendes OCR-Debug-Verzeichnis, z. B. fuer den schlanken RapidOCR-Wrapper:

```bash
/usr/bin/python3 hardware/camera_test_server.py --mode review --port 8010 --ocr-debug-dir runs/latest_rapidocr/debug
```

## Zugriff Vom Mac

Im Browser auf dem Mac oeffnen:

```text
http://abr.local:8000/
http://abr.local:8001/
http://abr.local:8010/
```

Alternativ statt `abr.local` die IP-Adresse des Pi verwenden.

## Verhalten

Standardverhalten des Skripts:

- verwendet Kameraindex `0`
- waehlt ohne Zusatzparameter die groesste gefundene Sensoraufloesung
- streamt das Bild als `MJPEG`
- aktualisiert so schnell, wie Kamera, JPEG-Encoding und Netzwerk es hergeben

Im `review`-Modus:

- liest das Skript bei jeder Statusabfrage den aktuellen Stand unter
  `captures/latest/` und dem jeweils konfigurierten OCR-Debug-Verzeichnis
- zeigt immer genau zwei Bilder untereinander an
- schaltet oben per Radio-Buttons zwischen vier Quellen um:
  - `raw`
  - `rectified`
  - `enhanced`
  - `ocr-overlay`
- verwendet fuer `raw` die unverzerrten Kamerabilder aus `raw/`
- verwendet fuer `rectified` die entzerrten `case/left.jpg` und `right.jpg`
- verwendet fuer `enhanced` die von `capture_double_page` oder
  `enhance_for_ocr.py` erzeugten `02_enhanced.png`
- verwendet fuer `ocr-overlay` die von `run_fallback_pipeline.py` erzeugten
  `06_ocr_overlay.png`; das kann aus `run_fallback_pipeline.py` oder aus
  `hardware/run_rapidocr.py` stammen
- aktualisiert die Browseransicht automatisch, sobald eine neue Aufnahme
  oder ein neuer OCR-Lauf neue Overlays geschrieben hat
- zeigt unterhalb der Bilder fuer die aktuell gewaehlte Quelle auch die
  konkreten linken/rechten Dateipfade und fehlende Dateien an; damit laesst
  sich ein Pfadproblem bei `ocr-overlay` direkt im Browser erkennen

Praktische Empfehlung fuer den ersten Live-Test:

- nicht sofort Vollaufloesung verwenden
- fuer die `IMX519` ist `1920x1080` ein guter Startpunkt fuer fluessige Vorschau
- die vom Pi gemeldete Vollaufloesung `4656x3496` ist fuer MJPEG-Livebild moeglich, aber deutlich langsamer

Zusaetzliche Endpunkte:

- `/snapshot.jpg`
- `/status.json`
- `/review-status.json`

Ein Snapshot laesst sich damit direkt vom Mac abspeichern, z. B.:

```bash
curl http://abr.local:8000/snapshot.jpg -o calibration/shots/cam0_charuco_01.jpg
curl http://abr.local:8001/snapshot.jpg -o calibration/shots/cam1_charuco_01.jpg
```

Fuer die Kamera-Justage kann das Browserbild optional mit einem Fadenkreuz in der Bildmitte ueberlagert werden.
Der Server-Start mit `--crosshair` blendet es initial ein; auf der Seite selbst laesst es sich dann per Checkbox ein- und ausblenden.

## Optionale Parameter

```bash
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --width 2304 --height 1296
```

Wichtige Optionen:

- `--mode`: `live` oder `review`
- die alten Namen `capture-review`, `ocr-review` und `ocr-words-review`
  bleiben als Start-Aliasse fuer `review` erhalten
- `--camera`: Kameraindex, z. B. `0`
- `--host`: Bind-Adresse, Standard `0.0.0.0`
- `--port`: HTTP-Port, Standard `8000`
- `--width` und `--height`: explizite Zielaufloesung statt Vollaufloesung
- `--crosshair`: Fadenkreuz im Browserbild initial einblenden
- `--frame-timeout`: maximale Zeit ohne neues JPEG-Frame, Standard `3.0`
- `--jpeg-quality`: JPEG-Qualitaet, Standard `90`
- `--capture-session-dir`: Capture-Quelle fuer `--mode review`, Standard `captures/latest`
- `--ocr-debug-dir`: OCR-Overlay-Quelle fuer `--mode review`, Standard `runs/latest/debug`;
  fuer den aktuellen Pi-Standardlauf meist `runs/latest_rapidocr/debug`
- `--review-source`: initiale Auswahl `raw`, `rectified`, `enhanced` oder `ocr-overlay`
- `--ocr-stage`: veraltete Restoption aus dem frueheren `ocr-review`-Modus; wird ignoriert

Volle Sensoraufloesung mit Fadenkreuz:

```bash
/usr/bin/python3 hardware/camera_test_server.py --camera 0 --port 8000 --crosshair
/usr/bin/python3 hardware/camera_test_server.py --camera 1 --port 8001 --crosshair
```

Die Vollaufloesung der aktuell verwendeten `IMX519` liegt bei:

- `4656 x 3496`

## Erwartete Nutzung

Der Testserver ist bewusst nur ein Diagnosewerkzeug fuer den Hardwareaufbau:

- Bildausschnitt pruefen
- Schaerfe pruefen
- Belichtung und Licht testen
- Fokus und Verzeichnung beurteilen
- `ChArUco`-Kalibrierbilder als Einzel-Snapshot aufnehmen
- letzte entzerrte Capture-Ergebnisse ohne separaten Datei-Download im Browser vergleichen
- die OCR-Vorverarbeitung je Seite direkt auf den echten Debug-Artefakten im Browser vergleichen
- das backend-unabhaengige OCR-Text-Overlay aus `06_ocr_overlay.png` fuer beide Seiten direkt im Browser vergleichen

Er ist kein Bestandteil der spaeteren produktiven OCR-/TTS-Pipeline.

## Hilfreiche Kamera-Basischecks

Bevor ein Python-Problem gesucht wird, zuerst den nackten Kamera-Stack pruefen:

```bash
rpicam-hello --list-cameras
rpicam-hello -t 15000 -n
```

Hinweis fuer den `Raspberry Pi 5`:

- `rpicam-vid -o test.h264` ist kein guter Basischeck fuer dieses Projekt, wenn nur der H.264-Codec-Pfad scheitert
- fuer die reine Kamerapruefung ist `rpicam-hello -t 15000 -n` aussagekraeftiger
