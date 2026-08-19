# Laufzeit- und Datenarchitektur für Bücher

Stand: `2026-08-19`

English version: [Book Runtime and Data Architecture](../docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)

## Zweck

Dieses Dokument beschreibt die persistente Datenhaltung und die Verarbeitung
eines Buches von der NFC-Identifikation bis zu vorlesbaren Seiten, künstlichen
Abschnitten und Zusammenfassungen.

Die maßgeblichen Komponenten sind:

- `BookSessionResolver`
- `BookStore`
- `PageIngestor` und `PageIngestService`
- `ChapterAssembler`
- `SummaryManager`
- `SummaryService` als optionale asynchrone Hilfskomponente

## Grundprinzip

Die Runtime trennt flüchtigen Laufzeitstatus (Eingaben, laufende Jobs und
Audio) von dauerhaftem Buchstatus. Alle dauerhaften Daten eines Buches liegen
unter `library/<tag_id>/`.

Ein ISO14443A-NFC-Tag wird als Buchschluessel bevorzugt. Zusätzliche
ISO15693-IDs können demselben Buch als Aliase zugeordnet werden. Enthaelt ein
Scan ohne ISO14443A genau einen unbekannten ISO15693-Tag, wird dessen ID zum
Schluessel eines neu angelegten Buchs. Ein Buch wird
außerdem dauerhaft an das beim ersten Einlesen aktive Sprachprofil `de` oder
`en` gebunden. Alte `book.json`-Dateien ohne `language` gelten als deutsch und
werden beim nächsten deutschen Zugriff entsprechend ergänzt. Gemischte
Buch-, OCR-, Seiten-, Kapitel- oder Summary-Daten werden abgewiesen.

## Verzeichnisstruktur pro Buch

```text
library/
  <tag_id>/
    book.json
    iso15693_tag_ids.txt
    state/
      chapter_assembler_state.json
      page_orientation.json
      pending_right_tail_fragment.json
    scans/
      <scan_id>/
        manifest.json
    pages/
      0008.json
      0009.json
      page_1.json
    chapters/
      chapter_0001/
        chapter.json
        text.txt
    summaries/
      chapter_0001_summary.json
      book_so_far_summary.json
```

- Seiten mit erkannter Seitenzahl erhalten einen vierstellig aufgefüllten
  Dateinamen. Ohne Seitenzahl wird die bereinigte `page_id` vorlaeufig
  verwendet. Liefert die zweite Seite eine Zahl, wird die Gegenseite anhand
  ihrer Links-/Rechts-Lage abgeleitet und beide Platzhalter werden durch
  nummerierte Dateien ersetzt.
- `iso15693_tag_ids.txt` enthält eine Alias-ID pro Zeile. Wird nur ein
  bekannter ISO15693-Tag gelesen, werden neue Daten weiter im zugehörigen
  ISO14443A-Buchordner gespeichert.
- `state/page_orientation.json` speichert die letzte zuverlaessige OCR-
  Seitenorientierung (`reader1` fuer vertauschte oder `reader2` fuer
  unveraenderte Zuordnung). Bei einem neuen Buch wird `reader2` initialisiert;
  bei leeren oder textarmen Seiten dient der Wert als Fallback.
- JSON- und Textdateien werden atomar über eine temporäre Datei ersetzt.

## Persistente Datenobjekte

### `BookRecord` in `book.json`

- `tag_id`, `created_at`, `last_seen_at`
- optionale bibliografische Angaben `title` und `author`
- `language`: dauerhaftes Buchprofil `de` oder `en`

### `ScanRecord` in `scans/<scan_id>/manifest.json`

- `scan_id`, `created_at`, `session_dir`
- optionale Pfade `capture_dir`, `ocr_dir` und `report_path`
- `left_page_id` und `right_page_id`
- Metadaten, unter anderem OCR-Sprache, Orientierung und Pipeline-Zeiten

Die gespeicherten Pfade verweisen auf Laufzeitartefakte außerhalb des
Buchordners und können nach einer Bereinigung dieser Artefakte historisch
werden. Die fachlichen Seitendaten bleiben davon unberührt.

### `PageRecord` in `pages/<key>.json`

- Identität und Herkunft: `page_id`, `scan_id`, `created_at`, `side`
- Inhalte: `clean_text`, `speak_text`
- Struktur: `page_number`, `chapter_number`, `chapter_heading`,
  `chapter_markers[]`
- Seitenübergang: `tail_fragment`
- Herkunft und Diagnose: `source_report_path`, `metadata`

`clean_text` ist der fachlich bereinigte, möglichst originalgetreue Text.
`speak_text` ist die für TTS aufbereitete Fassung; beide dürfen bewusst
voneinander abweichen. `metadata.language` kennzeichnet das Sprachprofil.

### `ChapterRecord` in `chapters/<chapter_id>/chapter.json`

- `chapter_id`, `created_at`, `completed_at`, `text_path`
- `page_ids`, `page_numbers`, `start_page`, `end_page`
- optionale erkannte `chapter_number` und `chapter_heading`
- optionale `summary_path`
- Metadaten zu Start-, End- und Folgegrenze, Grenztyp, Seitenumfang und
  Sprache

Der zusammengesetzte Abschnittstext liegt daneben in `text.txt`.

### `SummaryRecord` in `summaries/*.json`

- `summary_id`, `summary_type`, `updated_at`, `text`
- `source_chapter_ids`, `model_name`, `metadata`

Persistiert werden Abschnittszusammenfassungen und die Buchrückschau. Die
temporäre Rückschau des noch offenen Abschnitts existiert nur im Speicher.

## Seiten-Ingest

Der `PageIngestor` prüft zunächst, ob OCR-Bericht, aktives Sprachprofil und
bereits gespeichertes Buch zusammenpassen. Anschließend verarbeitet er den
OCR-Bericht fachlich weiter:

- Seitenzahlen erkennen; bei einer vollständigen Doppelseite eine fehlende
  Zahl aus der Gegenseite mit `-1` beziehungsweise `+1` ableiten
- Footer-Artefakte in der Seitennummernzone ausfiltern
- Kapitelmarker wie `Kapitel X`, isolierte Kapitelnummern, reine
  Überschriftenseiten und mehrere Marker auf einer Seite erkennen
- Seitenzahl aus `clean_text` und `speak_text` entfernen
- Kapitelzahlen im `speak_text` als Kardinalzahl formulieren
- Worttrennungen innerhalb einer Seite und über Seitenkanten reparieren
- gesperrte Buchstabenfolgen ab drei Buchstaben zusammenziehen
- kurze Versalüberschriften nur für TTS in Wortanfangsgroßschreibung
  umwandeln und als eigenen Absatz behandeln
- Absatzgrenzen aus den OCR-`layout_blocks` übernehmen
- unvollständige Satzreste erkennen und über Seiten hinweg verschieben
- kurze eingeklammerte OCR-Artefakte mit Ziffern wie `(r9or)` nicht als
  Satzrest weiterreichen

Nur im deutschen `speak_text` gelten derzeit die Ausspracheausnahmen `Dr.` →
`Doktor` und `Notre-Dame` → `Notre Damm`. `clean_text` sowie englische Bücher
bleiben unverändert. Bereits gespeicherte Seiten werden nicht rückwirkend
migriert, sondern erst bei erneutem Ingest neu aufbereitet.

### Fehlende Seitenzahl

Kann keine Zahl ermittelt werden, bleibt `page_number = null` und die Datei
wird nach der `page_id` benannt. Eine früh ingestierte linke Einzelseite leitet
ihre Nummer nicht aus älteren Seiten ab; sie übernimmt lediglich einen zuvor
gespeicherten rechten Satzrest.

### Kapitelmarker

`chapter_markers[]` ist die führende Struktur und kann mehrere Marker
enthalten. Die Felder `chapter_number` und `chapter_heading` spiegeln aus
Kompatibilitätsgründen nur den ersten Marker. Eine reine Überschriftenseite
kann als `heading_only_page` erhalten bleiben.

### Satzreste und Seitenübergänge

`tail_fragment` enthält den unvollständigen Satzrest einer Seite:

- Ein linker Satzrest wird aus der frühen linken Seitenausgabe entfernt und
  an die rechte Seite derselben Doppelseite verschoben.
- Ein rechter Satzrest wird an die nächste linke Seite angehängt und zusätzlich
  in `state/pending_right_tail_fragment.json` gespeichert.
- Fehlt rechts ein Satzrest, wird dieser Pending-State aktiv geleert.

## Audioausgabe

Die Runtime liest `speak_text`, nicht den rohen OCR-Text. SSML-Pausen werden
erst bei der Audioausgabe erzeugt und nicht in den Seiten-JSONs gespeichert.

Beim Backend `google-standard-enhanced` gelten:

- `900 ms` nach einem abgeschlossenen Satz innerhalb eines Absatzes
- `2000 ms` am Absatzende
- nach einem vollständig eingerahmten Dialogsatz nur die Satzpause, auch wenn
  anschließend im Buch ein neuer Absatz beginnt
- `1350 ms` nach moderat hervorgehobenen, aus Versalien normalisierten
  Überschriften und nach Kapitelansagen
- `700 ms` nach normalen kurzen Überschriften

Erzeugt OCR zwar ein formal gültiges Ergebnis, aber keine vorlesbare Seite,
werden die `PageRecord`s trotzdem gespeichert. Statt Seitentext spielt die
Runtime abhängig vom Sprachprofil `system_audio/messages/de/empty_page.wav`
oder `system_audio/messages/en/empty_page.wav`; der Job endet sauber.

## Abschnittsbildung

Der `ChapterAssembler` arbeitet auf den gespeicherten `PageRecord`s:

1. Er beginnt an der persistenten Grenze in
   `state/chapter_assembler_state.json`.
2. Zwischen Seite 10 und 20 beendet er den Abschnitt an der ersten erkannten
   Kapitelgrenze.
3. Ohne solche Grenze verwendet er den letzten vollständigen Absatz der
   20. Seite.
4. Die Folgegrenze kann mitten auf einer Seite liegen und wird mit Offset
   gespeichert.
5. Er schreibt `ChapterRecord` und `text.txt` und prüft dabei die einheitliche
   Buch- und Seitensprache.

`collect_pending_content()` liefert zusätzlich den Text von der offenen
Grenze bis zur neuesten Seite, ohne einen Abschnitt zu speichern.

## Zusammenfassungen

Der `SummaryManager` verwendet standardmäßig `gemini-3.5-flash` über Google
Cloud und denselben ADC-/Service-Account-Mechanismus wie die übrigen
Google-Cloud-Zugriffe.

- Zielgrößen werden in Textseiten angegeben; eine Zielseite entspricht 250
  Wörtern.
- Der Klassen- und Kommandozeilenstandard beträgt `1.5` Seiten für Abschnitt
  und Buchrückschau. Die ausgelieferte systemd-Unit setzt beide Werte aktuell
  explizit auf `0.75` Seiten.
- Überschreitet ein Ergebnis das Wortziel um mehr als zehn Prozent, folgt ein
  Kürzungsdurchlauf. Ein weiterhin zu langes Ergebnis wird nicht gecacht.
- Metadaten halten unter anderem Zielgröße, Wortzahlen, Policy-Version,
  Tokenbudget, Abschlussstatus und Sprache fest.
- Alte Caches werden bei geänderter Zielgröße oder Sprache neu erzeugt.
- Die Buchrückschau wird außerdem neu erzeugt, wenn sich Kapitelliste oder
  Inhalt/Aktualisierungszeit einer Abschnittszusammenfassung ändern. Dazu wird
  ein SHA-256-Fingerabdruck gespeichert.
- Liefert Gemini wegen eines Ausgabelimits keinen vollständigen Text, wird die
  Anfrage einmal ohne `maxOutputTokens` wiederholt.

Nach dem Schreiben eines neuen Abschnitts erzeugt der produktive Runtime-Pfad
sofort dessen Zusammenfassung und aktualisiert bei Bedarf
`book_so_far_summary.json`.

### Temporäre Rückschau des offenen Abschnitts

Bei der Kapitel-/Letzte-Seiten-Taste werden zunächst alle inzwischen
abschließbaren Abschnitte gebildet. Danach wird der offene Text ab der
persistierten Grenze gesammelt:

- Ohne offenen Text wird die letzte persistente Abschnittszusammenfassung
  geladen oder erzeugt.
- Mit offenem Text kombiniert `summarize_chapter_progress()` die letzte
  persistente Abschnittszusammenfassung mit dem neuen Text.
- Vor dem ersten fertigen Abschnitt dient nur der offene Text als Quelle.

Der resultierende Typ `temporary_chapter_progress` wird direkt zur
Audioausgabe weitergereicht und nicht gespeichert. Seine Metadaten enthalten
unter anderem `pending_page_ids`, `pending_page_numbers`,
`pending_text_characters` und `temporary=true`.

`SummaryService` kapselt weiterhin eine testbare asynchrone Queue, ist im
produktiven `hardware/control_panel_service.py` jedoch nicht der primäre Pfad.

## Offene Validierungs- und Ausbaupunkte

- Abschnittsheuristiken mit weiteren realen Büchern prüfen
- Promptlänge und Modellwahl anhand praktischer Ergebnisse feinjustieren
- bei Bedarf Telemetrie oder Statusereignisse für Abschnitt und Summary
  ergänzen

## Relevante Dateien

- [abr/book/models.py](../abr/book/models.py)
- [abr/book/store.py](../abr/book/store.py)
- [abr/book/session.py](../abr/book/session.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/chapter_assembler.py](../abr/book/chapter_assembler.py)
- [abr/book/summary_manager.py](../abr/book/summary_manager.py)
- [abr/control/runtime.py](../abr/control/runtime.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)
- [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)
- [deploy/abr-control-panel.service](../deploy/abr-control-panel.service)
