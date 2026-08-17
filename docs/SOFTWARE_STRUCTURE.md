# Software Structure

Stand: `2026-08-01`

## Uebersicht

Im Repo existieren inzwischen zwei relevante Ebenen:

1. der historische Vollpfad ueber [run_fallback_pipeline.py](../run_fallback_pipeline.py)
2. der aktuelle produktionsnahe Geraetepfad ueber
   [hardware/control_panel_service.py](../hardware/control_panel_service.py)

Der neue Schwerpunkt liegt klar auf Ebene 2.

## Historischer Vollpfad

Einstieg:

- [run_fallback_pipeline.py](../run_fallback_pipeline.py)
- [abr/cli.py](../abr/cli.py)
- [abr/pipeline.py](../abr/pipeline.py)

Dieser Pfad bleibt wichtig fuer:

- Vergleichslaeufe
- OCR-/TTS-Experimente
- isolierte Pipeline-Tests

## Aktueller Geraetepfad

### Einstieg

- [hardware/control_panel_service.py](../hardware/control_panel_service.py)

### Eingabe und Frontpanel

- [abr/hardware/control_panel.py](../abr/hardware/control_panel.py)
  - GPIO-Abstraktion
  - Flankencallbacks fuer das produktive `rpi-gpio`-Backend
- [abr/control/frontpanel.py](../abr/control/frontpanel.py)
  - Flankeninterrupts und Quadraturdekodierung fuer EC11 A/B
  - Polling mit Debounce fuer Taster
  - Encoder-Polling-Fallback fuer `pinctrl`
  - Event-Typen
  - Action-Router

### Runtime

- [abr/control/runtime.py](../abr/control/runtime.py)
  - `RuntimeController`
  - `ForegroundJobManager`
  - `PageAudioPlayer`
  - Heartbeat
  - Buch-Loeschdialog
  - Verkabelung von `capture -> Bildvorbereitung -> OCR -> page-ingest ->
    Seitenausgabe`
  - beide Seiten werden zuerst aufgenommen, danach links vor rechts verarbeitet

- [abr/control/audio_volume.py](../abr/control/audio_volume.py)
  - Lautstaerkelogik mit 10 Stufen von `20%` bis `100%`
  - threadsicherer Sollwert, der im EC11-Callback ohne Subprozess aktualisiert
    werden kann
  - nachgelagerte Synchronisation mit dem optionalen ALSA-Mixer

- [abr/control/artifact_cleanup.py](../abr/control/artifact_cleanup.py)
  - Cleanup nach OCR oder nach Ingest

### NFC

- [abr/hardware/nfc_gateway.py](../abr/hardware/nfc_gateway.py)
  - Runtime-Leser fuer Gateway-Status
  - zweistufige Abfrage mit `STATUS_START` und `STATUS_FETCH`
  - gemeinsame Auswertung von ISO14443A und ISO15693 inklusive Reader-ID
- [abr/hardware/pico_gateway_client.py](../abr/hardware/pico_gateway_client.py)
  - UART-Client
- [hardware/pn5180_gateway_client.py](../hardware/pn5180_gateway_client.py)
  - Terminal-Wrapper

### Buchdaten

- [abr/book/models.py](../abr/book/models.py)
  - `BookRecord`, `ScanRecord`, `PageRecord`, `ChapterRecord`,
    `SummaryRecord`
- [abr/book/store.py](../abr/book/store.py)
  - persistente Buchdatenablage
  - ISO15693-Aliaszuordnung zu einem fuehrenden ISO14443A-Buch
- [abr/book/session.py](../abr/book/session.py)
  - `BookSessionResolver`
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
  - `PageIngestor`
  - `PageIngestService`
- [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)
  - Offline-Debug-CLI fuer Ingest

### Audio

- [abr/system_audio.py](../abr/system_audio.py)
  - Erzeugen und Abspielen von Systemhinweisen
- [hardware/generate_audio_message.py](../hardware/generate_audio_message.py)
  - CLI fuer Warnhinweise
- [abr/audio_playback.py](../abr/audio_playback.py)
  - Datei-Playback mit gemeinsamem Playback-Lock
  - dynamische Software-Lautstaerke durch blockweise Abfrage des aktuellen
    Sollwerts waehrend der Wiedergabe
  - stabilisierter `aplay`-Streamingpfad mit `250ms` PCM-Vorlauf, `300ms`
    ALSA-Puffer, `50ms` Perioden und sofortigem Flush jedes PCM-Blocks
  - verwendet auf dem Pi `aplay` ohne explizites ALSA-Geraet
  - erwartet deshalb ein systemweites `default`-Plug-PCM fuer
    `CARD=MAX98357A`; Details stehen in `docs/RASPBERRY_PI_SETUP.md`

### Capture und OCR

- [abr/hardware/double_page_capture.py](../abr/hardware/double_page_capture.py)
  - Capture-Implementierung
- der Runtime-Adapter in `abr/control/runtime.py` ordnet nach `STATUS_FETCH`
  die beiden `case`-Dateien der Buchorientierung zu und dreht die fertige
  rechte Seitendatei einmalig um 180 Grad
- [hardware/capture_double_page.py](../hardware/capture_double_page.py)
  - Pi-CLI fuer Capture
- [abr/capture_ocr.py](../abr/capture_ocr.py)
  - schlanker OCR-Pfad fuer vorbereitete OCR-Bilder
- [hardware/run_rapidocr.py](../hardware/run_rapidocr.py)
  - Pi-CLI fuer RapidOCR

### OCR, Layout und Text

- [abr/ocr/rapidocr_backend.py](../abr/ocr/rapidocr_backend.py)
- [abr/ocr/tesseract_backend.py](../abr/ocr/tesseract_backend.py)
- [abr/ocr/paddle_backend.py](../abr/ocr/paddle_backend.py)
- [abr/layout/basic.py](../abr/layout/basic.py)
- [abr/text_logic/ocr_cleanup.py](../abr/text_logic/ocr_cleanup.py)
  - repariert Worttrennungen und typische OCR-Textartefakte
  - zieht gesperrt gesetzte Buchstabenfolgen zusammen
  - erkennt kurze Grossbuchstaben-Ueberschriften und erzeugt fuer
    `speak_text` eine lesbare Gross-/Kleinschreibung
  - normalisiert deutsche Ausspracheausnahmen im `speak_text`: `Dr.` zu
    `Doktor` und `Notre-Dame` zu `Notre Damm`
- [abr/text_logic/segmenter.py](../abr/text_logic/segmenter.py)
- [abr/text_logic/reading_order.py](../abr/text_logic/reading_order.py)

### TTS

- [abr/tts/base.py](../abr/tts/base.py)
- [abr/tts/command_backend.py](../abr/tts/command_backend.py)

Wichtig:

- Seitenausgabe nutzt aktuell vor allem `google`
- fuer Kapitelansagen fuegt die Runtime SSML-Pausen nur bei SSML-faehigen
  Backends wie `google` und `say` ein
- `google-standard-enhanced` behandelt normalisierte
  Grossbuchstaben-Ueberschriften als eigene Kapitelgrenze mit `1350ms` Pause
  und verwendet `900ms` Satz- sowie `2000ms` Absatzpause; Absatzgrenzen direkt
  nach vollstaendig eingerahmten Dialogsaetzen erhalten nur die Satzpause

### Buchsprachenkonfiguration

- [abr/language_config.py](../abr/language_config.py)
  - zentrale unveraenderliche Profile fuer Deutsch und U.S.-Englisch
  - fehlende Konfiguration verwendet die bisherigen deutschen Werte
  - persistente, atomare Auswahl unter `~/.config/abr/device.json`
- [deploy/install_language_switch.sh](../deploy/install_language_switch.sh)
  - installiert den Systembefehl `abr-language`
- `hardware/control_panel_service.py` laedt das Profil beim Start und
  konfiguriert Standard-TTS, Neural2, ElevenLabs und Gemini Flash
- `PageIngestor` erzeugt sprachabhaengig `Kapitel ...` oder `Chapter ...` fuer
  isolierte Kapitelnummern
- normaler und Enhanced-SSML-Renderer erkennen das Kapitelwort des Profils
- `CaptureOCRJobConfig` transportiert `de|en` durch beide OCR-Runtime-Pfade
- RapidOCR behaelt fuer Deutsch den bisherigen Default-Enginepfad und verwendet
  fuer Englisch ein separates mobiles PP-OCRv5-Recognition-Modell
- OCR-Reports und Scanmetadaten halten Sprache und Modellprofil fest
- Deutsch bleibt bei fehlender Konfiguration mit den bisherigen Stimmen und
  Ausgaben der Default
- Details und Stufenplan:
  [LANGUAGE_PROFILES.md](../docs/LANGUAGE_PROFILES.md)

### E-Mail-Fernwartung

- [abr/remote_mail.py](../abr/remote_mail.py)
  - gemeinsame SMTP-/IMAP-Implementierung
  - atomisches Speichern ohne Ueberschreiben
  - Absender-, Betreff- und Anhangsvalidierung
  - UID-Zustand fuer gelesene und ungelesene Upload-Mails
- [abr/remote_mail_download.py](../abr/remote_mail_download.py)
  - Moduleinstieg fuer den globalen Befehl `email_download`
- [abr/remote_mail_upload.py](../abr/remote_mail_upload.py)
  - einmaliger IMAP-Prueflauf fuer den `systemd`-Dienst
- [deploy/install_remote_mail.sh](../deploy/install_remote_mail.sh)
  - installiert globalen Download-Wrapper, Upload-Service und Timer
- `deploy/abr-email-upload.service` und `deploy/abr-email-upload.timer`
  - pruefen den Posteingang alle zwei Minuten

### Nutzerstatistik

- [abr/usage_statistics.py](../abr/usage_statistics.py)
  - persistente buchweise Zaehler mit Statistiktag ab `04:00`
  - atomische JSON-Ablage und Prozess-/Thread-Sperren
  - erzeugt fuer abgeschlossene Tage ohne Nutzung synthetische Leerperioden
  - archivierte Leerperioden verhindern mehrfachen Versand desselben
    Nullberichts und erlauben das geordnete Nachholen mehrtaegiger Luecken
- [abr/usage_report.py](../abr/usage_report.py)
  - formatiert abgeschlossene Perioden, versendet sie ueber den bestehenden
    Mail-Account und archiviert erst nach erfolgreichem Versand
  - versendet auch Berichte mit `Keine Nutzung erfasst.` und Nullsummen
- `deploy/abr-usage-report.service` und `deploy/abr-usage-report.timer`
  - taeglicher, persistenter systemd-Lauf um `04:00`
- Installation und Betrieb:
  [USAGE_STATISTICS.md](../docs/USAGE_STATISTICS.md)

Der Upload-Betreff enthaelt nur den Zielordner, zum Beispiel
`save src/abr/`. Der Name des einzigen Anhangs wird als Zieldateiname
verwendet. Erfolgreich verarbeitete Mails werden aus dem IMAP-Postfach
geloescht. Details stehen in `docs/REMOTE_MAINTENANCE_EMAIL.md`.

## Neue Buchschicht

Im `abr/book`-Paket liegen jetzt zusaetzlich:

- `abr/book/chapter_assembler.py`
  - bildet aus `PageRecord`s kuenstliche 10-20-Seiten-Abschnitte
  - speichert Mid-Page-Grenzen persistent im Runtime-State
  - liefert mit `collect_pending_content()` den noch nicht abgeschlossenen
    Text ab dieser persistenten Grenze, ohne einen Abschnitt zu erzwingen
- `abr/book/summary_manager.py`
  - erzeugt persistente Abschnitts- und Buchzusammenfassungen
  - erzeugt mit `summarize_chapter_progress()` eine nicht gespeicherte
    aktuelle Rueckschau aus letzter Abschnittszusammenfassung und offenem Text
  - erzeugt Abschnitts- und Gesamtzusammenfassungen ueber Gemini
  - erzeugt neue Abschnittszusammenfassungen im aktuellen Runtime-Pfad direkt
    nach neuer Abschnittsbildung
  - kann Summary-Caches bei geaenderter Zielgroesse automatisch neu erzeugen
  - erzeugt deutsche oder U.S.-englische Prompts anhand des aktiven
    Sprachprofils
  - validiert persistente Kapitel- und Buch-Caches auch gegen deren Sprache;
    alte sprachlose Caches gelten kompatibel als Deutsch
  - enthaelt weiterhin auch `SummaryService` als optionale asynchrone
    Hilfskomponente
- `abr/book/page_ingestor.py`
  - ersetzt beim inkrementellen OCR-Lauf einen zunaechst unnummeriert
    gespeicherten Seitenplatzhalter, sobald dieselbe Seite im vollstaendigen
    Report eine Seitenzahl erhalten hat
  - loescht den Platzhalter erst nach erfolgreichem Speichern der nummerierten
    Seite und nur bei gleicher Scan-ID, Seite und OCR-Report-Seiten-ID
  - bindet neue Buecher an `BookRecord.language` und lehnt OCR-Reports oder
    bestehende Buecher mit abweichender Sprache vor dem Speichern ab
- `abr/book/store.py`
  - behandelt alte `BookRecord`s ohne Sprache kompatibel als Deutsch
  - stellt mit `require_book_language()` die zentrale Sprachpruefung fuer
    nachgelagerte Buchfunktionen bereit
- `abr/book/chapter_assembler.py`
  - prueft die Sprache aller Quellseiten gegen das Buch und schreibt sie in
    die Kapitelmetadaten
