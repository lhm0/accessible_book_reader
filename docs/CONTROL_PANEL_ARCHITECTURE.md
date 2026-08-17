# Control Panel Architecture

Stand: `2026-08-01`

## Ziel

Die Bedienlogik des ABR-Geraets soll dauerhaft auf dem `Raspberry Pi 5` laufen
und dabei:

- Taster und `EC11` permanent ueberwachen
- Hardwareereignisse von der fachlichen Logik trennen
- auch waehrend Capture, OCR, TTS und NFC reaktionsfaehig bleiben

## Tatsachlich implementierte Struktur

Der aktuelle Pi-Pfad besteht aus vier klar getrennten Schichten:

1. `GPIO backend`
   - direkter GPIO-Zugriff ueber `RPi.GPIO` auf Basis von `rpi-lgpio`
   - Fallback fuer Tests: `pinctrl`
2. `FrontPanelMonitor`
   - Taster-Polling in einem langlebigen Thread
   - GPIO-Flankeninterrupts fuer beide EC11-Kanaele mit `rpi-gpio`
   - entprellt Taster
   - dekodiert den `EC11`
   - erzeugt nur Hardwareevents
3. `Action Router`
   - uebersetzt Hardwareevents in fachliche Aktionen
   - erkennt auch die Dreifachtaste fuer den Buch-Loeschdialog
4. `Runtime Controller`
   - verarbeitet Aktionen
   - steuert Jobs, Audio, Buchkontext und Fehlerpfade

## Interrupts fuer den EC11, Polling fuer Taster

Der EC11 verwendet mit dem produktiven `rpi-gpio`-Backend Flankeninterrupts
auf Kanal A und B. Der Callback liest beide Pegel als gemeinsamen Snapshot
und fuehrt nur zeitkritische, nicht blockierende Arbeit aus:

- Quadraturdecoder aktualisieren
- threadsicheren Lautstaerke-Sollwert im Speicher veraendern
- normales Encoder-Event fuer Logging und Mixer-Synchronisation einreihen

Im Interrupt werden weder `amixer` noch Audio- oder andere Subprozesse
gestartet. Das verhindert lange Callback-Laufzeiten. Mechanische Taster
bleiben beim bewaehrten Polling mit Debounce. Falls nur `pinctrl` verfuegbar
ist, arbeitet auch der Encoder weiter per Polling; die Sollwertvariable wird
dann direkt im Monitor-Thread aktualisiert.

- Taster: Polling mit Debounce
- Encoder: Flankeninterrupt mit Quadratur-Dekodierung, Polling-Fallback
- Fachlogik: weiterhin nach Event-Uebersetzung; nur der atomare Sollwert wird
  bereits im Callback veraendert

## Polling-Fallback

Der Monitor arbeitet mit zwei Taktbereichen:

- Leerlauf: `2.0 ms`
- waehrend Encoder-Aktivitaet: `0.5 ms`
- `encoder_active_hold_ms`: `25 ms`
- Button-Debounce: `25 ms`

Diese schnellen Intervalle gelten fuer Taster-Snapshots und als
Encoder-Fallback. Bei aktivem GPIO-Interrupt werden Encoderpegel nicht
zusaetzlich im Pollingpfad dekodiert.

## Aktuell verdrahtete Bedienlogik

### `Start / Stop / NFC`

- startet den echten Lauf `capture -> Bildvorbereitung -> OCR -> page-ingest`
- stoppt einen laufenden foreground job
- stoppt eine laufende Seitenausgabe
- stoppt auch den reinen Heartbeat-Wartezustand

### `EC11`

- veraendert die Lautstaerke direkt
- funktioniert auch waehrend laufender Seiten- und Systemaudioausgabe wie
  `bing.wav`
- der Interrupt aktualisiert nur den Sollwert; Mixerzugriff, Logging und
  sonstige Subprozesse laufen weiterhin ausserhalb des Callbacks
- die eigentliche WAV-Wiedergabe fragt den Sollwert blockweise ab; Details zu
  Pufferung und Underrun-Schutz stehen in
  [CONTROL_RUNTIME_ARCHITECTURE.md](../docs/CONTROL_RUNTIME_ARCHITECTURE.md)

### `EC11-Taster`

- aktuell produktiv nur fuer den Buch-Loeschdialog genutzt

### Dreifachtaste

Die gleichzeitige Betaetigung aus:

- `Start / Stop / NFC`
- `Buch-Zusammenfassung`
- `Kapitel-/Letzte-Seiten-Zusammenfassung`

startet den Buch-Loeschdialog.

## Produktiv verdrahtete Summary-Tasten

### `Kapitel-/Letzte-Seiten-Zusammenfassung`

- spielt zuerst `kapitel_zusammenfassen`
- startet danach einen `bing`-Heartbeat bis die Audioausgabe startet
- zieht zunaechst neu abschliessbare Abschnitte nach und prueft danach den
  Text ab der persistenten offenen Abschnittsgrenze
- kombiniert offenen Text mit der letzten verfuegbaren
  Abschnittszusammenfassung zu einer temporaeren Rueckschau
- fasst vor dem ersten fertigen Abschnitt den offenen Text allein zusammen
- speichert diese temporaere Rueckschau nicht
- ohne offenen Text holt sie weiterhin die letzte verfuegbare
  Abschnittszusammenfassung und kann diese bei Bedarf ueber Gemini erzeugen
  oder aktualisieren

### `Buch-Zusammenfassung`

- spielt zuerst `buch_zusammenfassen`
- startet danach einen `bing`-Heartbeat bis die Audioausgabe startet
- erzeugt auf Basis aller vorhandenen Abschnittszusammenfassungen ein
  aktuelles "Was bisher geschah"

### Fehlender Summary-Inhalt

- nur wenn weder ein abgeschlossener Abschnitt noch offener Text vorliegt,
  spielt die Runtime `keine_zusammenfassung`

## Relevante Dateien

- [abr/hardware/control_panel.py](../abr/hardware/control_panel.py)
- [abr/control/frontpanel.py](../abr/control/frontpanel.py)
- [abr/control/runtime.py](../abr/control/runtime.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)

## Naechster sinnvoller Ausbau

Auf Ebene des Bedienpanels ist der naechste sinnvolle Schritt nicht mehr die
Grundverdrahtung, sondern Feinschliff und Betriebsreife:

1. Summary-Heartbeat und Fehlermeldungen mit echtem Pi-Betrieb weiter testen
2. Status-/Telemetry-Ereignisse fuer Abschnitt und Summary ergaenzen
3. spaeter `systemd`-Start fuer den Runtime-Dienst
