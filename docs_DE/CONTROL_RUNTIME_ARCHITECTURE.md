# Control Runtime Architecture

Stand: `2026-07-11`

## Ziel

Dieses Dokument beschreibt die aktuell implementierte Laufzeitarchitektur des
ABR-Geraets auf dem `Raspberry Pi 5`.

Die fachliche Buch-, Seiten- und spaetere Kapitel-/Summary-Logik ist separat in
[docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md](../docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)
beschrieben.

## Implementierte Hauptkomponenten

Die Runtime besteht derzeit aus:

1. `FrontPanelMonitor`
2. `Action Router`
3. `RuntimeController`
4. `ForegroundJobManager`
5. `PageIngestService`
6. `PageAudioPlayer`
7. `SystemAudio`-Worker
8. `AudioVolumeController`

## Kerngedanke

Die GPIO-Ueberwachung ist strikt von langen Jobs getrennt. Capture, OCR, TTS
und Audioausgabe blockieren den Frontpanel-Pfad nicht.

Es gibt zwei parallel relevante Ebenen:

- `Work State`
- Audiozustand

Das ist bereits praktisch umgesetzt.

## Tatsachlich verwendete Zustandsidee

### Work State

Aktuell implementiert:

- `idle`
- `capture_ocr_running`
- `book_summary_running`
- `chapter_summary_running`
- `delete_book_confirmation`
- `cancelling_work`
- `error`

Wichtig:

- die beiden Summary-States sind jetzt als echte Foreground-Jobs verdrahtet
- waehrend einer laufenden Zusammenfassung bleiben Frontpanel und Audiostopp
  weiterhin reaktionsfaehig

### Audioebenen

Es gibt zwei unterschiedliche Audiopfade:

- `SystemAudio`
  - serielle Queue
  - Warnhinweise sollen vollstaendig laufen
- `PageAudioPlayer`
  - fuer Seitenausgabe
  - explizit abbrechbar

Diese Trennung ist absichtlich und fachlich wichtig.

Beide Pfade teilen sich jedoch dieselbe lokale Playback-Implementierung in
`abr/audio_playback.py` und denselben pro Prozess geltenden Playback-Lock. Auf
dem Raspberry Pi wird `aplay` ohne explizites ALSA-`-D` gestartet. Die
Maschinenkonfiguration muss deshalb `/etc/asound.conf` so definieren, dass das
globale `default` als `plug`-PCM auf `hw:CARD=MAX98357A,DEV=0` zeigt. Der
symbolische Kartenname ist absichtlich stabiler als `card 0`, `card 1` oder
`card 2`; diese Nummern koennen sich durch HDMI- und Treiberreihenfolge
aendern. Die `plug`-Konvertierung ist notwendig, weil der Hardwarepfad zwei
Kanaele erwartet, die erzeugten WAV-Dateien aber mono sein koennen.

## Foreground-Job-Regel

Aktuell gilt:

- genau ein foreground job gleichzeitig
- derzeit produktiv nur der Lauf `capture -> Bildvorbereitung -> OCR ->
  page-ingest`
- Audio darf parallel dazu laufen
- keine versteckte Job-Warteschlange

## Start-/Stop-Semantik

### `Start / Stop / NFC`

Bei `idle`:

- NFC-Tag lesen
- Buchkontext sicherstellen
- `bing`
- Heartbeat starten
- den Lauf `capture -> Bildvorbereitung -> OCR -> page-ingest` starten

Bei laufendem foreground job:

- Abbruch anfordern
- `abbruch`

Bei laufender Seitenausgabe:

- Wiedergabe sofort stoppen
- `abbruch`

Bei reinem Heartbeat-Wartezustand:

- Heartbeat stoppen
- spaeter eintreffendes `page-ingest`-Ergebnis verwerfen
- `abbruch`

## Heartbeat

Der Start-Wartezustand wird durch einen separaten Heartbeat-Thread dargestellt.

Aktuelles Verhalten:

- Standardintervall: `5s`
- Signal: `bing`
- endet bei:
  - erster fertiger Seitenaudio
  - Fehler
  - Stop
  - leerem `page-ingest`-Ergebnis

Dieser Pfad ist inzwischen explizit abgesichert, damit es keine
Endlosschleifen mehr gibt, wenn OCR/Ingress zwar formal erfolgreich waren,
aber keine vorlesbaren Seiten entstanden sind. In diesem speziellen Fall
wird `empty_page.wav` ausgegeben; andere Fehlerpfade bleiben unveraendert
bei `fehler.wav`.

## SystemAudio

Die vorproduzierten Systemhinweise liegen sprachweise unter
`system_audio/messages/de/` und `system_audio/messages/en/`. Beim Start liest
`control_panel_service.py` das aktive Sprachprofil und uebergibt dem Runtime-
Controller genau den zugehoerigen Ordner. Ein Wechsel mit `abr-language` wird
daher nach dem Neustart von `abr-control-panel.service` wirksam.

Die logischen Dateinamen sind in beiden Sprachordnern identisch. Eine neue
Systemmeldung muss immer fuer beide Sprachen bereitgestellt werden. Ein
fehlender Hinweis wird nicht aus einem anderen Sprachordner ersetzt, sondern
als Laufzeitfehler mit dem vollstaendig aufgeloesten Pfad protokolliert.

Aufgaben:

- `bing`
- `neues_buch`
- `abbruch`
- `buch_loeschen`
- `buch_geloescht`
- `buch_nicht_erkannt`
- `fehler`
- `kapitel_zusammenfassen`
- `buch_zusammenfassen`
- `keine_zusammenfassung`

Wichtige Regel:

- diese Hinweise laufen ueber eine eigene Queue
- sie sollen nicht durch die Seitenausgabe zerhackt werden

## Seitenaudio

Der `PageAudioPlayer`:

- ignoriert leere `speak_text`-Seiten
- spielt vorhandene Seiten in Reihenfolge ab
- startet erst, nachdem die linke Seite komplett als Audio vorliegt
- waehrend die linke Seite laeuft, werden Bildvorbereitung, OCR,
  `PageIngestor` und TTS fuer die rechte Seite nachgezogen
- ist per `Start / Stop` sofort abbrechbar

Wichtig fuer die Wartezeit:

- beide Seiten werden weiterhin zuerst komplett aufgenommen
- erst danach wird links vor rechts verarbeitet
- das verkuerzt die Zeit von `Start` bis zur ersten Audioausgabe, ohne dass das
  Buch noch auf dem Scanner liegen bleiben muss

Kapitelansagen:

- werden zur Laufzeit fuer `google` und `say` als SSML behandelt
- vor `Kapitel ...` liegt eine Pause von `1350ms`
- nach `Kapitel ...` ebenfalls `1350ms`
- kurze, vollstaendig grossgeschriebene OCR-Ueberschriften werden fuer die
  Ausgabe in lesbare Gross-/Kleinschreibung umgewandelt, als eigener Absatz
  behandelt und erhalten danach ebenfalls `1350ms` Pause

## Lautstaerke

Der `AudioVolumeController`:

- arbeitet aktuell mit `10` Stufen
- Bereich `20% .. 100%`
- bevorzugt Software-Regelung, wenn kein brauchbarer ALSA-Mixer verfuegbar ist
- wirkt auch waehrend aktiver Wiedergabe

Die Lautstaerke besitzt einen threadsicheren Sollwert. Ein EC11-Schritt
veraendert ihn bereits im GPIO-Flankencallback ueber `request_delta()`; dieser
Pfad startet bewusst keinen Mixer-Subprozess. Der spaeter verarbeitete normale
Encoder-Event synchronisiert bei Bedarf den ALSA-Mixer und schreibt das Log.

Sowohl `PageAudioPlayer` als auch `SystemAudio` uebergeben
`AudioVolumeController.current_percent` als `volume_provider` an die lokale
WAV-Wiedergabe. Der `aplay`-Streamingpfad fragt diesen Wert fuer jeden
PCM-Block erneut ab. Damit wirkt eine Drehung auch waehrend eines synchronen
`bing.wav`, obwohl der Runtime-Hauptthread bis zum Tonende blockiert ist.

Da dynamisch regelbare WAVs als PCM-Strom an `aplay` gehen, braucht dieser
Pfad Reserve gegen kurze Scheduler-Verzoegerungen auf dem Pi. Der erlaubte
PCM-Vorlauf betraegt `250ms`, der ALSA-Puffer `300ms` bei einer Periode von
`50ms`. Die zuvor verwendeten `100ms` Reserve konnten bei einem beschaeftigten
System einen kurzen Buffer-Underrun und damit eine hoerbare Unterbrechung in
der etwa vier Sekunden langen `bing.wav` verursachen. Die groessere Reserve
haelt die Wiedergabe zusammenhaengend. Jeder skalierte PCM-Block wird zudem
sofort in die Pipe geflusht, statt mehrere Bloecke im Python-Schreibpuffer zu
sammeln; Lautstaerkeaenderungen bleiben mit deutlich unter einer Sekunde
Reaktionszeit wahrnehmbar direkt.

## Nutzerstatistik

Der produktive `control_panel_service` erzeugt einen
`UsageStatisticsStore` unterhalb des konfigurierten `library-root` und reicht
ihn an den `RuntimeController` weiter.

Die Runtime erfasst buchbezogen:

- erfolgreich ingestierte Seiten; `scan_id` plus `page_id` verhindern eine
  Doppelzaehlung durch den inkrementellen Ingest derselben Seite
- die reale Laufzeit jedes Seiten- und Zusammenfassungsaudios um den
  blockierenden Playback-Aufruf, auch bei einem vorzeitigen Abbruch
- den Start der Kapitel-/Letzte-Seiten-Zusammenfassung
- den Start von `Was bisher geschah`

Systemaudio und Signalklaenge laufen ueber einen getrennten Wiedergabepfad
und werden nicht als Vorlesezeit erfasst. Statistikfehler werden geloggt, aber
nicht in den eigentlichen Geraeteablauf weitergereicht.

Die persistente Ablage ist atomar und gegen parallele Zugriffe aus Runtime,
Audio-Thread und Report-Prozess gesperrt. Perioden folgen `Europe/Berlin` und
laufen von `04:00` bis `04:00`. Versand, Archivierung und systemd-Betrieb sind
in [USAGE_STATISTICS.md](../docs/USAGE_STATISTICS.md)
beschrieben.

## Buch-Loeschdialog

Implementiert im Runtime-Controller:

1. Dreifachtaste
2. NFC lesen
3. wenn kein Tag:
   - `buch_nicht_erkannt`
4. wenn Tag vorhanden:
   - `buch_loeschen`
   - Bestaetigung nur per `EC11`-Taster
   - Abbruch per Funktionstaste
5. Ergebnis:
   - `abbruch` oder `buch_geloescht`

## Implementierte Grenzen

Die Runtime koordiniert bereits:

- Frontpanel
- NFC
- Capture/OCR
- Heartbeat
- Page-Ingest
- Seitenausgabe
- Lautstaerke
- Buch-Loeschen

Die Runtime koordiniert jetzt zusaetzlich:

- Abschnittsbildung nach jedem erfolgreichen `page-ingest`
- sofortige Abschnittszusammenfassung fuer neue Abschnitte ueber
  `SummaryManager`
- Tastenjobs fuer letzte Abschnittszusammenfassung und "Was bisher geschah"
- temporaere aktuelle Rueckschau aus der letzten persistenten
  Abschnittszusammenfassung und dem noch offenen Abschnittstext

Wichtig fuer die Summary-Tasten:

- Kapitel- und Buchzusammenfassung starten mit einer vorgelagerten
  Systemnachricht
- danach laeuft derselbe `bing`-Heartbeat wie beim Start-Knopf
- vor der Ausgabe der Kapitel-/Letzte-Seiten-Zusammenfassung zieht der
  `ChapterAssembler` fertige Abschnitte nach und liest danach den Text ab
  seiner persistenten offenen Grenze
- ist offener Text vorhanden, erzeugt `SummaryManager.summarize_chapter_progress()`
  daraus und aus der letzten Abschnittszusammenfassung einen nur im Speicher
  gehaltenen `SummaryRecord`; vor dem ersten Abschnitt dient nur der offene
  Text als Quelle
- ohne offenen Text bleibt der bisherige Pfad zur letzten persistenten
  Abschnittszusammenfassung unveraendert
- erst wenn der Summary-Text als Audio enqueued ist, endet der Heartbeat
- nur wenn weder ein abgeschlossener Abschnitt noch offener Text vorhanden
  ist, spielt die Runtime `keine_zusammenfassung`

Der temporaere Pfad ist im Log explizit erkennbar:

```text
Temporaere Kapitelzusammenfassung wird aus dem letzten Abschnitt und N Zeichen offenem Text erzeugt.
Temporaere Kapitelzusammenfassung bereit; sie wird nicht gespeichert.
```

Vor dem ersten abgeschlossenen Abschnitt nennt die erste Meldung stattdessen,
dass nur offener Text als Quelle dient. Das Audiolabel beginnt mit
`kapitel-zusammenfassung-temporaer`; persistente Kapitelzusammenfassungen
behalten ihre bisherigen Labels.

## Noch offene Schritte

1. echtes Laufzeitverhalten der Summary-Laengensteuerung auf dem Pi verifizieren
2. bei Bedarf explizite `chapter_completed`-/`summary_completed`-Events ableiten
3. weitere Fehlerfaelle fuer Google-Cloud-ADC, Projektkonfiguration oder
   Netzwerk noch feiner rueckmelden

## Relevante Dateien

- [abr/control/runtime.py](../abr/control/runtime.py)
- [abr/control/frontpanel.py](../abr/control/frontpanel.py)
- [abr/control/audio_volume.py](../abr/control/audio_volume.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)

## Asynchrone NFC-Abfrage und Buchorientierung

Der Startpfad verwendet fuer das PN5180-Gateway den zweistufigen Ablauf:

1. direkt beim Druecken von `Start / Stop / NFC`: `STATUS_START`
2. Aufnahme beider Kamerabilder
3. unmittelbar vor Bildvorbereitung/OCR: `STATUS_FETCH`

Die Auswahl danach ist:

- `ISO14443A` ist der fuehrende Buchschluessel
- Reader 2 mit ISO14443A wird als Orientierung 1 gemeldet
- Reader 1 mit ISO14443A wird als Orientierung 2 gemeldet
- bei Orientierung 1 bleibt die aufgenommene Links-/Rechts-Zuordnung erhalten
- bei Orientierung 2 werden die beiden Seitendateien unmittelbar nach
  `STATUS_FETCH` und vor der Bildvorbereitung vertauscht
- danach wird `case/right.jpg` direkt um 180 Grad gedreht; dadurch ist die
  Korrektur auch im Camera-Testserver unter `entzerrte Bilder` sichtbar
- die OCR-Vorverarbeitung fuehrt keine weitere Seitendrehung aus
- nur ISO15693: Zuordnung ueber vorhandene
  `iso15693_tag_ids.txt`; Standardorientierung wie Reader 2

Die ISO15693-Only-Orientierung ist mit
`--iso15693-only-orientation reader1|reader2` umstellbar.

## Gekapselter Neural2-Testpfad

Die produktive Seitenausgabe bleibt:

- Backendname `google`
- Klasse `GoogleCloudTTSBackend`
- Stimme `de-DE-Standard-H`
- Standard ohne zusaetzliche CLI-Option

Der Opt-in-Pfad `google-standard-enhanced` verwendet ebenfalls
`GoogleCloudTTSBackend` und `de-DE-Standard-H`. Nur die Runtime-Aufbereitung
unterscheidet sich: Sie strukturiert Absaetze und Saetze mit SSML, behaelt
die Kapitelpause und hebt kurze Ueberschriften moderat hervor. Bei einem
Fragesatz wird das vollstaendige letzte Wort mit
`<prosody pitch="+3st">` markiert.
Nach jedem Satz innerhalb eines Absatzes wird
`<break time="900ms"/>` eingefuegt. Der letzte Satz eines Absatzes erhaelt
stattdessen `<break time="2000ms"/>`; beide Pausen werden nicht addiert.
Neben den Leerzeilen aus dem Page-Ingest erkennt der Renderer als Fallback
auch einfache Zeilenumbrueche nach `.` oder `?`; schliessende
Anfuehrungszeichen zwischen Satzzeichen und Umbruch sind erlaubt.
Ist der vorherige Absatz ein vollstaendig in `"..."`, `»...«` oder `„...“`
eingerahmter Dialogsatz, wird die folgende Absatzgrenze ausnahmsweise wie eine
Satzgrenze behandelt und erhaelt nur `900ms` Pause.
Eine Validierung stellt sicher, dass die Wortfolge nicht veraendert wird;
bei einem Fehler wird die bisherige SSML-Aufbereitung benutzt. Der Default
`google` bleibt unangetastet.

Der Neural2-Versuch ist davon getrennt:

- Backendname `google-neural2`
- Klasse `GoogleNeural2TTSBackend`
- Defaultstimme `de-DE-Neural2-H`
- Aktivierung nur mit
  `--page-tts-backend google-neural2`

Beide Pfade behalten die vorhandenen SSML-Kapitelpausen. Durch Weglassen des
Schalters oder `--page-tts-backend google` wird ohne Migration oder
Datenanpassung auf den bisherigen Pfad zurueckgeschaltet.

Zusaetzlich existiert ein dritter, ebenfalls gekapselter Versuchspfad:

- Backendname `google-gemini-flash`
- Klasse `GoogleGeminiFlashTTSBackend`
- Modell `gemini-2.5-flash-tts`
- Defaultstimme `Charon`
- getrennte Felder fuer gesprochenen Text und Hoerbuch-Stilprompt
- Aktivierung nur mit
  `--page-tts-backend google-gemini-flash`

Gemini TTS erhaelt Klartext statt SSML. Der vorhandene Geschwindigkeitswert
wird als natuerlichsprachliche Tempovorgabe an den Prompt angehaengt. Text und
Prompt werden getrennt gegen das jeweilige `4000`-Byte-Limit geprueft.

Auch von diesem Pfad fuehrt `--page-tts-backend google` beziehungsweise das
Weglassen der Option direkt und ohne Datenmigration zu
`de-DE-Standard-H` zurueck.

## Schutz gegen falsche Seitenfolge

`RuntimeController` fuehrt pro Buch einen fluechtigen Zustand aus:

- Seitenzahlen des zuletzt zur Wiedergabe angenommenen Scans
- Scan-ID, damit linkes und rechtes inkrementelles Ingest-Ergebnis als eine
  Doppelseite behandelt werden
- Bestaetigungsmerker fuer Rueckwaertsblaettern und Seitenwiederholung
- unterdrueckte Scan-IDs, damit nach einer Warnung auch das zweite
  Teilergebnis desselben Scans nicht ausgegeben wird

Bei einer Ueberschneidung mit der letzten Doppelseite wird
`repeat_page.wav`, bei einer kleineren minimalen Seitenzahl
`wrong_direction.wav` abgespielt. Die Seitenausgabe wird jeweils nicht
eingeplant. Ein neuer Scan verbraucht den passenden Bestaetigungsmerker und
darf die beanstandete Pruefung einmal passieren. Der
Rueckwaerts-Bestaetigungsmerker garantiert die Ausgabe des neuen Scans.
Scans ohne Seitenzahl bleiben von den Pruefungen ausgenommen.

Anders als allgemeine Systemhinweise werden diese beiden Warnungen synchron
im Page-Ingest-Callback abgespielt. Damit ist die Warnung abgeschlossen,
bevor das Ergebnis verworfen wird. Die Runtime protokolliert
`Seitenfolge-Hinweis startet` und `Seitenfolge-Hinweis abgeschlossen`; ein
Wiedergabefehler nennt stattdessen den fehlenden oder unlesbaren Audiopfad.

Zwischen OCR links und dem Start der rechten Bildverarbeitung liegt im
inkrementellen Pfad eine Synchronisationsstelle: `PageIngestService.submit`
liefert ein Completion-Event, auf das der Capture-Runner wartet. Eine
Seitenfolge-Warnung ruft `ForegroundJobManager.cancel_current_job()` auf.
Der wartende Runner erkennt das Cancel-Event, wirft
`ForegroundJobCancelled` und startet OCR rechts nicht mehr. Das
`CANCELLED`-Jobereignis setzt die Runtime anschliessend auf `IDLE`.

## Segmentierung langer Summary-Audios

`PageAudioPlayer.enqueue_text()` prueft fuer die Google-Pfade die Bytegroesse
der tatsaechlich gerenderten Eingabe, also bei
`google-standard-enhanced` einschliesslich SSML. Zusammenfassungen werden
bereits oberhalb von `900` Byte geteilt; `3800` Byte bleibt die allgemeinere
Google-Sicherheitsgrenze. Der Text wird bevorzugt an vollstaendigen
Satzgrenzen geteilt. Nur ein
einzelner ueberlanger Satz faellt auf wortweise Teilung zurueck.

Alle Segmente werden als getrennte Utterances derselben Generation
eingereiht und vom bestehenden Prefetch-/Playback-Worker nacheinander
synthetisiert und abgespielt. Die Labels lauten beispielsweise
`was-bisher-geschah:1/3` bis `:3/3`. Damit kann eine lange Zusammenfassung
nicht mehr als einzelne zu grosse Google-TTS-Anfrage enden.

Summary-Intro und erstes `bing` werden synchron vor dem Start des
Summary-Jobs wiedergegeben. Sobald `PageAudioPlayer` aktiv ist, verwirft der
Systemaudio-Worker noch wartende Heartbeat-Eintraege. So kann kein bereits
freigegebener Heartbeat hinter der Summary-Wiedergabe auf dem globalen
Audio-Lock warten.

Vor der Wiederverwendung von `book_so_far_summary.json` berechnet der
`SummaryManager` einen SHA-256-Fingerabdruck aus IDs, `updated_at` und Text
der verwendeten Kapitelzusammenfassungen. Die bisherige reine Prüfung der
Kapitel-IDs konnte einen veralteten kurzen Buch-Summary-Cache nicht
erkennen. Fehlt oder unterscheidet sich der Fingerabdruck, wird die
Buchzusammenfassung neu erzeugt. Der Runtime-Log nennt zusätzlich den
exakten Summary-Pfad und die Zeichenanzahl des an die Audioausgabe
übergebenen Texts.

## Vollstaendigkeit von Gemini-Zusammenfassungen

Eine `generateContent`-Antwort darf nicht allein deshalb gespeichert werden,
weil sie bereits Text enthaelt. Meldet ein Kandidat
`finishReason=MAX_TOKENS`, ist dieser Text unvollstaendig und kann sogar
mitten im Wort enden. `GeminiSummaryBackend` verwirft einen solchen Teiltext
und wiederholt die Anfrage einmal ohne das aus `target-pages` abgeleitete
`maxOutputTokens`. Nur eine nicht abgebrochene Antwort wird zurueckgegeben.
Ein erneut abgebrochener Versuch fuehrt zu einem Fehler statt zu einer
beschaedigten Cache-Datei.

Neue Kapitel- und Buch-Summaries tragen in ihren Metadaten
`generation_complete=true`. Alte Dateien ohne diesen Merker werden nicht
mehr als gueltiger Cache behandelt und beim naechsten Summary-Aufruf einmalig
neu erzeugt. In Fehlerdetails werden, soweit von Vertex AI geliefert,
`promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount` und
`totalTokenCount` ausgegeben.

Die fachliche Laenge wird nicht mehr ueber dieses technische Tokenlimit
gesteuert. `target-pages` wird stattdessen mit `250` Woertern pro Seite in
eine konkrete Wortobergrenze uebersetzt. Die erste Gemini-Anfrage nennt diese
Grenze im Prompt und erhaelt bis zu `2048` technische Ausgabetokens. Liegt
das Ergebnis mehr als zehn Prozent ueber dem Ziel, wird es in einer zweiten
Gemini-Anfrage gezielt gekuerzt. Bleibt es auch danach oberhalb der Toleranz,
wird es nicht gespeichert. Die JSON-Metadaten halten Zielwortzahl sowie
Wortzahl vor und nach einer eventuellen Kuerzung fest.
