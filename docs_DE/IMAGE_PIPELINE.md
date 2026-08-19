# Image Pipeline

Stand: `2026-08-19`

## Ziel

Dieses Dokument definiert verbindlich, was in welchem Schritt mit den
Bildern passiert und welcher Pfad aktuell fuer den Pi-Scanner bevorzugt ist.

Die Trennung ist jetzt:

- `capture_double_page`: aufnehmen, entzerren, OCR-Bilder vorbereiten
- `enhance_for_ocr`: isolierte Bildverbesserung fuer vorhandene `case`-Bilder
- `run_rapidocr.py`: schlanker OCR-Lauf fuer `ocr/left.png` und `ocr/right.png`
- `run_fallback_pipeline.py`: voller Vergleichs- und TTS-Pfad, aber aktuell nicht der
  bevorzugte Laufzeitpfad

`run_fallback_pipeline.py` macht **keine** Bildoptimierung mehr.

Wichtig zur Einordnung:

- der aktuelle Produktpfad laeuft ueber `hardware/control_panel_service.py`
- dort werden beide Seiten zuerst aufgenommen und danach links vor rechts
  verarbeitet
- `capture_double_page.py` laeuft in diesem Pfad mit `--skip-enhance`
- vor der seitenweisen Vorbereitung bereitet die Runtime das linke rohe
  `case`-Bild im Speicher vor und klassifiziert drei erkannte Textzeilen als
  `0` oder `180` Grad
- die daraus folgende gemeinsame Seitenzuordnung wird genau einmal
  angewendet; danach passiert die OCR-Bildvorbereitung einzeln pro Seite

## Manueller Referenzpfad auf dem Pi

Der weiterhin wichtige manuelle Referenzpfad auf dem Pi ist:

1. `python hardware/capture_double_page.py --no-denoise`
2. `python hardware/run_rapidocr.py --ocr-dir captures/latest/ocr --output-dir runs/latest_rapidocr --orientation-mode off --overlay`

Begruendung fuer diesen isolierten manuellen Pfad:

- `--no-denoise` spart gegenueber dem frueheren Vorverarbeitungspfad grob
  `12-13s` pro Doppelseite
- der schlanke RapidOCR-Wrapper schreibt frueh `left.txt` und danach `right.txt`
- der aeltere vollstaendige Orientierungvergleich des Wrappers ist zu teuer
  und wird deshalb nicht als Standard verwendet

Der produktive Frontpanel-Pfad arbeitet anders: Er verwendet einmal pro
Doppelseite den schnellen RapidOCR-Winkelklassifikator auf drei Textzeilen vor
der normalen OCR. Ein zuverlaessiges Ergebnis wird buchweise gespeichert; bei
textarmen Seiten greift die Runtime auf diesen Merker zurueck.

Gemessener Pi-Stand vom `2026-07-01`:

- `capture_double_page` inklusive Entzerrung und OCR-Vorverarbeitung:
  ca. `10.9s`
- darin OCR-Vorverarbeitung mit `--no-denoise`: ca. `2.8s`
- schlanker RapidOCR-Wrapper mit seinem aelteren einfachen
  Orientierungsvergleich:
  ca. `24.2s`
- fuer diesen Wrapper bleibt `--orientation-mode off` empfohlen; die
  produktive Orientierung uebernimmt die getrennte gemeinsame
  Drei-Zeilen-Sonde

## 1. capture_double_page

Wrapper:

- [hardware/capture_double_page.py](../hardware/capture_double_page.py)

Implementierung:

- [abr/hardware/double_page_capture.py](../abr/hardware/double_page_capture.py)

Interner Ablauf:

1. Rohbild links aufnehmen
2. Rohbild rechts aufnehmen
3. beide Rohbilder mit den gespeicherten Remaps entzerren
4. `case/left.jpg` und `case/right.jpg` schreiben
5. die Enhance-Routine auf den `case`-Ordner anwenden
6. daraus OCR-fertige Eingabebilder und Debug-Stufen erzeugen
7. `captures/latest/` als letzten stabilen Lauf veroeffentlichen

Input:

- Kameras `cam0` und `cam1`
- Remaps `calibration/out/cam0_planar.npz` und `calibration/out/cam1_planar.npz`

Output unter `captures/<session>/`:

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

Bedeutung:

- `case/left.jpg`, `case/right.jpg`: entzerrte Seitenbilder
- `ocr/left.png`, `ocr/right.png`: finale OCR-Eingaben fuer `run_rapidocr.py`
  oder alternativ `run_fallback_pipeline.py`
- `ocr/manifest.json`: Zuordnung der OCR-Dateien zu den Quellbildern und
  Vorverarbeitungs-Timings
- `debug/page_x/...`: nachvollziehbare Vorverarbeitungsstufen
- `metadata.json`: Capture-, Rectify- und Enhance-Timings fuer den ganzen Lauf

Empfohlener aktueller Aufruf auf dem Pi:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
```

## 2. enhance_for_ocr

Wrapper:

- [hardware/enhance_for_ocr.py](../hardware/enhance_for_ocr.py)

Implementierung:

- [abr/preprocessing/enhance_for_ocr.py](../abr/preprocessing/enhance_for_ocr.py)

Zweck:

- vorhandene `case`-Bilder offline in denselben OCR-Zustand bringen wie
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

Wichtige Option:

- `--no-denoise`: schaltet den frueheren Hauptzeitfresser
  `fastNlMeansDenoising` ab

Beispiel:

```bash
python hardware/enhance_for_ocr.py \
  --case-dir testdata/roman_001 \
  --ocr-dir runs/roman_001_prepare/ocr \
  --debug-dir runs/roman_001_prepare/debug \
  --no-denoise
```

## 3. run_rapidocr.py

Wrapper:

- [hardware/run_rapidocr.py](../hardware/run_rapidocr.py)

Implementierung:

- [abr/capture_ocr.py](../abr/capture_ocr.py)

Zweck:

- vorbereitetes `ocr/left.png` und `ocr/right.png` mit `RapidOCR` lesen
- den Text frueh seitenweise schreiben
- optional OCR-Overlays fuer den Review-Server erzeugen
- Laufzeiten pro Seite und pro Teilschritt dokumentieren

Input:

- ein vorbereiteter OCR-Ordner mit:
  - `left.png`
  - `right.png`
  - `manifest.json`

Was der Wrapper macht:

1. vorbereitete OCR-Bilder laden
2. optional eine einfache 0/180-Orientierung pruefen
3. OCR pro Seite ausfuehren
4. `left.txt` sofort schreiben und flushen
5. danach `right.txt` schreiben
6. `report.json` und optional `06_ocr_overlay.png` erzeugen

Empfohlener aktueller Aufruf:

```bash
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

Output unter `runs/<lauf>/`:

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

Wichtige Entscheidung:

- `--orientation-mode simple` bleibt als experimentelle Option im Code
- der aktuelle bevorzugte Standard ist **`--orientation-mode off`**
- dieser Altpfad kostet mehrere Sekunden pro Seite und wird von der
  produktiven Runtime nicht verwendet

Diese Optionen steuern den aelteren seitenweisen 0-/180-Vergleich des
Wrappers. Sie deaktivieren nicht die gemeinsame Drei-Zeilen-
Orientierungssonde der produktiven Runtime.

## 4. run_fallback_pipeline.py

Einstieg:

- [run_fallback_pipeline.py](../run_fallback_pipeline.py)
- [abr/cli.py](../abr/cli.py)
- [abr/pipeline.py](../abr/pipeline.py)

Input:

- ein vorbereiteter OCR-Ordner mit:
  - `left.png`
  - `right.png`
  - `manifest.json`

Typische Quellen dafuer:

- `captures/<session>/ocr/`
- `captures/latest/ocr/`
- `runs/<name>_prepare/ocr/`

Was `run_fallback_pipeline.py` macht:

1. OCR-ready `left.png` und `right.png` laden
2. OCR ausfuehren
3. Layout und Paragraphen aufbauen
4. Lesetext und Report schreiben
5. optional TTS ausgeben

Was `run_fallback_pipeline.py` **nicht** mehr macht:

- keine Entzerrung
- keine Kontrastanhebung
- keine Schaerfung
- keine Binarisierung

`run_fallback_pipeline.py` bleibt wichtig fuer:

- TTS-Tests
- Vergleichslaeufe gegen den schlanken Wrapper
- Layout-, Segment- und Lesestromlogik

Beispiel:

```bash
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/roman_001
```
