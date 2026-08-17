# Raspberry Pi 5 Smoketest

## Ziel

Dieser Ablauf prueft, ob der aktuelle ABR-Prototyp auf einem `Raspberry Pi 5` reproduzierbar laeuft und dabei die erwarteten Artefakte sowie erste Laufzeitmetriken erzeugt.

Der Referenzpfad bleibt:

- OCR: `rapidocr`
- OCR-Eingang: `enhanced`
- TTS: `Google Cloud Text-to-Speech`
- Stimme: `de-DE-Standard-H`

## Erfolgskriterium

Ein Lauf ist erfolgreich, wenn:

- `combined_text.txt` erzeugt wird
- `report.json` erzeugt wird
- bei Audio-Test ein Sprachfile erzeugt wird
- `report.json` `pipeline_timings`, `pages[].timings` und optional `tts` enthaelt

## Systempakete

Empfohlene Basis auf Raspberry Pi OS / Debian `Trixie`:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils
```

Hinweise:

- `libgl1` wird fuer `opencv-python` oft benoetigt.
- `libopenblas-dev` ersetzt auf `Trixie` den frueher oft verwendeten `libatlas-base-dev`-Pfad.
- `pulseaudio-utils` liefert meist `paplay`.
- Wenn `paplay` nicht verfuegbar ist, alternativ `aplay` installieren und verwenden.

## Python-Umgebung

```bash
cd /pfad/zu/abr
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install ".[ocr-rapidocr,dev,tts-google]"
pip install --no-cache-dir opencv-contrib-python
```

Optionaler Fallback-/Vergleichspfad:

```bash
pip install ".[ocr-tesseract]"
sudo apt install -y tesseract-ocr tesseract-ocr-deu
```

Kurzer Check fuer die Kalibrierwerkzeuge:

```bash
python - <<'PY'
import cv2
print("aruco:", hasattr(cv2, "aruco"))
PY
```

Erwartung:

- `aruco: True`

## Google TTS Auth

Variante mit lokalem ADC-Login:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project DEIN_PROJECT_ID
export GOOGLE_CLOUD_QUOTA_PROJECT=DEIN_PROJECT_ID
```

Falls `gcloud` auf dem Pi nicht gewuenscht ist, kann alternativ ein Service-Account ueber ADC bereitgestellt werden. Wichtig ist nur, dass der Code ein gueltiges Token und ein Quota-Projekt ermitteln kann.

## Referenzlauf Ohne Audio

```bash
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --output-dir runs/pi_smoketest_text
```

Pruefen:

- `runs/pi_smoketest_text/combined_text.txt`
- `runs/pi_smoketest_text/report.json`

## Referenzlauf Mit Google TTS Als Datei

```bash
python run_fallback_pipeline.py \
  --case-dir runs/roman_001_prepare/ocr \
  --ocr-backend rapidocr \
  --tts-backend google \
  --google-tts-voice-name de-DE-Standard-H \
  --google-tts-language-code de-DE \
  --tts-speed 0.9 \
  --audio-out runs/pi_smoketest_google/speech.wav \
  --output-dir runs/pi_smoketest_google
```

Pruefen:

- `runs/pi_smoketest_google/speech.wav`
- `runs/pi_smoketest_google/report.json`
- in `report.json`:
  - `pipeline_timings.total_pipeline_sec`
  - `pages[].timings.preprocessing_sec`
  - `pages[].timings.ocr_sec`
  - `pages[].timings.orientation_sec`
  - `pages[].timings.layout_sec`
  - `tts.file_synthesis_sec`

## Referenzlauf Mit Live-TTS

Nur sinnvoll, wenn auf dem Pi ein lokaler Player wie `paplay` oder `aplay`
verfuegbar ist. Fuer den produktiven MAX98357A-Pfad muss das globale
ALSA-`default` gemaess `docs/RASPBERRY_PI_SETUP.md` auf den symbolischen
Kartennamen `MAX98357A` zeigen. Vor dem Live-Lauf pruefen:

```bash
aplay -D default /usr/share/sounds/alsa/Front_Center.wav
```

```bash
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
  --output-dir runs/pi_smoketest_live
```

Zusatzpruefung fuer `report.json`:

- `tts.time_to_first_audio_sec`
- `tts.time_to_first_playback_sec`
- `tts.total_live_tts_sec`

## Bekannte Risiken

- `opencv-python` kann auf dem Pi zusaetzliche Systembibliotheken benoetigen.
- `rapidocr` plus Orientierungserkennung bleiben ein zentraler lokaler CPU-Block.
- die Orientierungserkennung macht aktuell OCR fuer `0` und `180` Grad und ist daher absichtlich eher konservativ als billig.
- Cloud-TTS kann die gefuehlte Latenz trotz schneller OCR dominieren.
- fuer produktionsnahe Laeufe ist `700` aktuell der bevorzugte Kompromiss fuer Live-TTS-Blockgroesse.

## Erste Messpunkte

Fuer den ersten Pi-Vergleich genuegen diese Zahlen:

- `pipeline_timings.total_pipeline_sec`
- `pipeline_timings.page_processing_sec`
- `pages[0].timings.ocr_sec`
- `pages[1].timings.ocr_sec`
- `tts.time_to_first_audio_sec`
- `tts.file_synthesis_sec`

## Wenn Der Lauf Fehlschlaegt

- `rapidocr` fehlt:
  - `pip install ".[ocr-rapidocr]"`
- `onnxruntime` fehlt oder ist defekt:
  - `pip install --force-reinstall onnxruntime`
- fuer einen Tesseract-Vergleich fehlt `pytesseract`:
  - `pip install ".[ocr-tesseract]"`
- fuer einen Tesseract-Vergleich fehlen Sprachdaten:
  - `sudo apt install tesseract-ocr-deu`
- kein Audio-Player fuer Live-TTS:
  - `paplay` oder `aplay` bereitstellen
- `aplay` meldet `Unknown error 524`:
  - `aplay -D plughw:CARD=MAX98357A,DEV=0` gegenpruefen
  - funktioniert das, `/etc/asound.conf` beziehungsweise ALSA-`default`
    korrigieren; Details stehen in `docs/RASPBERRY_PI_SETUP.md`
- Google `403` / Quota-Projekt:
  - `GOOGLE_CLOUD_QUOTA_PROJECT` setzen
- `google-auth` fehlt:
  - `pip install ".[tts-google]"`

## Optional: NFC Gateway Smoketest

Wenn der RP2040-PN532-Gateway mit dem Pi verbunden ist:

```bash
cd /pfad/zu/abr
source .venv/bin/activate
pip install ".[nfc-pn532]"
python hardware/pn532_gateway_client.py STATUS
python hardware/pn532_gateway_client.py DIAG
```

Erfolgskriterium:

- `STATUS` liefert mindestens eine `OK ...`-Zeile und danach `READER ...`-Zeilen
- `DIAG` liefert pro Reader eine Diagnosezeile statt Timeout

Wenn stattdessen der RP2040-PN5180-Gateway mit dem Pi verbunden ist:

```bash
cd /pfad/zu/abr
source .venv/bin/activate
pip install ".[nfc-pn532]"
python hardware/pn5180_gateway_client.py STATUS
python hardware/pn5180_gateway_client.py DIAG
```

Erfolgskriterium:

- `STATUS` liefert mindestens eine `OK ...`-Zeile und danach `READER ...`-Zeilen
- `DIAG` liefert pro Reader eine Diagnosezeile statt Timeout

## Optional: Kamera-Entzerrung Auf Dem Pi

Wenn fuer `cam0` oder `cam1` bereits ein Kalibrierbild unter `calibration/shots/` liegt, kann der erste Entzerrungsaufruf die fehlende Remap-Datei automatisch erzeugen.

Beispiel:

```bash
cd /pfad/zu/abr
source .venv/bin/activate
python calibration/apply_saved_remap.py \
  --input testdata/scans0/cam0_0001.jpg \
  --remap calibration/out/cam0_planar.npz \
  --output testdata/scans0/cam0_0001_rectified.jpg
```

Erwartung:

- falls `calibration/out/cam0_planar.npz` noch fehlt, wird sie automatisch erzeugt
- danach entsteht die entzerrte Ausgabe `testdata/scans0/cam0_0001_rectified.jpg`
