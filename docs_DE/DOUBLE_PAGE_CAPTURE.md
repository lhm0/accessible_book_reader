# Double Page Capture

Stand: `2026-08-19`

## Zweck

Dieses Werkzeug ist der erste produktive Adapter zwischen den realen Pi-Kameras
und der bestehenden OCR-/TTS-Pipeline.

Es erledigt genau `Sprint 1`:

- zwei reale Kamerabilder aufnehmen
- die vorhandenen Remaps automatisch anwenden
- einen standardisierten `case`-Ordner mit `left.jpg` und `right.jpg` erzeugen
- direkt danach einen OCR-Ordner mit `left.png`, `right.png` und `manifest.json` erzeugen
- direkt danach die OCR-Vorverarbeitungsbilder unter `debug/page_1` und `page_2` erzeugen
- den zugeordneten LED-Kanal je Seite nur waehrend der jeweiligen Aufnahme einschalten

Fuer die aktuelle Debug-Phase gibt es zusaetzlich einen einfachen Rohbildmodus:

- Aufnahme nur der beiden Rohbilder
- standardmaessig in der Aufloesung der gespeicherten Remap-Datei
- stabile Ablage unter `captures/latest/raw/` fuer den schnellen Download auf den Mac

Der aktuell bevorzugte OCR-Pfad laeuft danach auf dem erzeugten `ocr`-Ordner
ueber `hardware/run_rapidocr.py`.

Die reine OCR-Vorverarbeitung ist jetzt ausserdem als eigenes Werkzeug
verfuegbar und wird intern von `capture_double_page` genutzt. `run_fallback_pipeline.py`
verarbeitet nur noch vorbereitete OCR-Bilder; fuer schnelle Pi-Laeufe ist
aktuell aber der schlanke Wrapper `hardware/run_rapidocr.py` bevorzugt.

Wichtig fuer den produktiven Frontpanel-Pfad:

- `capture_double_page.py` nimmt zunaechst mit der normalen Zuordnung
  Kamera 0 nach `case/left.jpg` und Kamera 1 nach `case/right.jpg` auf
- nach den Aufnahmen holt die Runtime das Ergebnis der zuvor gestarteten
  PN5180-Abfrage zur Buchidentifikation ab; die Readerposition wird nicht fuer
  die Seitenorientierung verwendet
- die Runtime bereitet `case/left.jpg` im Speicher vor, sucht drei lange
  Textzeilen und entscheidet mit dem RapidOCR-Winkelklassifikator zwischen
  aufrecht und kopfstehend
- bei aufrechtem Text bleiben die beiden `case`-Dateien zugeordnet; bei
  kopfstehendem Text werden `case/left.jpg` und `case/right.jpg` vertauscht
- anschliessend dreht die Runtime `case/right.jpg` einmalig um `180` Grad
- die gemeinsame OCR-Vorverarbeitung dreht im NFC-Runtime-Pfad danach keine
  Seite erneut
- zuverlaessige Ergebnisse aktualisieren den buchweisen Merker; bei leeren,
  textarmen oder uneindeutigen Seiten wird die zuletzt gespeicherte
  Orientierung verwendet

## Dateien

- Modul: [abr/hardware/double_page_capture.py](../abr/hardware/double_page_capture.py)
- Wrapper: [hardware/capture_double_page.py](../hardware/capture_double_page.py)
- gemeinsamer Vorverarbeitungsmodulpfad: [abr/preprocessing/enhance_for_ocr.py](../abr/preprocessing/enhance_for_ocr.py)
- CLI-Wrapper fuer isolierte Vorverarbeitung: [hardware/enhance_for_ocr.py](../hardware/enhance_for_ocr.py)
- schlanker RapidOCR-Wrapper: [hardware/run_rapidocr.py](../hardware/run_rapidocr.py)

## Voraussetzungen Auf Dem Pi

- beide Kameras werden von `rpicam-hello --list-cameras` erkannt
- `rpicam-still` ist verfuegbar
- die Projekt-`venv` ist installiert
- `opencv-contrib-python` und `numpy` sind in der `venv` vorhanden
- die Remaps liegen unter:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`

Wichtig:

- dieses Werkzeug braucht fuer die Aufnahme **nicht** `Picamera2`
- es ruft fuer die Aufnahme `rpicam-still` auf
- ohne explizite Belichtungszeit bleibt `rpicam-still` im normalen Automatikpfad
- ohne expliziten `--gain` bleibt auch die Gain-Regelung im normalen Automatikpfad
- die Entzerrung laeuft danach ueber das bestehende
  [calibration/apply_saved_remap.py](../calibration/apply_saved_remap.py)

## Standardausgabe

Ein Lauf erzeugt unter `captures/<session-name>/`:

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

Bedeutung:

- `raw/`: rohe Kamerabilder direkt aus `rpicam-still`
- `rectified/`: mit Remap entzerrte Bilder
- `case/`: entzerrte, noch nicht OCR-finalisierte Seiten
- `ocr/`: finale Eingabe fuer `python hardware/run_rapidocr.py --ocr-dir ...`
- `debug/`: nachvollziehbare OCR-Vorverarbeitung fuer beide Seiten
- `metadata.json`: verwendete Kameraindizes, Remaps, aufgerufene Kommandos und
  Laufzeitmetriken

Zusaetzlich wird immer ein stabiler Spiegel des letzten Laufs unter
`captures/latest/` erzeugt.

Dieser Pfad ist auch die Standardquelle fuer den neuen Review-Modus des
Kamera-Testservers.

## Typischer Lauf Auf Dem Pi

Aus der Projekt-`venv`:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
```

Das Werkzeug verwendet standardmaessig:

- linke Seite: Kamera `0`
- rechte Seite: Kamera `1`
- `LED-left` an `BCM12` waehrend der linken Aufnahme
- `LED-right` an `BCM13` waehrend der rechten Aufnahme
- Remaps:
  - `calibration/out/cam0_planar.npz`
  - `calibration/out/cam1_planar.npz`

Die Session bekommt automatisch einen Zeitstempelnamen wie
`scan_20260626_153000`.

Aktuell gemessener Pi-Lauf vom `2026-07-01` fuer diesen Modus:

- Capture gesamt: ca. `3.85s`
- Rectify gesamt: ca. `3.86s`
- OCR-Vorverarbeitung gesamt mit `--no-denoise`: ca. `2.77s`
- gesamter Capture-Pfad bis `ocr/*.png`: ca. `10.9s`

Vergleich:

- derselbe Vorverarbeitungsblock lag mit aktiviertem De-Noising zuvor bei
  ca. `15.5s`
- `--no-denoise` ist deshalb im Moment die bevorzugte Einstellung

## Schrittweiser Rohbild-Test

Fuer die aktuelle Bildqualitaetspruefung solltest du zuerst nur Rohbilder
aufnehmen:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.hardware.double_page_capture --raw-only
```

Wichtig:

- ohne `--width/--height` verwendet das Werkzeug jetzt standardmaessig die in
  der jeweiligen Remap gespeicherte Kalibrieraufloesung
- fuer den aktuellen Aufbau sollte das der Vollaufloesungspfad sein
- die Bilder liegen danach unter:
  - `captures/latest/raw/cam0_raw.jpg`
  - `captures/latest/raw/cam1_raw.jpg`

Diese beiden Dateien sind der bevorzugte erste Downloadpfad zum Mac.

## Schrittweiser Rectify-Test

Wenn die Rohbilder gut aussehen, folgt als naechster Schritt die Entzerrung der
bereits aufgenommenen Bilder, ohne erneut zu capturen:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m abr.hardware.double_page_rectify
```

Alternativ ueber den Wrapper:

```bash
python hardware/rectify_double_page.py
```

Standardpfad:

- liest aus `captures/latest/raw/`
- schreibt nach:
  - `captures/latest/rectified/`
  - `captures/latest/case/`
  - `captures/latest/ocr/`
  - `captures/latest/debug/`

Erwartete Dateien:

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

Damit kannst du die entzerrten Bilder wieder sehr einfach auf den Mac ziehen.

Wenn eine Seite nach der Entzerrung auf dem Kopf steht, kannst du pro Seite
eine feste Nachrotation angeben.

Typischer Fall fuer den aktuellen Aufbau:

```bash
python -m abr.hardware.double_page_rectify --right-rotate 180
```

Dann wird nur die rechte Seite nach der Entzerrung um `180` Grad gedreht,
bevor `case/right.jpg` geschrieben wird.

Dieser manuelle Parameter ist fuer isolierte Capture-/Rectify-Tests gedacht.
Im produktiven Frontpanel-Pfad wird die rechte Seitendatei nach der
OCR-basierten Zuordnung automatisch gedreht.

## Aktueller Folgeaufruf

Nach einem erfolgreichen Capture ist der derzeit bevorzugte OCR-Lauf:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

Wichtig fuer diesen isolierten Wrapper-Aufruf:

- die zusaetzliche Orientierungserkennung bleibt als Option im Wrapper
  vorhanden
- sie ist aktuell aber **nicht** Teil des bevorzugten Standardpfads
- Grund: sie kostet derzeit mehrere Sekunden pro Seite und soll spaeter separat
  erneut optimiert werden

Dies beschreibt nicht die Orientierungssonde des produktiven
Frontpanel-Pfads. Die Runtime klassifiziert einmalig drei Textzeilen vor der
Vorbereitung und Erkennung beider Seiten; dadurch wird keine komplette Seite
doppelt per OCR verarbeitet.

## Wichtige Optionen

Fester Session-Name:

```bash
python hardware/capture_double_page.py --session-name first_book_scan
```

Abweichende Kamera-Zuordnung:

```bash
python hardware/capture_double_page.py --left-camera 1 --right-camera 0
```

Abweichende Remaps:

```bash
python hardware/capture_double_page.py \
  --left-remap calibration/out/cam1_planar.npz \
  --right-remap calibration/out/cam0_planar.npz
```

Hoehere JPEG-Qualitaet oder laengerer Timeout:

```bash
python hardware/capture_double_page.py \
  --jpeg-quality 98 \
  --timeout-ms 2000
```

Gemeinsame manuelle Belichtungszeit fuer beide Kameras:

```bash
python hardware/capture_double_page.py \
  --shutter-us 8000
```

Hinweis:

- `--shutter-us` setzt die Belichtungszeit in Mikrosekunden fuer beide Seiten
- ohne `--shutter-us` bleibt die bisherige automatische Belichtung aktiv

Gemeinsamer manueller Gain fuer beide Kameras:

```bash
python hardware/capture_double_page.py \
  --gain 1.5
```

Vollstaendig manuelle Basis fuer beide Kameras:

```bash
python hardware/capture_double_page.py \
  --shutter-us 8000 \
  --gain 1.5
```

Hinweis:

- `--gain` setzt den analogen Gain fuer beide Seiten
- ohne `--gain` bleibt die bisherige automatische Gain-Regelung aktiv

Isolierte OCR-Vorverarbeitung auf einen bereits vorhandenen `case`-Ordner:

```bash
python hardware/enhance_for_ocr.py \
  --case-dir captures/latest/case \
  --ocr-dir captures/latest/ocr \
  --debug-dir captures/latest/debug
```

Das ist derselbe Vorverarbeitungspfad, den auch `capture_double_page` intern
nutzt.

Nur Rohbilder ohne Entzerrung und Case-Erzeugung:

```bash
python -m abr.hardware.double_page_capture --raw-only
```

Bestimmten Session-Ordner statt `captures/latest/` entzerren:

```bash
python -m abr.hardware.double_page_rectify --session-dir captures/scan_20260626_184412
```

## Weiterer Pipeline-Lauf

Nach erfolgreicher Aufnahme gibst du den erzeugten `ocr`-Ordner in die
bestehende OCR-/TTS-Pipeline.

Beispiel fuer den vollen Fallback-Pfad:

```bash
python run_fallback_pipeline.py \
  --case-dir captures/scan_20260626_153000/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/scan_20260626_153000
```

Fuer einen direkten OCR-Vergleich kann derselbe vorbereitete `ocr`-Ordner
auch mit Tesseract ausgewertet werden:

```bash
python run_fallback_pipeline.py \
  --case-dir captures/scan_20260626_153000/ocr \
  --ocr-backend tesseract \
  --output-dir runs/scan_20260626_153000_tesseract
```

Oder mit Live-TTS:

```bash
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
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

## Testziel Fuer Sprint 1

`Sprint 1` ist erfolgreich, wenn:

- `hardware/capture_double_page.py` zwei Rohbilder erzeugt
- beide Rohbilder automatisch entzerrt werden
- `case/left.jpg` und `case/right.jpg` entstehen
- `ocr/left.png` und `ocr/right.png` entstehen
- `python run_fallback_pipeline.py --case-dir ...` auf diesem `ocr`-Ordner laeuft
