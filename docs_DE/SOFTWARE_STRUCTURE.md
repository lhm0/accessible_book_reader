# Softwarestruktur

Stand: `2026-08-18`

English version: [Software Structure](../docs/SOFTWARE_STRUCTURE.md)

## Zweck

Dieses Dokument erklärt die aktuelle Struktur des Repositorys und ordnet die
wichtigsten Module dem produktiven Gerätepfad, den Entwicklungswerkzeugen und
den persistenten Daten zu.

## Laufzeitpfade

### Produktiver Gerätepfad

Der kanonische Einstieg auf dem Raspberry Pi ist
[hardware/control_panel_service.py](../hardware/control_panel_service.py). Der
systemd-Dienst startet diesen Prozess dauerhaft.

Der Hauptfluss lautet:

```text
Frontpanel-Ereignis
  -> NFC-Abfrage am Pico-Gateway
  -> Aufnahme beider Kameras
  -> Buch ueber NFC zuordnen und Seitenorientierung aus Textzeilen bestimmen
  -> linke Seite vorbereiten, OCR, ingestieren und vorlesen
  -> rechte Seite parallel nachziehen
  -> Abschnittsbildung und Zusammenfassungen aktualisieren
```

### Entwicklungs- und Vergleichspfad

[run_fallback_pipeline.py](../run_fallback_pipeline.py) führt über
`abr.cli` und `abr.pipeline` einen vollständigen, aber nicht produktiven
OCR-/TTS-Vergleichslauf aus. Dieser Pfad bleibt für Backendvergleiche,
Layouttests und isolierte Experimente erhalten. Er ist nicht die Runtime des
fertigen Geräts.

## Python-Paket `abr`

### `abr/control`: Gerätekoordination

- [runtime.py](../abr/control/runtime.py)
  - `RuntimeController`, `ForegroundJobManager` und `PageAudioPlayer`
  - Start/Stop-Semantik, Heartbeat und Buchlöschdialog
  - Capture-, OCR-, Ingest-, Summary- und Audio-Orchestrierung
  - Schutz vor Wiederholung und falscher Seitenfolge
- [frontpanel.py](../abr/control/frontpanel.py)
  - langlebiger Monitor, Debounce, EC11-Quadraturdekodierung
  - Hardwareevents und Übersetzung in fachliche Aktionen
- [audio_volume.py](../abr/control/audio_volume.py)
  - zehn Lautstärkestufen von 20 bis 100 Prozent
  - threadsicherer Sollwert und optionale ALSA-Mixer-Synchronisation
- [artifact_cleanup.py](../abr/control/artifact_cleanup.py)
  - kontrolliertes Entfernen kurzlebiger Capture-/OCR-Artefakte

### `abr/hardware`: Pi-nahe Adapter

- [control_panel.py](../abr/hardware/control_panel.py)
  - BCM-Pinbelegung und GPIO-Backends `rpi-gpio`/`pinctrl`
- [led_control.py](../abr/hardware/led_control.py)
  - getrennte Beleuchtung für linke und rechte Aufnahme
- [double_page_capture.py](../abr/hardware/double_page_capture.py)
  - Kameraaufnahme über `rpicam-still`, Remap und Sessionstruktur
- [double_page_rectify.py](../abr/hardware/double_page_rectify.py)
  - nachträgliche Entzerrung bereits aufgenommener Rohbilder
- [pico_gateway_client.py](../abr/hardware/pico_gateway_client.py)
  - gemeinsamer UART-Client für das Raspberry-Pi-Pico-Gateway
- [nfc_gateway.py](../abr/hardware/nfc_gateway.py)
  - Auswertung von Readerstatus und ISO14443A-/ISO15693-Buchidentifikation
  - zweistufige Abfrage mit `STATUS_START` und `STATUS_FETCH`

Der Raspberry Pi enthält keinen direkten PN5180- oder PN532-Treiber. Die
Reader sind ausschließlich mit dem Pico verbunden; die Pi-Software sieht nur
das UART-Protokoll.

### `abr/book`: persistente Buchdomäne

- [models.py](../abr/book/models.py)
  - `BookRecord`, `ScanRecord`, `PageRecord`, `ChapterRecord`,
    `SummaryRecord` und Kapitelmarker
- [store.py](../abr/book/store.py)
  - atomare JSON-/Textablage unter `library/<tag_id>/`
  - bevorzugte ISO14443A-IDs, ISO15693-Aliase und direkte ISO15693-Buch-IDs
  - persistenter Orientierungs-/Runtime-State und Sprachprüfung
- [session.py](../abr/book/session.py)
  - Auflösung eines Tags in eine Buchsession
- [page_ingestor.py](../abr/book/page_ingestor.py)
  - OCR-Report zu fachlichen `PageRecord`s
  - Seitenzahlen, Kapitelmarker, Absatzstruktur und Seitenübergänge
  - getrennte Felder `clean_text` und `speak_text`
  - sprachabhängige TTS-Aufbereitung
- [chapter_assembler.py](../abr/book/chapter_assembler.py)
  - künstliche Abschnitte in einem Fenster von 10 bis 20 Seiten
  - persistente Grenzen, auch innerhalb einer Seite
  - offener Abschnittstext für temporäre Rückschauen
- [summary_manager.py](../abr/book/summary_manager.py)
  - Gemini-Backend für Abschnitts- und Buchzusammenfassungen
  - Längenregeln, Cachevalidierung, Sprache und Quellen-Fingerabdruck
  - nicht persistente Zusammenfassung des offenen Abschnitts
  - optionaler asynchroner `SummaryService`

Die Datenstruktur ist ausführlich in
[BOOK_RUNTIME_DATA_ARCHITECTURE.md](BOOK_RUNTIME_DATA_ARCHITECTURE.md)
beschrieben.

### Capture, Bildvorbereitung und OCR

- [capture_ocr.py](../abr/capture_ocr.py)
  - schlanker normaler und inkrementeller OCR-Lauf
  - Auswahl und Abstimmung dreier Textzeilen fuer den RapidOCR-
    Winkelklassifikator
  - schreibt Bericht und optionale Overlays
- `abr/preprocessing/`
  - `enhance_for_ocr.py`: produktionsnahe Seiteneinzelvorbereitung
  - `processor.py`: allgemeine Vorverarbeitungsstufen
- `abr/orientation/detector.py`
  - aelterer optionaler 0-/180-Grad-Vergleich fuer nichtproduktive Pipelines
- `abr/ocr/`
  - `base.py` und `factory.py`: Backend-Schnittstelle und Auswahl
  - `rapidocr_backend.py`: produktiver lokaler OCR-Pfad plus Textzeilensuche
    und `0`-/`180`-Grad-Klassifikation
  - `tesseract_backend.py`: Fallback und Vergleich
  - `paddle_backend.py`: experimenteller Vergleichspfad
- `abr/layout/basic.py`
  - Aufbau einfacher Absatz- und Layoutblöcke
- `abr/input/loader.py`
  - Laden vorbereiteter Pipeline-Eingaben
- `abr/debug/`
  - Debug-Artefakte und Visualisierungen
- `abr/reporting.py`
  - serialisierter Pipelinebericht und Laufzeitmetriken

Die Stufentrennung ist in [IMAGE_PIPELINE.md](IMAGE_PIPELINE.md) dokumentiert.

### Textlogik

- [ocr_cleanup.py](../abr/text_logic/ocr_cleanup.py)
  - Worttrennungen und typische OCR-Artefakte
  - gesperrte Buchstabenfolgen und Versalüberschriften
  - deutsche Ausspracheausnahmen `Dr.` → `Doktor` und
    `Notre-Dame` → `Notre Damm`
- [segmenter.py](../abr/text_logic/segmenter.py)
  - Satz- und TTS-Segmentierung
- [reading_order.py](../abr/text_logic/reading_order.py)
  - Lesereihenfolge erkannter Bereiche

### TTS und Audiowiedergabe

- `abr/tts/base.py`
  - gemeinsame TTS-Schnittstelle
- `abr/tts/command_backend.py`
  - eSpeak, macOS `say`, Piper, OpenAI, ElevenLabs
  - Google Standard, Neural2 und Gemini Flash TTS
- [audio_playback.py](../abr/audio_playback.py)
  - gemeinsamer prozessweiter Playback-Lock
  - blockweises PCM-Streaming an `aplay`
  - dynamische Softwarelautstärke und Underrun-Schutz
- [system_audio.py](../abr/system_audio.py)
  - serielle Queue für vorproduzierte Systemhinweise

Die produktive Seitenausgabe verwendet derzeit
`google-standard-enhanced`. Der Renderer erzeugt SSML mit Kapitel-, Satz-,
Absatz- und Dialogpausen erst zur Laufzeit; diese Markierungen werden nicht in
den Buchdaten gespeichert.

### Sprache und Google-Authentifizierung

- [language_config.py](../abr/language_config.py)
  - unveränderliche Profile für Deutsch und U.S.-Englisch
  - atomare Auswahl in `~/.config/abr/device.json`
- [google_cloud_auth.py](../abr/google_cloud_auth.py)
  - gemeinsamer ADC-Zugriff, Token-, Projekt- und Quota-Projekt-Auflösung

Sprache wird durch Capture, OCR, Buch, Kapitel, Zusammenfassung und TTS
durchgereicht. Gemischtsprachige Daten werden abgewiesen. Details:
[LANGUAGE_PROFILES.md](LANGUAGE_PROFILES.md).

### Betriebsfunktionen

- [wifi_profiles.py](../abr/wifi_profiles.py)
  - NetworkManager-Profile, Prioritäten, Wechsel und persistentes Autoconnect
- [remote_mail.py](../abr/remote_mail.py), `remote_mail_download.py`,
  `remote_mail_upload.py`
  - optionaler, validierter Dateiweg per SMTP/IMAP
- [usage_statistics.py](../abr/usage_statistics.py)
  - buchbezogene Seiten-, Audio- und Summary-Zähler
- [usage_report.py](../abr/usage_report.py)
  - Tagesbericht, Mailversand und Archivierung

Persönliche Konfigurationen liegen ausschließlich unter `~/.config/abr/`, in
`~/.config/gcloud/` oder in NetworkManager und nicht im Repository.

## Hardware- und Diagnose-CLIs

Der Ordner `hardware/` enthält dünne ausführbare Wrapper und Diagnosewerkzeuge:

- `control_panel_service.py`: produktiver Prozesseinstieg
- `capture_double_page.py`, `rectify_double_page.py`: Capture/Rectify
- `enhance_for_ocr.py`, `run_rapidocr.py`: Bildvorbereitung/OCR
- `camera_test_server.py`: Kamera-Livebild und Artefakt-Review
- `control_panel_test.py`, `led_light_test.py`: Hardwarediagnose
- `page_ingest_debug.py`: Offline-Ingest-Diagnose
- `generate_audio_message.py`: Systemhinweise erzeugen
- `pn5180_gateway_client.py`, `pn532_gateway_client.py`: UART-Terminalwrapper
- `email_download.py`, `email_upload.py`: ältere Kompatibilitätswrapper; der
  installierte Produktpfad verwendet die `abr.remote_mail_*`-Module

## Pico-Firmware

- `hardware/pn5180_gateway/`
  - bevorzugte PlatformIO-Firmware für bis zu zwei PN5180
  - gemeinsamer Pico-SPI-Bus, Leser strikt nacheinander aktiv
- `hardware/pn532_gateway/`
  - alternative PlatformIO-Firmware für getrennte Pico-I²C-Busse

Beide Gateways stellen dem Pi ein verwandtes zeilenbasiertes UART-Protokoll
bereit. Buildartefakte unter `.pio/` werden nicht versioniert.

## Kalibrierung

Der Ordner `calibration/` enthält:

- `generate_charuco_board.py`: druckbares Referenzboard
- `calibrate_planar_charuco.py`: Kameramodell und feste Remap erzeugen
- `apply_saved_remap.py`: Remap auf Scannerbilder anwenden
- `manual_undistort.py`: manueller Vergleichs- und Fallbackpfad
- `out/`: Referenzboard, Remaps und Vorschauen
- `shots/`: Kalibrieraufnahmen

## Deployment

Der Ordner `deploy/` enthält Vorlagen und idempotente Installer:

- `install_control_panel_service.sh`: produktive Runtime-Unit
- `install_language_switch.sh`: globaler Befehl `abr-language`
- `install_wifi_autoconnect.sh`: einmalige privilegierte
  NetworkManager-Konfiguration; keine dauerhafte ABR-Unit
- `install_remote_mail.sh`: optionaler Mail-Upload-Timer und Downloadbefehl
- `install_usage_statistics.sh`: optionaler täglicher Statistikbericht

Die Installer ersetzen lokale Platzhalter für Benutzer, Home, Repository,
Python und Konfiguration erst beim Schreiben nach `/etc/systemd/system/`.

## Hardwaredesign, Mechanik und Audioressourcen

- `hardware/electronics/`: KiCad-Projekte und aktuelle Produktionsdaten
- `hardware/mechanics/`: CAD-Quellen und exportierte Druckdateien
- `system_audio/messages/de|en/`: vorproduzierte Systemhinweise
- `system_audio/messages/README.md`: Herkunft und Nutzungsrahmen der Audios

## Laufzeit- und generierte Verzeichnisse

- `library/`: persistente lokale Buchdaten; nicht veröffentlichen
- `captures/`: kurzlebige Kamera- und Vorverarbeitungsartefakte
- `runs/`: manuelle Pipeline- und Vergleichsläufe
- `temp/`: temporäre Arbeitsdaten
- `.venv/`, `build/`, `*.egg-info`, `__pycache__/`, `.pytest_cache/`:
  lokale Python-Artefakte
- `datasheets/`: bewusst nur lokal, nicht Teil des öffentlichen Repositorys

Die produktive Runtime darf Buchdaten nur über `BookStore` schreiben. Andere
generierte Verzeichnisse sind Diagnose- oder Arbeitsbereiche und keine
kanonischen Buchdaten.

## Tests

`tests/` enthält Unit- und Integrationstests für alle wesentlichen Ebenen:

- Capture, Remap, Bildvorbereitung und OCR-Backends
- Textbereinigung, Layout und Segmentierung
- BookStore, PageIngestor, ChapterAssembler und SummaryManager
- Frontpanel, Runtime, Audio, Lautstärke und Systemhinweise
- NFC-Gateway und UART-Parser
- Sprache und englischer End-to-End-Integrationspfad
- WLAN, Mail und Nutzungsstatistik

Ausführen:

```bash
cd ~/src/abr
source .venv/bin/activate
python -m pytest -q
```

Hardware, Google-Dienste und reale Audioqualität werden zusätzlich auf dem Pi
geprüft; die automatisierten Tests ersetzen externe Dienste durch
deterministische Testbackends.

## Relevante Architekturdokumente

- [CONTROL_PANEL_ARCHITECTURE.md](CONTROL_PANEL_ARCHITECTURE.md)
- [CONTROL_RUNTIME_ARCHITECTURE.md](CONTROL_RUNTIME_ARCHITECTURE.md)
- [BOOK_RUNTIME_DATA_ARCHITECTURE.md](BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [IMAGE_PIPELINE.md](IMAGE_PIPELINE.md)
- [HARDWARE_GPIO_PLAN.md](HARDWARE_GPIO_PLAN.md)
- [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md)
