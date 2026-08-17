# Book Runtime And Data Architecture

Stand: `2026-07-06`

## Ziel

Dieses Dokument beschreibt den aktuell erreichten Stand der fachlichen
Datenhaltung fuer:

- Buchidentifikation ueber `NFC`
- Speicherung pro Buch
- Speicherung pro gescannter Doppelseite
- normalisierte `PageRecord`s fuer die Seitenausgabe

Es beschreibt ausserdem die neue Abschnitts- und Summary-Ebene:

- `ChapterAssembler`
- `SummaryManager`

## Implementierte Dienste

Aktuell umgesetzt sind:

- `BookSessionResolver`
- `BookStore`
- `PageIngestor`
- `PageIngestService`
- `ChapterAssembler`
- `SummaryManager`
- `SummaryService` als optionale Hilfskomponente

## Grundprinzip

Der aktuelle Runtime-Stand trennt:

1. `volatile runtime`
   - aktuelle Eingaben
   - laufende Jobs
   - Audio
2. `persistent book state`
   - alles unter `library/<tag_id>/`

Der NFC-Tag bleibt dabei der Primaerschluessel eines Buches.

## Verzeichnisstruktur pro Buch

```text
library/
  <tag_id>/
    book.json
    iso15693_tag_ids.txt
    state/
      chapter_assembler_state.json
      pending_right_tail_fragment.json
    scans/
      <scan_id>/
        manifest.json
    pages/
      0008.json
      0009.json
      page_1.json
      page_2.json
    chapters/
      chapter_0001/
        chapter.json
        text.txt
    summaries/
      chapter_0001_summary.json
      book_so_far_summary.json
```

Wichtig:

- `<tag_id>` ist fuer neue Buchdaten die ID des fuehrenden ISO14443A-Tags
- `iso15693_tag_ids.txt` enthaelt alternative ISO15693-IDs, jeweils eine pro
  Zeile; damit kann ein bekanntes Buch auch ohne lesbaren ISO14443A-Tag
  wiedergefunden werden
- wird nur ISO15693 gelesen, durchsucht die Runtime die vorhandenen
  Buchverzeichnisse nach dieser Alias-ID und speichert neue Seiten im
  zugeordneten ISO14443A-Buchordner
- `chapters/` enthaelt abgeschlossene kuenstliche Abschnitte
- `summaries/` enthaelt Abschnitts- und Gesamtzusammenfassungen
- unter `state/chapter_assembler_state.json` liegt die persistente Folgegrenze

## Implementierte Datenobjekte

### `BookRecord`

Datei:

- `book.json`

Enthaelt aktuell mindestens:

- `tag_id`
- `created_at`
- `last_seen_at`

### `ScanRecord`

Ort:

- `scans/<scan_id>/manifest.json`

Enthaelt:

- `scan_id`
- `created_at`
- `session_dir`
- `capture_dir` optional
- `ocr_dir` optional
- `report_path`
- Referenzen auf linke/rechte Seitenobjekte

### `PageRecord`

Ort:

- `pages/<key>.json`

Enthaelt aktuell:

- `page_id`
- `scan_id`
- `created_at`
- `side`
- `clean_text`
- `speak_text`
- `page_number`
- `chapter_number`
- `chapter_heading`
- `chapter_markers[]`
- `tail_fragment`
- `source_report_path`
- `metadata`

Wichtig:

- `clean_text` ist der fachlich bereinigte Text
- `speak_text` ist der fuer Audio gedachte Text
- beide duerfen bewusst voneinander abweichen

## Implementierte `PageIngestor`-Logik

Der `PageIngestor` verarbeitet `report.json` bereits fachlich deutlich weiter
als ein reiner OCR-Import.

Aktuell implementiert:

- Seitenzahl erkennen
- in einem vollstaendigen Doppelseiten-Report fehlende Seitenzahl aus der
  Gegenseite ableiten
- Footer-Artefakte in der Seitennummernzone ausfiltern
- Kapitelmarker erkennen:
  - explizite `Kapitel X`
  - isolierte Kapitelnummern
  - reine Ueberschriftenseiten
  - mehrere Marker auf einer Seite
- `clean_text` ohne Seitenzahl erzeugen
- `speak_text` getrennt erzeugen
- im deutschen `speak_text` Ausspracheausnahmen anwenden: `Dr.` wird
  `Doktor`, `Notre-Dame` wird `Notre Damm`; `clean_text` und englische
  Buchprofile bleiben unveraendert; bereits gespeicherte Seiten werden nicht
  automatisch migriert und erhalten die Ersetzung erst beim erneuten Ingest
- Kardinalzahlen fuer Kapitelansagen im `speak_text`
  - Beispiel: `Kapitel zwei.` statt `Kapitel 2.`
- Worttrennungen ueber Zeilen im `speak_text` reparieren
- gesperrte Buchstabenfolgen ab drei Buchstaben zusammenziehen:
  `U E B E R` wird zu `UEBER`; Satzzeichen und nachfolgender Abstand bleiben
  erhalten, Zeilen- und Absatzgrenzen werden nicht verbunden
- kurze, vollstaendig grossgeschriebene Ueberschriften nur im `speak_text`
  in Wort-fuer-Wort-Grossschreibung umwandeln, beispielsweise
  `ERLEBNIS IN DER KNABENZEIT` zu `Erlebnis In Der Knabenzeit`; `clean_text`
  bleibt originalgetreu
- diese Ueberschriften durch eine Leerzeile vom folgenden Fliesstext trennen,
  damit die Runtime sie als eigenen Absatz und Kapitelgrenze behandeln kann
- Absatzgrenzen aus den `layout_blocks` des OCR-Reports uebernehmen:
  Zeilen innerhalb eines Absatzes bleiben einfach getrennt, zwischen zwei
  Absatzbloecken steht in `speak_text` eine Leerzeile
- Satzreste als `tail_fragment` speichern
- kurze eingeklammerte OCR-Artefakte mit Ziffern wie `(r9or)` weder als neuen
  `tail_fragment` speichern noch aus bereits gespeicherten Seitendaten auf
  die Folgeseite uebernehmen
- Satzreste ueber Seiten hinweg verschieben
- Worttrennungen ueber die linke/rechte Seitenkante reparieren

## Seitenlogik im Detail

### Seitenzahl

Wenn nur eine der beiden Seitenzahlen erkannt wird:

- links erkannt -> rechts `+1`
- rechts erkannt -> links `-1`

Das gilt nur, wenn beide Seiten des Doppelseiten-Reports gemeinsam vorliegen.

Wenn gar keine Seitenzahl erkannt wird:

- die Seite bleibt mit `page_number = null` erhalten
- als Dateiname wird dann `page_id` verwendet, z.B. `page_1.json`

Sonderfall im aktuellen Runtime-Pfad:

- wird eine linke Einzelseite frueh ingestiert und ihre Seitenzahl fehlt,
  erfolgt **keine** Ableitung aus aelteren `PageRecord`s
- stattdessen wird nur der zuletzt gespeicherte Satzrest der vorherigen rechten
  Seite aus `state/pending_right_tail_fragment.json` verwendet

### Kapitelmarker

Gespeichert werden:

- `chapter_number`
- `chapter_heading`
- `chapter_markers[]`

Dabei gilt:

- `chapter_markers[]` ist die fuehrende Struktur
- `chapter_number` und `chapter_heading` spiegeln nur den ersten Marker
- mehrere Kapitelmarker auf einer Seite sind zulaessig

### Reine Ueberschriftenseiten

Beispiel:

- `INTERMEZZO`

Diese Seiten koennen als `heading_only_page` erkannt werden. Sie bleiben als
fachliche Seite erhalten, werden aber nicht mit beliebigen Satzrest-Heuristiken
vermischt.

### `tail_fragment`

`tail_fragment` speichert den unvollstaendigen Satzrest einer Seite.

Aktueller Stand:

- rechter Satzrest einer Doppelseite wird an die naechste linke Seite
  angehaengt
- derselbe rechte Satzrest wird zusaetzlich in
  `state/pending_right_tail_fragment.json` gespeichert
- ist auf der rechten Seite kein Satzrest vorhanden, wird dieser Pending-
  Speicher aktiv geleert
- linker Satzrest wird aus der linken Seitenausgabe entfernt und an die rechte
  Seite derselben Doppelseite verschoben
- Worttrennungen ueber diese Uebergaenge bleiben repariert

## Audio-Relevanz der gespeicherten Daten

Die Runtime liest nicht direkt rohen OCR-Text, sondern `speak_text`.

Dabei gilt:

- `clean_text` bleibt der technische/fachliche Seiteninhalt
- `speak_text` ist bereits fuer TTS vorbereitet
- die zusaetzlichen SSML-Pausen vor und nach Kapitelansagen werden erst in der
  Runtime erzeugt, nicht in der gespeicherten JSON-Datei
- `google-standard-enhanced` verwendet innerhalb eines Absatzes `900ms`
  Satzpause und am Absatzende `2000ms`; eine Absatzgrenze direkt nach einem
  vollstaendig eingerahmten Dialogsatz wird nur als Satzgrenze gewertet
- beim Backend `google-standard-enhanced` erhalten die aus Grossbuchstaben
  normalisierten Ueberschriften nach der moderaten Hervorhebung dieselbe
  `1350ms`-Pause wie eine Kapitelansage; normale kurze Ueberschriften behalten
  die bisherige `700ms`-Pause

## Sonderfall: keine vorlesbaren Seiten

Wenn OCR formal ein `report.json` liefert, aber daraus nur leere `speak_text`-
Seiten entstehen:

- die `PageRecord`s werden trotzdem gespeichert
- die Runtime startet keine Seitenausgabe
- stattdessen wird je nach aktivem Sprachprofil
  `system_audio/messages/de/empty_page.wav` oder
  `system_audio/messages/en/empty_page.wav` abgespielt
- andere Fehlerpfade verwenden weiterhin `fehler.wav`
- der Heartbeat endet sauber

## Was Noch Fehlt

### `ChapterAssembler`

Ist jetzt vorhanden.

Aktueller Stand:

- beobachtet neue `PageRecord`s indirekt ueber den Runtime-Pfad
- beendet einen Abschnitt an der ersten erkannten Kapitelgrenze im Fenster
  `10..20` Seiten
- faellt sonst auf den letzten vollstaendigen Absatz der `20.` Seite zurueck
- speichert die Folgegrenze persistent, auch wenn sie mitten auf einer Seite
  liegt
- schreibt `ChapterRecord`s und `text.txt` unter `chapters/`

### `SummaryManager`

Ist jetzt vorhanden.

Aktueller Stand:

- erzeugt Abschnittszusammenfassungen ueber Gemini auf Google Cloud
- verwendet dafuer denselben ADC-/Service-Account-Pfad wie der aktuelle
  TTS-Backend-Zugriff
- verwendet konfigurierbare Zielgroessen in Textseiten, Standard `1.5` fuer
  Abschnitt und Buchrueckschau
- rechnet eine Zielseite in `250` Woerter um und nennt die konkrete
  Wortobergrenze im Prompt
- verwendet ein grosszuegiges technisches Tokenbudget, damit Thinking-Tokens
  die sichtbare Zusammenfassung nicht vorzeitig abschneiden
- startet bei mehr als zehn Prozent Ueberschreitung automatisch einen
  gezielten Kuerzungsdurchlauf
- verwirft auch das gekuerzte Ergebnis, falls es weiterhin oberhalb der
  Zehn-Prozent-Toleranz liegt, statt einen ueberlangen Cache zu speichern
- speichert sie unter `summaries/`
- speichert Metadaten wie `target_pages`, `target_words`,
  `initial_word_count`, `actual_word_count`, `length_policy_version` und
  `max_output_tokens`
- erzeugt Abschnittszusammenfassungen fuer neue Abschnitte im produktiven
  Runtime-Pfad sofort nach dem Schreiben des `ChapterRecord`
- aktualisiert bei Bedarf eine Gesamtzusammenfassung "Was bisher geschah"
- erzeugt fuer die Kapitel-/Letzte-Seiten-Taste bei vorhandenem offenem Text
  eine `temporary_chapter_progress`-Zusammenfassung aus der letzten
  persistenten Abschnittszusammenfassung und dem Text seit der offenen
  `ChapterAssembler`-Grenze
- erzeugt vor dem ersten fertigen Abschnitt dieselbe temporaere Rueckschau
  allein aus dem offenen Text
- gibt diese temporaere `SummaryRecord` nur im Speicher zurueck; es wird keine
  JSON-Datei unter `summaries/` geschrieben und die persistente
  Abschnittszusammenfassung bleibt unveraendert
- erzeugt alte Summary-Dateien automatisch neu, wenn sich `target-pages` oder
  bei der Buchrueckschau die zugrundeliegende Kapitelliste geaendert hat
- speichert fuer Buchrueckschauen einen SHA-256-Fingerabdruck aus Kapitel-ID,
  `updated_at` und Text aller Abschnittszusammenfassungen
- erzeugt den Buch-Summary-Cache auch bei unveraenderten Kapitel-IDs neu,
  sobald sich Inhalt oder Aktualisierungszeit einer Abschnittszusammenfassung
  geaendert haben; alte Cache-Dateien ohne Fingerabdruck werden einmalig
  erneuert
- wiederholt eine Anfrage einmal ohne `maxOutputTokens`, wenn Gemini zwar
  antwortet, aber keinen vollstaendigen Textteil liefert

#### Temporaere Zusammenfassung des offenen Abschnitts

Beim Druck auf `Kapitel-/Letzte-Seiten-Zusammenfassung` gilt folgende
Reihenfolge:

1. `ChapterAssembler.assemble_available_chapters()` schliesst zuerst alle
   inzwischen vollstaendig gewordenen Abschnitte ab.
2. `ChapterAssembler.collect_pending_content()` liest danach den Text von
   `current_start` in `state/chapter_assembler_state.json` bis zum Ende der
   neuesten Seite. Ein Offset innerhalb einer Seite wird beruecksichtigt.
3. Ohne offenen Text wird wie bisher die letzte persistente
   Abschnittszusammenfassung geladen oder erzeugt.
4. Mit offenem Text laedt `SummaryManager.summarize_chapter_progress()` die
   persistente Zusammenfassung des letzten fertigen Abschnitts und laesst
   Gemini beide Quellen zu einer aktuellen Rueckschau verdichten.
5. Existiert noch kein fertiger Abschnitt, ist nur der offene Text die Quelle.
6. Der zurueckgegebene `SummaryRecord` hat den Typ
   `temporary_chapter_progress`, wird unmittelbar an `PageAudioPlayer`
   uebergeben und danach verworfen.

Die temporaere Summary enthaelt im Speicher Metadaten wie
`pending_page_ids`, `pending_page_numbers`, `pending_text_characters` und
`temporary=true`. Weder diese Summary noch eine Aenderung der persistenten
Abschnittszusammenfassung wird auf Datentraeger geschrieben. Wiederholtes
Druecken der Taste erzeugt deshalb jeweils eine neue aktuelle Gemini-Antwort.

### `SummaryService`

Existiert weiterhin im Repo.

Aktueller Status:

- kapselt eine asynchrone Queue fuer Abschnittszusammenfassungen
- ist weiterhin testbar und nutzbar
- wird im aktuellen produktiven `hardware/control_panel_service.py` aber nicht
  als primaerer Pfad verwendet

## Empfohlene naechste Umsetzungsstufe

Sinnvolle naechste Schritte sind jetzt:

1. echte Buchlaeufe gegen die Abschnittsheuristiken testen
2. Prompt-Laenge und Modellwahl fuer Gemini feinjustieren
3. spaetere Telemetrie oder Status-Events fuer Abschnitt/Summary ergaenzen

## Relevante Dateien

- [abr/book/store.py](../abr/book/store.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/models.py](../abr/book/models.py)
- [abr/book/session.py](../abr/book/session.py)
- [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)
