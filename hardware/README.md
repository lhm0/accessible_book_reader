# Hardware Uebersicht

Dieses Verzeichnis enthaelt die hardwarebezogenen Teilprojekte fuer den
aktuellen ABR-Scannerstand.

## Struktur

- [pn532_gateway](../hardware/pn532_gateway/README.md)
  - RP2040-/Pico-Gateway fuer `2 x PN532`
  - UART-Protokoll zum `Raspberry Pi 5`
  - weiterhin als alternativer NFC-Pfad im Repo

- [pn5180_gateway](../hardware/pn5180_gateway/README.md)
  - RP2040-/Pico-Gateway fuer bis zu `2 x PN5180`
  - aktueller produktiver Buchkennungs-Pfad
  - aktueller technischer Arbeitsstand: `2 x PN5180`, sequentielle
    Reader-Freigabe ueber `RESET`, on-demand statt Polling

- [electronics](../hardware/electronics/README.md)
  - KiCad-Projekte fuer Pi-Header, Bedienpanel und LED-Bar

- [mechanics](../hardware/mechanics/README.md)
  - Fusion- und Exportdateien fuer den Scanneraufbau

## Wichtige Pi-Skripte

- [capture_double_page.py](../hardware/capture_double_page.py)
  - produktionsnaher Zwei-Kamera-Capture
  - schaltet `LED-left` und `LED-right` passend zur Aufnahme
  - erzeugt `raw`, `rectified`, `case`, `ocr` und `debug/page_1..2`
  - `--no-denoise` ist aktuell der bevorzugte schnelle Pfad

- [run_rapidocr.py](../hardware/run_rapidocr.py)
  - schlanker RapidOCR-Wrapper fuer vorbereitete `ocr/left.png` und
    `ocr/right.png`
  - schreibt `left.txt`, `right.txt` und `report.json`
  - bevorzugter Standard: `--orientation-mode off`

- [camera_test_server.py](../hardware/camera_test_server.py)
  - Browser-Livebildtest fuer die Pi-Kameras
  - optionales Fadenkreuz
  - Review-Modus fuer `raw`, `rectified`, `enhanced` und `ocr-overlay`

- [led_light_test.py](../hardware/led_light_test.py)
  - einfacher Test fuer `LED-left` auf `BCM12` und `LED-right` auf `BCM13`

- [control_panel_test.py](../hardware/control_panel_test.py)
  - einfacher GPIO-Test fuer Taster und `EC11`

- [control_panel_service.py](../hardware/control_panel_service.py)
  - aktueller produktionsnaher Runtime-Dienst
  - startet den echten Lauf `capture -> Bildvorbereitung -> OCR -> page-ingest`
  - liest Buch-Tags ueber NFC-Gateway
  - startet die PN5180-Abfrage beim Tastendruck mit `STATUS_START` und holt
    sie nach beiden Aufnahmen mit `STATUS_FETCH` ab
  - verwendet ISO14443A als fuehrende Buch-ID und ISO15693 als gespeicherte
    alternative Zuordnung
  - ordnet die Kamerabilder anhand des ISO14443A-Readers zu:
    Orientierung 1 behaelt links/rechts, Orientierung 2 vertauscht beide
  - dreht danach `case/right.jpg` einmalig um 180 Grad
  - speichert Ergebnisse unter `library/<tag_id>/`
  - nimmt beide Seiten zuerst komplett auf
  - verarbeitet danach links vor rechts
  - startet die Seitenausgabe, sobald die linke Seite als Audio vorliegt
  - zieht die rechte Seite waehrend der linken Wiedergabe nach
  - spielt vor dem Start `bing`
  - spielt waehrend des Wartens einen Heartbeat mit erneutem `bing`
  - beendet den Heartbeat sauber bei Erfolg, Stop oder Fehler
  - spielt bei nicht vorlesbarem Ingest-Ergebnis `fehler`
  - stoppt eine laufende Seitenausgabe per `Start / Stop`
  - unterstuetzt den Buch-Loeschdialog per Dreifachtaste
  - erzeugt neue Abschnittszusammenfassungen direkt nach neuer
    Abschnittsbildung
  - spielt bei den beiden Summary-Tasten zuerst
    `kapitel_zusammenfassen` bzw. `buch_zusammenfassen`
  - startet danach einen `bing`-Heartbeat bis die Summary-Audio bereit ist
  - spielt `keine_zusammenfassung`, wenn noch kein passender Summary-Text
    verfuegbar ist
  - unterstuetzt konfigurierbares Artefakt-Cleanup

- [page_ingest_debug.py](../hardware/page_ingest_debug.py)
  - Offline-Debugpfad fuer `report.json -> PageRecord -> BookStore`

- [generate_audio_message.py](../hardware/generate_audio_message.py)
  - erzeugt vorproduzierte Audio-Botschaften fuer Systemhinweise
  - Standardstimme: `Google Cloud TTS`, `de-DE-Standard-A`
  - Standardpfad: `system_audio/messages`
  - `--ssml` erlaubt `<break .../>`
  - fuer Raspi-only-Erzeugung ohne Git-Konflikte sollte `--output-root`
    ausserhalb des Repo-Pfads verwendet werden

## Aktueller Runtime-Pfad

Die aktuelle Pi-Laufzeit besteht aus:

1. GPIO-Flankeninterrupts fuer EC11 A/B und Taster-Polling ueber
   `FrontPanelMonitor`; `pinctrl` bleibt Encoder-Polling-Fallback
2. Action-Routing zu fachlichen Aktionen
3. `RuntimeController`
4. `ForegroundJobManager` fuer `capture -> Bildvorbereitung -> OCR -> page-ingest`
5. `PageIngestService`
6. `PageAudioPlayer`
7. `SystemAudio` fuer Warnhinweise

Die EC11-Interruptbehandlung aktualisiert nur einen threadsicheren
Lautstaerke-Sollwert. Seiten- und Systemaudio fragen ihn waehrend der
Wiedergabe blockweise ab. Der dynamische `aplay`-Pfad arbeitet mit `250ms`
PCM-Vorlauf, `300ms` ALSA-Puffer und `50ms` Perioden; jeder PCM-Block wird
sofort geflusht. Damit bleibt insbesondere `bing.wav` trotz laufender
Lautstaerkeregelung zusammenhaengend.

Produktiv verdrahtet sind jetzt zusaetzlich:

- `Buch-Zusammenfassung`
- `Kapitel-/Letzte-Seiten-Zusammenfassung`
- `ChapterAssembler`
- `SummaryManager`

Pi-Audio-Voraussetzung:

- `/etc/asound.conf` definiert das globale ALSA-`default` als `plug`-PCM fuer
  `hw:CARD=MAX98357A,DEV=0`
- der symbolische Kartenname ist verbindlich; numerische Kartenindizes koennen
  durch die beiden HDMI-Karten wechseln
- Setup, Referenztests und Fehlerbild `Unknown error 524` stehen in
  [docs/RASPBERRY_PI_SETUP.md](../docs/RASPBERRY_PI_SETUP.md)

Wichtig:

- `SummaryService` existiert weiterhin als allgemeine asynchrone
  Hilfskomponente im Repo
- der produktive `control_panel_service` verwendet aktuell aber direkt den
  `SummaryManager`

## Pi-Referenzkommando

Dieses Kommando dient dem manuellen Test. Fuer den Dauerbetrieb wird
`abr-control-panel.service` verwendet. Die vollstaendige Einrichtung und
Diagnose steht in
[docs/SYSTEMD_CONTROL_PANEL_SERVICE.md](../docs/SYSTEMD_CONTROL_PANEL_SERVICE.md).

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

Nuetzliche Optionen:

- `--artifact-mode debug|production`
- `--cleanup-stage after-ocr|after-ingest`
- `--page-tts-backend google|google-standard-enhanced|google-neural2|google-gemini-flash`
- `--page-tts-speed 0.9`
- `--volume-mixer-control auto`
- `--summary-gemini-model gemini-3.5-flash`
- `--summary-gcp-project <PROJECT_ID>`
- `--summary-gcp-location global`
- `--chapter-summary-target-pages 1.5`
- `--book-summary-target-pages 1.5`

Bei beiden Summary-Parametern entspricht eine Zielseite `250` Woertern.
Beispielsweise erzeugt `0.5` eine Zielgrenze von `125` Woertern. Wird diese
Grenze um mehr als zehn Prozent ueberschritten, kuerzt Gemini das Ergebnis in
einem zweiten Durchlauf.

Die Taste `Kapitel-/Letzte-Seiten-Zusammenfassung` beruecksichtigt auch Text,
der nach dem letzten abgeschlossenen Abschnitt aufgenommen wurde. Der
`ChapterAssembler` liest ihn ab seiner persistenten offenen Abschnittsgrenze.
Gemini verbindet ihn mit der gespeicherten Zusammenfassung des letzten
Abschnitts. Diese aktuelle Zwischenzusammenfassung wird nur vorgelesen und
nicht unter `summaries/` gespeichert. Existiert noch kein fertiger Abschnitt,
wird der bisherige offene Text allein temporaer zusammengefasst.

Zur Seitensprache:

- `google` bleibt der unveraenderte Default mit `de-DE-Standard-H`
- `google-standard-enhanced` verwendet dieselbe Standard-H-Stimme und
  dasselbe Backend, strukturiert den Text aber mit SSML fuer Saetze,
  Absaetze und Ueberschriften; bei Fragen wird das vollstaendige letzte Wort
  um drei Halbtoene angehoben; nach Saetzen innerhalb eines Absatzes liegen
  `900ms`, nach dem letzten Satz eines Absatzes stattdessen `2000ms` Pause.
  Als Absatz gilt auch ein einfacher Zeilenumbruch nach `.` oder `?`,
  optional gefolgt von einem schliessenden Anfuehrungszeichen. Direkt nach
  einem vollstaendig eingerahmten Dialogsatz gilt trotz Absatzwechsel nur die
  Satzpause von `900ms`.
- `google-neural2` ist ein separater Versuchsweg mit
  `de-DE-Neural2-H`
- `google-gemini-flash` ist ein separater promptgesteuerter Versuchsweg mit
  `gemini-2.5-flash-tts` und der Stimme `Charon`
- Weglassen von `--page-tts-backend` oder explizites
  `--page-tts-backend google` stellt jederzeit den bisherigen Pfad her

Zur Seitenfolge:

- die Runtime merkt sich pro Buch die beiden zuletzt zur Ausgabe
  angenommenen Seitenzahlen
- eine unmittelbar wiederholte Seite fuehrt zu `repeat_page.wav`
- eine niedrigere Doppelseite fuehrt zu `wrong_direction.wav`
- die jeweilige Warnung kann mit einem erneuten Scan einmal bestaetigt
  werden; das spaeter eintreffende zweite Teilergebnis des abgewiesenen
  Scans bleibt unterdrueckt

Zur Summary-Laenge:

- `target-pages` wird mit `250` Woertern pro Zielseite in eine konkrete
  Wortgrenze umgesetzt
- ein grosszuegiges technisches Tokenbudget verhindert, dass Thinking die
  sichtbare Antwort vorzeitig abschneidet
- bei mehr als zehn Prozent Ueberschreitung folgt ein Kuerzungsdurchlauf

## Weitere Doku

- [docs/HARDWARE_GPIO_PLAN.md](../docs/HARDWARE_GPIO_PLAN.md)
- [docs/CONTROL_PANEL_ARCHITECTURE.md](../docs/CONTROL_PANEL_ARCHITECTURE.md)
- [docs/CONTROL_RUNTIME_ARCHITECTURE.md](../docs/CONTROL_RUNTIME_ARCHITECTURE.md)
- [docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md](../docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [docs/DOUBLE_PAGE_CAPTURE.md](../docs/DOUBLE_PAGE_CAPTURE.md)
