# Development Roadmap

Stand: `2026-07-06`

## Erreichte Meilensteine

Folgende Bloecke sind bereits produktionsnah implementiert:

- `Raspberry Pi 5` als Hauptrechner
- realer Zwei-Kamera-Capture
- getrennte Beleuchtung links/rechts
- `RapidOCR` auf dem Pi
- `Google Cloud TTS`
- Audioausgabe ueber `MAX98357A`
- NFC-Buchidentifikation ueber `PN5180`-Gateway
- asynchroner PN5180-Startpfad mit `STATUS_START` waehrend der Aufnahme und
  anschliessendem `STATUS_FETCH`
- fuehrende ISO14443A-Buch-ID, persistente ISO15693-Aliaszuordnung und
  readerbasierte Buchorientierung
- am realen Aufbau verifizierte Links-/Rechts-Zuordnung und Drehung der
  rechten Seitendatei
- Frontpanel mit `EC11` und drei Funktionstasten
- langlebige Runtime mit Start/Stop, Heartbeat, Seitenausgabe und
  Buch-Loeschdialog
- `BookStore`
- `PageIngestor`
- `ChapterAssembler`
- `SummaryManager`
- verdrahtete Summary-Tasten inklusive Intro-, Heartbeat- und
  Fehlhinweislogik

## Aktuelles naechstes Hauptthema

Der naechste groessere Entwicklungsschritt ist nicht mehr Capture oder GPIO,
sondern:

- Qualitaet, Robustheit und Betriebsreife der Abschnitts- und Summary-Ebene

## Prioritaeten ab jetzt

### Prioritaet 1: Abschnittsheuristiken absichern

Arbeiten:

- Abschnittsgrenzen mit echtem Buchmaterial pruefen
- Fallbacks fuer schwere OCR-Faelle weiter schaerfen
- Umgang mit unklaren Kapitelmarken und Mid-Page-Grenzen nachjustieren

Erfolgskriterium:

- nach mehreren Scans entstehen belastbare Abschnittsobjekte unter
  `library/<tag_id>/chapters/`

### Prioritaet 2: Summary-Qualitaet und -Laenge

Arbeiten:

- Prompting und Modellwahl weiter testen
- Token-Skalierung fuer `target-pages` mit echtem Material kalibrieren
- Fehlerbilder von Gemini sauberer diagnostizieren

Erfolgskriterium:

- es liegen jederzeit direkt abspielbare Summary-Dateien vor

### Prioritaet 3: Telemetrie und Betriebsreife

Arbeiten:

- Status-/Telemetry-Ereignisse fuer neue Abschnitte und Zusammenfassungen
- `systemd`-Dienst
- Logging und Restart-Strategie
- saubere Produktionsdefaults fuer Cleanup und Audio-Hinweise

## Was Bewusst Nicht Das Naechste Thema Ist

- weitere GPIO-Grundarbeit
- neue OCR-Backends
- GUI
- tiefere Kamera-Kalibrierumbauten
- groessere TTS-Auswahlvergleiche

## Praktischer Arbeitsstart fuer den Folgechat

Startpunkte im Code:

- [abr/book/store.py](../abr/book/store.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/models.py](../abr/book/models.py)
- [abr/control/runtime.py](../abr/control/runtime.py)

Konkretes Ziel des Folgechats:

1. Abschnittsgrenzen an echtem Material gegenpruefen
2. Summary-Laenge und Robustheit auf dem Pi feinjustieren
3. danach Telemetrie und Betriebsreife ergaenzen
