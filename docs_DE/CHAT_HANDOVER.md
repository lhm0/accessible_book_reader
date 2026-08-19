# Chat Handover

Stand: `2026-08-19`

## Zweck

Dieses Dokument ist die Uebergabe fuer einen neuen Codex-Chat. Es beschreibt
den tatsaechlich erreichten Arbeitsstand, nicht nur Zielbilder.

Projekt:

- Repository: `abr`
- Arbeitsverzeichnis auf dem Mac: `~/src/abr`
- Pi-Referenzpfad: `~/src/abr`

## Kurzfassung

Der aktuelle produktionsnahe Pfad auf dem Raspberry Pi 5 ist:

1. Frontpanel-Eingabe ueber `Start / Stop / NFC`, `Buch-Zusammenfassung`,
   `Kapitel-/Letzte-Seiten-Zusammenfassung` und `EC11`
2. NFC-Tag-Lesen ueber das `PN5180`-Gateway
3. reale Doppelaufnahme mit getrennter Beleuchtung links/rechts
4. Buch ueber NFC zuordnen und Orientierung schnell aus drei RapidOCR-
   Textzeilen der linken Aufnahme bestimmen
5. beide Seiten korrekt zuordnen, dann links vor rechts verarbeiten
6. fuer links zuerst: Bildvorbereitung, OCR, `PageIngestor`, TTS
7. fuer rechts danach dieselben Schritte waehrend die linke Seite bereits
   abgespielt wird
8. automatische Seitenausgabe per TTS

Die Runtime dafuer ist inklusive Abschnitts- und Summary-Ebene implementiert.
Neu hinzugekommen sind:

- `ChapterAssembler` fuer kuenstliche 10-20-Seiten-Abschnitte
- `SummaryManager` fuer Gemini-Zusammenfassungen ueber denselben
  Google-Cloud-ADC-Pfad wie TTS
- `SummaryService` bleibt als Hilfskomponente im Repo, ist im produktiven
  `control_panel_service` aktuell aber nicht mehr der Standardpfad
- fachliche Verdrahtung der beiden Summary-Tasten
- E-Mail-Fernwartung fuer Datei-Download und kontrollierten Datei-Upload
- `abr-control-panel.service` fuer SSH-unabhaengigen Dauerbetrieb mit
  automatischem Neustart und persistentem Journal-Log
- NetworkManager-basierte Verwaltung mehrerer WLAN-Profile mit automatischem
  Wiederverbinden und bewusstem Profilwechsel
- Etappen 1 bis 5 der Buchsprachenerweiterung: zentrale persistente Profile
  fuer Deutsch und U.S.-Englisch steuern Runtime-TTS, Kapitelansagen und
  RapidOCR sowie Gemini-Zusammenfassungen und deren Cachevalidierung; Deutsch
  behaelt explizit den bisherigen parameterlosen RapidOCR-Enginepfad und bleibt
  der kompatible Default
- neue NFC-Buecher werden beim ersten Scan dauerhaft an `de` oder `en`
  gebunden; OCR, Ingest, Kapitel, Summary und TTS lehnen gemischte Buchdaten ab
- bestehende `book.json` ohne Sprache gelten als Deutsch; englische Testbuecher
  aus der Zeit vor Etappe 5 muessen kontrolliert migriert oder neu angelegt
  werden
- die Readerposition bestimmt die Seitenorientierung nicht mehr: RapidOCR
  klassifiziert drei lange Textzeilen vor der eigentlichen OCR; zuverlaessige
  Ergebnisse aktualisieren `state/page_orientation.json`, textarme Seiten
  verwenden den buchweisen Merker
- neue Buecher koennen ohne ISO14443A direkt mit genau einem unbekannten
  ISO15693-Tag angelegt werden
- die [deutsche README](../readme_DE.md) dokumentiert den bisherigen Stand;
  die englische [README](../readme.md) ist der kanonische Einstieg fuer eine
  Neuinstallation; sie fuehrt von Systempaketen und Checkout ueber `.venv`,
  Google ADC und Geraetekonfiguration bis zu systemd-Diensten und Smoke-Test
- die hardwarebezogenen Details und die abschließende Verifikation stehen in
  [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md)
- alle geraete- und personenbezogenen Werte liegen ausserhalb des
  Repositorys: Google ADC unter `~/.config/gcloud/`, Sprache unter
  `~/.config/abr/device.json`, Maildaten unter `~/.config/abr/mail.ini` und
  WLAN-Zugangsdaten in NetworkManager-Profilen
- die Installer ermitteln den aufrufenden Benutzer, dessen Home-Verzeichnis,
  Repositorypfad und `.venv` bei der Installation; ein fest codierter lokaler
  Benutzer- oder Projektpfad ist nicht erforderlich
- konkrete Google-Cloud-Projekt-IDs duerfen weder in Dokumentation noch in
  Git-Historie stehen; Beispiele verwenden ausschliesslich
  `DEIN_PROJECT_ID`
- [PATENT_NOTICE.md](../PATENT_NOTICE.md) dokumentiert transparent, dass keine
  Patent- oder Freedom-to-Operate-Recherche erfolgt ist, die Projektlizenzen
  nur kontrollierte Rechte der jeweiligen Lizenzgeber erfassen und eine
  kommerzielle Umsetzung eine eigene professionelle Pruefung benoetigt

Zuletzt festgelegter Erprobungsstand:

- der Opt-in-Sprachpfad `google-standard-enhanced` bleibt aktivierbar, ohne
  den bisherigen Standardpfad `google` zu veraendern
- innerhalb eines Absatzes folgen auf vollstaendige Saetze `900ms` Pause
- nach dem letzten Satz jedes Absatzes folgen stattdessen `2000ms`; die
  Satz- und Absatzpause werden nicht addiert
- nach einem vollstaendig eingerahmten Dialogsatz wird eine folgende
  Absatzgrenze im Enhanced-Renderer als normale Satzgrenze mit `900ms`
  behandelt; unterstuetzt sind `"..."`, `»...«` und `„...“`
- deutsche `speak_text`-Fassungen ersetzen `Dr.` durch `Doktor` und
  `Notre-Dame` durch `Notre Damm`, ohne `clean_text` zu veraendern; bestehende
  Seiten-JSONs werden nicht rueckwirkend umgeschrieben und benoetigen dafuer
  einen erneuten Page-Ingest
- das letzte Wort einer Frage bleibt um `+3st` angehoben
- Summary-Zielseiten werden mit `250` Woertern pro Seite in ein Wortziel
  uebersetzt; bei mehr als zehn Prozent Ueberschreitung folgt ein eigener
  Kuerzungsdurchlauf
- unnummerierte, durch einen grossen vertikalen Abstand abgesetzte
  Kapitelueberschriften werden im `speak_text` als eigener Absatz erhalten;
  dies verbessert die Sprechpause, ohne daraus bereits eine fachliche
  Kapitelgrenze abzuleiten

## Was Jetzt Wirklich Fertig Ist

### 1. Frontpanel und Runtime

Implementiert sind:

- GPIO-Abstraktion in [abr/hardware/control_panel.py](../abr/hardware/control_panel.py)
- Polling-Monitor und Action-Router in [abr/control/frontpanel.py](../abr/control/frontpanel.py)
- langlebiger Runtime-Controller in [abr/control/runtime.py](../abr/control/runtime.py)
- Startskript fuer den Pi in [hardware/control_panel_service.py](../hardware/control_panel_service.py)

Aktuelle Semantik:

- `Start / Stop / NFC`
  - startet den echten Lauf `capture -> Bildvorbereitung -> OCR -> page-ingest`
  - stoppt einen laufenden foreground job
  - stoppt eine laufende Seitenausgabe
  - stoppt auch den reinen Wartezustand mit Heartbeat
- `EC11`
  - regelt die Lautstaerke
  - wirkt auch waehrend laufender Seitenausgabe
- `EC11-Taster`
  - aktuell produktiv nur fuer den Buch-Loeschdialog verdrahtet
- Dreifachtaste aus `Start / Stop / NFC` + `Buch-Zusammenfassung` +
  `Kapitel-/Letzte-Seiten-Zusammenfassung`
  - startet den Buch-Loeschdialog

Die beiden Summary-Tasten sind jetzt fachlich verdrahtet:

- `Kapitel-/Letzte-Seiten-Zusammenfassung`
  - spielt zuerst `kapitel_zusammenfassen`
  - startet danach denselben `bing`-Heartbeat wie der Start-Knopf
  - holt immer die letzte Abschnittszusammenfassung in echter
    `chapter_0001`, `chapter_0002`, ...-Reihenfolge
  - erzeugt oder aktualisiert sie bei Bedarf ueber Gemini
  - prueft vorher den Text ab der persistenten offenen Abschnittsgrenze
  - verbindet vorhandenen offenen Text mit der gespeicherten Zusammenfassung
    des letzten fertigen Abschnitts zu einer temporaeren aktuellen Rueckschau
  - vor dem ersten fertigen Abschnitt wird der offene Text allein
    zusammengefasst
  - die temporaere Rueckschau wird nur vorgelesen und nicht unter
    `summaries/` gespeichert
  - Zielgroesse ist per `target-pages` konfigurierbar, Standard `1.5`
  - eine Zielseite entspricht `250` Woertern
  - ein vorhandener Summary-Cache wird automatisch neu erzeugt, wenn sich die
    Zielgroesse oder aktive Buchsprache geaendert hat
  - wandelt sie per TTS in Audio und spielt sie ab

Beim inkrementellen Ingest wird die erste Seite bereits nach
`left_report.json` gespeichert. Falls ihre Seitenzahl erst durch die zweite
Seite im kombinierten `report.json` ermittelt werden kann, leitet der Ingest
die Nachbarzahl aus der erkannten Links-/Rechts-Lage ab: zweite Seite rechts
bedeutet Vorgänger, zweite Seite links bedeutet Nachfolger. Die Platzhalter
`page_1.json`/`page_2.json` werden durch vierstellig nummerierte Dateien
ersetzt. Die Zuordnung wird ueber Scan-ID, Seitenseite und urspruengliche
Report-Seiten-ID abgesichert; geloescht wird erst nach erfolgreichem Speichern
des Ersatzes.

Unnummerierte Kapitelueberschriften sind fuer die Audioausgabe jetzt ebenfalls
abgesichert. Der produktive schlanke RapidOCR-Pfad schreibt dazu ebenso wie die
allgemeine Pipeline die Ergebnisse des `BasicLayoutAnalyzer` als
`layout_blocks` in den OCR-Report. Zuvor fehlte dieses Feld im produktiven
Report, obwohl Bounding-Boxen vorhanden waren.

Der Analyzer trennt normale Zeilengruppen weiterhin erst, wenn der vertikale
Abstand groesser als das `1,4`-Fache der mittleren Zeilenhoehe ist. Nur nach
einer kurzen Zeile, die bereits die vorsichtigen Textmerkmale einer Ueberschrift
erfuellt, gilt das `1,2`-Fache der Hoehe genau dieser Ueberschriftenzeile. Das
deckt auch leicht schraege OCR-Bounding-Boxen ab, ohne die allgemeine
Absatzschwelle zu veraendern. Ein kurzer Text ohne
abschliessendes Satzzeichen kann danach als `chapter_heading` klassifiziert
werden. `PageIngestor._paragraph_end_line_indices()` behandelt diesen Blocktyp
ebenso wie `paragraph`: Nach der letzten Ueberschriftenzeile steht in
`speak_text` eine Leerzeile. Damit kann der TTS-Pfad die Ueberschrift mit einer
deutlichen Pause vom folgenden Fliesstext trennen.

Diese Korrektur ist bewusst eng begrenzt:

- `clean_text` und die gesprochenen Woerter bleiben unveraendert
- die vorhandene Layoutheuristik wird nicht erweitert
- es wird kein neuer `chapter_marker` erzeugt
- `ChapterAssembler` und Abschnittsgrenzen bleiben unveraendert

Abgedeckt ist der Fall durch einen Layouttest fuer eine unnummerierte
Ueberschrift mit grossem Folgeabstand und einen Ingest-Test, der
`Ueberschrift\n\nFliesstext` im `speak_text` sowie eine leere Marker-Liste
verlangt.
- `Buch-Zusammenfassung`
  - spielt zuerst `buch_zusammenfassen`
  - startet danach denselben `bing`-Heartbeat wie der Start-Knopf
  - kombiniert die vorhandenen Abschnittszusammenfassungen in
    Kapitelreihenfolge
  - erzeugt daraus ein "Was bisher geschah"
  - Zielgroesse ist per `target-pages` konfigurierbar, Standard `1.5`
  - eine Zielseite entspricht `250` Woertern
  - auch hier wird ein vorhandener Summary-Cache automatisch neu erzeugt, wenn
    sich Kapitelmenge, Zielgroesse oder aktive Buchsprache geaendert haben
  - wandelt es per TTS in Audio und spielt es ab

Nur wenn weder ein abgeschlossener Abschnitt noch offener Text vorliegt,
spielt die Runtime `keine_zusammenfassung`.

Technisch liefert `ChapterAssembler.collect_pending_content()` den offenen
Text samt Seiten-IDs und Seitenzahlen ab `current_start`. Der temporaere
`SummaryRecord` traegt den Typ `temporary_chapter_progress` und
`temporary=true`, wird aber nicht durch `BookStore.save_summary()`
geschrieben. Die persistente Zusammenfassung des letzten Abschnitts bleibt
damit als wiederverwendbare Grundlage unveraendert erhalten.

### 2. Audio-Verhalten

Es gibt zwei getrennte Audiopfade:

- `SystemAudio`
  - fuer Warnhinweise wie `bing`, `neues_buch`, `abbruch`, `buch_loeschen`,
    `buch_geloescht`, `buch_nicht_erkannt`, `fehler`
  - verwendet je nach aktivem Sprachprofil die vorproduzierten Dateien aus
    `system_audio/messages/de/` oder `system_audio/messages/en/`
  - wird ueber eine eigene Queue seriell abgespielt
  - Warnhinweise sollen vollstaendig abgespielt werden
- `PageAudioPlayer`
  - fuer die eigentliche Seitenausgabe
  - ist abbrechbar
  - spielt zuerst links, dann rechts
  - beide Seiten sind zu diesem Zeitpunkt bereits aufgenommen
  - Bildvorbereitung, OCR, `PageIngestor` und TTS fuer die rechte Seite werden
    waehrend der Wiedergabe der linken Seite vorbereitet

Wichtige aktuelle Details:

- vor dem Start des Capture/OCR-Pfads wird `bing` abgespielt
- waehrend der Wartezeit laeuft ein Heartbeat mit erneutem `bing`
- derselbe Heartbeat wird auch waehrend Kapitel- und Buchzusammenfassungsjobs
  verwendet
- der Heartbeat endet:
  - bei erster bereiter Seitenaudio
  - bei bereiter Summary-Audio
  - bei Fehler
  - bei manuellem Stop
  - wenn `page-ingest` keine vorlesbaren Seiten liefert
- liefert `page-ingest` nur leere `speak_text`-Seiten, wird
  `empty_page.wav` abgespielt und der Heartbeat sauber beendet; andere
  Fehlerpfade bleiben bei `fehler.wav`

#### Sprachabhaengige Systemhinweise

Die zuvor direkt unter `system_audio/messages/` liegenden deutschen Dateien
sind nach `system_audio/messages/de/` verschoben. Die gleichnamigen
U.S.-englischen Aufnahmen liegen unter `system_audio/messages/en/`.

Beide Ordner muessen denselben Satz produktiv verwendeter logischer
Meldungsnamen enthalten:

- `abbruch.wav`
- `bing.wav`
- `buch_geloescht.wav`
- `buch_loeschen.wav`
- `buch_nicht_erkannt.wav`
- `buch_zusammenfassen.wav`
- `empty_page.wav`
- `fehler.wav`
- `kapitel_zusammenfassen.wav`
- `keine_zusammenfassung.wav`
- `neues_buch.wav`
- `repeat_page.wav`
- `wrong_direction.wav`

Die Runtime-Namen bleiben absichtlich sprachneutral beziehungsweise historisch
stabil. Es gibt daher zum Beispiel auch im englischen Ordner eine Datei namens
`fehler.wav`; ihr gesprochener Inhalt ist Englisch. Neue Hinweise muessen unter
demselben Dateinamen in beiden Sprachordnern angelegt werden. Es gibt keinen
stillen Rueckfall von Englisch auf eine deutsche Datei: Fehlt eine Aufnahme im
ausgewaehlten Ordner, meldet die Runtime den aufgeloesten fehlenden Pfad als
Fehler. Dadurch wird eine versehentlich gemischte Bedienausgabe sichtbar.

`hardware/control_panel_service.py` liest beim Prozessstart das persistente
`LanguageProfile` und baut daraus eine `SystemAudioConfig` mit einem absoluten
Pfad:

```text
<Projekt>/system_audio/messages/<profile.code>/
```

Diese Konfiguration wird an `RuntimeController` uebergeben und gilt fuer alle
synchronen und asynchronen Systemhinweise. Der Audio-Loader selbst bleibt
allgemein und spielt nur aus dem konfigurierten Wurzelordner ab.

Ein manueller Sprachwechsel erfolgt auf dem Pi mit:

```bash
sudo abr-language en
sudo abr-language de
```

`abr-language` startet `abr-control-panel.service` neu. Das ist notwendig,
weil das Profil und der Systemaudio-Ordner nur beim Prozessstart gelesen
werden. Nach einem `git pull`, das Code oder WAV-Dateien aktualisiert, den
Dienst ebenfalls neu starten und pruefen:

```bash
sudo systemctl restart abr-control-panel.service
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 100 --no-pager
```

Abgesichert ist die Erweiterung durch:

- `tests/test_system_audio.py`: Wiedergabe ausschliesslich aus dem
  konfigurierten Sprachordner
- `tests/test_language_runtime.py`: Abbildung des Profils `de` auf `.../de`
  und des Profils `en` auf `.../en`
- Runtime-Tests: unveraenderte logische Meldungsnamen und Queue-Semantik

Bei der Implementierung bestanden die 75 betroffenen Systemaudio-, Sprachprofil-
und Runtime-Tests. Im Gesamtlauf bestanden 312 Tests; nur die zwei bereits
bekannten, sachfremden `ChapterAssembler`-Tests blieben rot.

ALSA-Produktionskonfiguration auf dem Raspberry Pi:

- Zielkarte ist `MAX98357A`, nicht eine der beiden HDMI-Karten
- der gemeinsame Playback-Code startet `aplay` ohne `-D` und ist deshalb auf
  ein korrektes systemweites ALSA-`default` angewiesen
- `/etc/asound.conf` muss `default` ueber den stabilen symbolischen Kartennamen
  auf `hw:CARD=MAX98357A,DEV=0` legen; keine numerische Kartennummer verwenden
- der Default muss ein `plug`-PCM sein, weil Google-TTS-WAVs mono sein koennen,
  waehrend der MAX98357A-ASoC-Pfad zwei Kanaele erwartet
- Referenztest nach Installation und nach Audio-Problemen:
  `aplay -D default /usr/share/sounds/alsa/Front_Center.wav`
- `Unknown error 524` bedeutet in diesem Aufbau typischerweise, dass das
  globale `default` versehentlich eine nicht nutzbare HDMI-Karte geoeffnet hat
- unabhaengiger Hardwaretest:
  `aplay -D plughw:CARD=MAX98357A,DEV=0 /usr/share/sounds/alsa/Front_Center.wav`

Verbindliche `/etc/asound.conf`:

```text
pcm.!default {
    type plug
    slave.pcm "hw:CARD=MAX98357A,DEV=0"
}
```

### 3. Lautstaerke

Implementiert in [abr/control/audio_volume.py](../abr/control/audio_volume.py).

Aktueller Stand:

- 10 Stufen
- Bereich `20% .. 100%`
- keine Stufe `0%`
- Software-Regelung im Audiopfad funktioniert auch waehrend aktiver Wiedergabe
- ALSA-Mixer ist nicht mehr Voraussetzung fuer die Nutzbarkeit
- EC11 A/B verwenden im produktiven `rpi-gpio`-Pfad Flankeninterrupts;
  `pinctrl` bleibt als Polling-Fallback erhalten
- der Interrupt veraendert nur den threadsicheren Lautstaerke-Sollwert und
  reiht danach das normale Encoder-Event ein
- Seiten-WAVs und System-WAVs wie `bing.wav` fragen den Sollwert blockweise
  waehrend der laufenden `aplay`-Wiedergabe ab
- Mixerzugriff und Logging bleiben ausserhalb des Interrupt-Callbacks
- der dynamische WAV-Streamingpfad verwendet `250ms` PCM-Vorlauf und einen
  `300ms`-ALSA-Puffer mit `50ms` Perioden; dies verhindert den beobachteten
  kurzen Underrun in der Mitte von `bing.wav`, der mit den frueheren `100ms`
  Reserven auftreten konnte
- jeder PCM-Block wird sofort in die `aplay`-Pipe geflusht; die korrigierte
  Lautstaerkeregelung und die unterbrechungsfreie Wiedergabe von `bing.wav`
  wurden am Geraet bestaetigt

### 4. NFC und Buchkontext

Der produktive Pfad verwendet:

- `PN5180`-Gateway am Pi
- Host-Wrapper: [hardware/pn5180_gateway_client.py](../hardware/pn5180_gateway_client.py)
- Runtime-Leser: [abr/hardware/nfc_gateway.py](../abr/hardware/nfc_gateway.py)

Fachliche Regel:

- der NFC-Tag ist der Primaerschluessel des Buchs
- Daten werden unter `library/<TAG_ID>/` gespeichert
- bei neu erkanntem Buch wird die Struktur automatisch angelegt
- dabei wird `neues_buch` abgespielt

Technischer Firmware-Stand des `PN5180`-Gateways am `2026-07-30`:

- beide PN5180-Reader sind wieder im aktiven Firmwarepfad
- die beiden Reader werden nicht gleichzeitig betrieben
- stattdessen gilt jetzt bewusst:
  - kein permanentes Polling mehr
  - Reader im Leerlauf dauerhaft in `RESET`
  - nur bei einem expliziten Kommando wird genau ein Reader freigegeben
  - bei Zwei-Reader-Abfragen werden die Reader strikt nacheinander bearbeitet
- der zweite Reader wird ueber dieselbe `RST`-Leitung zugleich fuer den PN5180
  und fuer das vorgeschaltete Relais genutzt
- dadurch ist der aktive Antennenpfad immer an genau den Reader gekoppelt, der
  gerade abgefragt wird
- der synchrone `STATUS`-Pfad arbeitet on-demand und fuehrt pro Reader einen
  kompletten Lesezyklus aus
- bei fruehen Readerfehlern nach `hardReset()` oder beim ersten RF-Setup wird
  derselbe Status-Probe jetzt mehrfach wiederholt, statt sofort mit `kein Tag`
  abzubrechen
- zusaetzlich existiert jetzt eine zweistufige asynchrone Statusabfrage:
  - `STATUS_START`
  - `STATUS_FETCH`
- `STATUS_START` kehrt sofort zurueck und startet den Readerjob erst in der
  naechsten Loop-Runde
- `STATUS_FETCH` liefert das zuletzt angestossene Ergebnis und wartet bei
  Bedarf bis zum Abschluss
- die Statuslogik unterstuetzt im aktuellen Stand wieder beide Protokolle:
  - `ISO14443A`
  - `ISO15693`
- der bevorzugte Type-A-Standardwert bleibt `RX_WAIT_CONFIG = 0x00000878`
- `TYPEA_TUNE` zeigt deshalb im Normalfall weiter `override_rxwait=off`

Wichtige Pi-Kommandos fuer diesen Stand:

```bash
python3 hardware/pn5180_gateway_client.py STATUS
python3 hardware/pn5180_gateway_client.py STATUS 1
python3 hardware/pn5180_gateway_client.py STATUS 2
python3 hardware/pn5180_gateway_client.py STATUS_START
python3 hardware/pn5180_gateway_client.py STATUS_FETCH
python3 hardware/pn5180_gateway_client.py --timeout 10 TYPEA_DIAG
```

Wichtig fuer den aktuellen Betriebsmodus:

- das Gateway arbeitet nicht mehr als dauerhaft pollender Tag-Monitor
- der Reader wird nur waehrend eines expliziten Befehls kurz freigegeben
- das ist wichtig fuer den aktuellen Relais-/Reset-Aufbau
- `STATUS_START` ist der geeignete Pfad, wenn das Hauptprogramm nicht auf das
  Leseergebnis warten soll

Produktiv in den Start-Knopf integriert ist inzwischen:

1. beim Tastendruck sofort `STATUS_START`
2. Aufnahme beider Kamerabilder waehrend der Gateway-Job laeuft
3. danach `STATUS_FETCH`, unmittelbar vor Buchzuordnung und OCR
4. ISO14443A als bevorzugte Buch-ID
5. Speicherung gleichzeitig gelesener ISO15693-IDs unter
   `library/<ISO14443A_ID>/iso15693_tag_ids.txt`
6. bei ausschliesslich gelesenem ISO15693-Tag Suche dieser Alias-ID in den
   vorhandenen Buchordnern; genau ein unbekannter ISO15693-Tag legt ein neues
   Buch direkt unter dieser ID an

Am realen Scanner verifizierte OCR-Bildzuordnung:

- die Readerposition dient ausschliesslich der Tag-Erfassung und beeinflusst
  die Orientierung nicht mehr
- die vorbereitete linke Aufnahme liefert drei lange, vertikal getrennte
  Textzeilen fuer den RapidOCR-Winkelklassifikator
- Votum `0` = `case/left.jpg` und `case/right.jpg` bleiben zugeordnet
- Votum `180` = beide Dateien werden vor der normalen OCR vertauscht
- nach dieser Zuordnung wird `case/right.jpg` einmalig um `180` Grad gedreht
- die nachfolgende OCR-Vorverarbeitung verwendet fuer beide Seiten
  `0` Grad Zusatzdrehung
- dadurch zeigen Camera-Testserver und OCR denselben korrigierten
  `case`-Stand
- mindestens zwei Klassifikationen muessen Konfidenz `>= 0.55` erreichen; der
  gewichtete Vorsprung muss groesser als `0.35` sein
- jede zuverlaessige Erkennung aktualisiert
  `library/<TAG_ID>/state/page_orientation.json`
- fehlen drei Zeilen, zwei zuverlaessige Klassifikationen oder ein eindeutiger
  Vorsprung, wird der gespeicherte Merker verwendet; neue Buchordner starten
  mit `reader2`, sodass auch eine leere erste Seite nicht abbricht
- nur fachlich nicht bestimmbare Orientierung nutzt den Fallback; technische
  OCR-Fehler bleiben sichtbar

Wichtig fuer `TYPEA_SWEEP`:

- erst den naechsten Befehl senden, wenn wirklich `END` zurueckkam
- sonst laufen auf dem Pi leicht Ausgaben eines noch nicht beendeten Sweeps in
  den naechsten Clientaufruf hinein

### 5. Buch-Loeschdialog

Implementiert im Runtime-Controller.

Ablauf:

1. Dreifachtaste
2. aktuelles NFC-Tag lesen
3. falls kein Tag:
   - `buch_nicht_erkannt`
   - Abbruch
4. falls Tag vorhanden:
   - `buch_loeschen`
   - Bestaetigung nur ueber `EC11`-Taster
   - Abbruch ueber eine der drei Funktionstasten
5. bei Abbruch:
   - `abbruch`
6. bei erfolgreichem Loeschen:
   - `buch_geloescht`

### 6. Page-Ingest und Buchdaten

Implementiert sind:

- [abr/book/store.py](../abr/book/store.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/session.py](../abr/book/session.py)
- Debug-CLI: [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)

Persistente Struktur pro Buch:

```text
library/
  <TAG_ID>/
    book.json
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

- wenn Seitenzahlen erkannt werden, heissen Seitendateien `0008.json` usw.
- ohne Seitenzahl wird der Fallback-Schluessel aus `page_id` benutzt, z.B.
  `page_1.json`
- `chapter_assembler_state.json` speichert die Folgegrenze fuer den naechsten
  Abschnitt, auch wenn diese mitten auf einer Seite liegt

### 7. Aktuelle Logik im `PageIngestor`

Der `PageIngestor` kann aktuell:

- Seitenzahl erkennen
- in einem vollstaendigen Doppelseiten-Report eine fehlende Seitenzahl aus der
  Gegenseite ableiten
  - links erkannt -> rechts `+1`
  - rechts erkannt -> links `-1`
- offensichtliche Footer-Artefakte wie OCR-Muell in der Seitennummernzone
  entfernen
- Kapitelmarker erkennen:
  - `Kapitel 7`
  - isolierte Kapitelnummern
  - reine Ueberschriftenseiten wie `INTERMEZZO`
  - mehrere Kapitelmarker auf einer einzelnen Seite
- `chapter_markers[]` speichern
- `clean_text` und `speak_text` getrennt speichern
- Worttrennungen im `speak_text` korrigieren
- Absatzgrenzen aus `layout_blocks` als Leerzeilen in `speak_text` erhalten
- deutsche Ausspracheausnahmen nur im `speak_text` anwenden:
  - `Dr.` -> `Doktor`
  - `Notre-Dame` -> `Notre Damm`
  - englische Buchprofile und `clean_text` bleiben unveraendert
- Satzreste ueber Seiten hinweg verschieben

Aktuell besonders wichtig fuer die Audioausgabe:

- unvollstaendige Satzenden werden als `tail_fragment` gespeichert
- Satzrest von rechter Seite `N` wird an den Anfang der linken Seite `N+1`
  uebernommen
- der Satzrest einer rechten Seite wird zusaetzlich unter
  `state/pending_right_tail_fragment.json` gehalten
- fehlt bei einer frueh ingestierten linken Einzelseite die Seitenzahl, wird
  genau dieser Pending-Speicher fuer den Uebergang verwendet
- Satzrest von linker Seite wird aus der linken Seitenausgabe entfernt und an
  den Anfang der rechten Seitenausgabe verschoben
- Worttrennung ueber Zeilen bleibt korrigiert
- Worttrennung ueber linke/rechte Seitenkante bleibt korrigiert
- gesperrte Woerter werden ab drei einzelnen Buchstaben zusammengezogen;
  beispielsweise wird `U E B E R S C H R I F T.` zu `UEBERSCHRIFT.`
- die Erkennung verbindet keine Buchstaben ueber Zeilen- oder Absatzgrenzen
  und laesst kurze Initialfolgen wie `A B` unangetastet
- kurze, vollstaendig grossgeschriebene Ueberschriften werden ausschliesslich
  im `speak_text` in Wort-fuer-Wort-Grossschreibung umgewandelt; beispielsweise
  `ERLEBNIS IN DER KNABENZEIT` zu `Erlebnis In Der Knabenzeit`
- nach einer solchen Ueberschrift steht im `speak_text` eine Leerzeile; der
  Enhanced-Renderer erzeugt daraus moderate Hervorhebung und `1350ms`
  Kapitelpause
- kurze eingeklammerte OCR-Artefakte mit Ziffern wie `(r9or)` werden bei der
  Satzrestanalyse verworfen; die Uebernahmepruefung filtert auch bereits in
  alten Seitendaten gespeicherte Artefakte

Kapitelansage im `speak_text`:

- fuer isolierte Kapitelnummern wird `Kapitel zwei.` statt `Kapitel 2.` erzeugt
- die deutlich wahrnehmbaren Pausen vor und nach der Kapitelansage werden nicht
  im `PageIngestor`, sondern erst in der Runtime als SSML eingefuegt

### 8. Seitenausgabe und SSML

Die Seitenausgabe verwendet:

- Google Cloud TTS als Default
- Stimme `de-DE-Standard-H`
- Geschwindigkeit aktuell `0.9`

Aktueller Zusatz fuer Kapitelansagen:

- vor `Kapitel ...` wird im Seitentext eine SSML-Pause von `1350ms` eingefuegt
- nach `Kapitel ...` ebenfalls `1350ms`
- das geschieht zur Laufzeit in [abr/control/runtime.py](../abr/control/runtime.py)
- fuer Backends ohne SSML-Unterstuetzung bleibt der Text unveraendert

Separater Neural2-Versuchsweg:

- der bisherige Pfad `google` mit `de-DE-Standard-H` ist weiterhin
  unveraenderter Default
- `google-neural2` verwendet die eigene Klasse
  `GoogleNeural2TTSBackend`
- dessen Defaultstimme ist `de-DE-Neural2-H`
- Aktivierung:

```bash
--page-tts-backend google-neural2
```

- sichere Rueckkehr:

```bash
--page-tts-backend google
```

oder den Parameter weglassen. Buchdaten, OCR und gespeicherte Seitentexte
werden beim Wechsel nicht veraendert.

Der günstige Standard-H-Versuchspfad wird separat aktiviert:

```bash
--page-tts-backend google-standard-enhanced
```

Er verwendet weiterhin `GoogleCloudTTSBackend` und `de-DE-Standard-H`.
Nur der Renderer in `abr/control/runtime.py` ist erweitert: Absatz- und
Satzstruktur sowie moderate Hervorhebung kurzer Überschriften. Vollstaendig
grossgeschriebene OCR-Ueberschriften werden im `speak_text` als eigener Absatz
mit lesbarer Gross-/Kleinschreibung abgelegt; danach gilt wie bei einer
Kapitelansage eine Pause von `1350ms`. Bei Fragen
wird das vollständige letzte Wort mit `<prosody pitch="+3st">` angehoben.
Nach dem letzten Satz jedes normalen Absatzes wird eine feste Pause
von `2000ms` gesetzt. Zusaetzlich stehen nach Saetzen innerhalb eines
Absatzes `900ms`; am Absatzende gelten stattdessen `2000ms`, nicht die Summe
beider Pausen.
Die dafür nötigen Leerzeilen übernimmt der `PageIngestor` aus den
`layout_blocks` des OCR-Reports. Für bereits zuvor gespeicherte Seiten
erkennt der Enhanced-Renderer zusätzlich einen einfachen Zeilenumbruch nach
`.` oder `?` als Absatzgrenze. Ein schließendes Anführungszeichen wie in
`.` + `«` + Zeilenumbruch wird berücksichtigt. Der konkrete Test mit
`library/0290.json` diente als Referenz fuer diese Erkennung. Eine Ausnahme
gilt fuer vollstaendig eingerahmte Dialogsaetze in `"..."`, `»...«` oder
`„...“`: Die direkt folgende Absatzgrenze erzeugt nur die normale Satzpause
von `900ms`, nicht die Absatzpause von `2000ms`.
Vor der Synthese wird geprüft, dass keine Wörter verändert wurden; bei
einem Fehler greift automatisch der bisherige Renderer. `google` selbst
bleibt unverändert.

Ein weiterer separater Versuchspfad ist Gemini 2.5 Flash TTS:

```bash
--page-tts-backend google-gemini-flash
```

Er verwendet:

- `GoogleGeminiFlashTTSBackend`
- Modell `gemini-2.5-flash-tts`
- Stimme `Charon`
- einen eigenen deutschen Hoerbuch-Prompt
- Klartext statt SSML
- maximal `4000` Byte Text und `4000` Byte Prompt pro Anfrage

Optionale Schalter:

```bash
--google-gemini-flash-voice-name Charon
--google-gemini-flash-prompt "Lies ruhig und natuerlich."
```

Der produktive Default bleibt auch nach dieser Erweiterung unveraendert
`google` mit `de-DE-Standard-H`.

### 8a. Seitenfolge-Warnungen

Die Runtime prueft pro Buch die erkannten Seitenzahlen gegen die zuletzt zur
Wiedergabe angenommene Doppelseite:

- Schnittmenge mit den letzten Seiten:
  `system_audio/messages/<Sprache>/repeat_page.wav`, Scan-Ausgabe abbrechen,
  Repeat-Bestaetigungsmerker setzen
- kleinste neue Seitenzahl kleiner als die kleinste letzte Seitenzahl:
  `system_audio/messages/<Sprache>/wrong_direction.wav`, Scan-Ausgabe abbrechen,
  Richtungs-Bestaetigungsmerker setzen
- ein neuer Scan mit gesetztem Merker ueberspringt die zugehoerige Pruefung
  einmal und setzt den Merker zurueck
- beim Richtungsmerker ist die Ausgabe dieses Bestaetigungsscans garantiert
- linkes und rechtes inkrementelles Ingest werden ueber `scan_id`
  zusammengefasst
- nach einer Warnung wird auch das spaetere Teilergebnis derselben Scan-ID
  unterdrueckt
- ohne erkannte Seitenzahl erfolgt keine Seitenfolge-Pruefung

Der Zustand ist fluechtig, buchbezogen und wird beim Buchloeschen bereinigt.
Die WAV-Dateien liegen sprachabhaengig unter `system_audio/messages/de/` und
`system_audio/messages/en/`. `control_panel_service.py` waehlt beim Start den
Unterordner des aktiven Sprachprofils; nach einem Sprachwechsel muss der Dienst
neu gestartet werden.
Die Warnungen werden synchron im Ingest-Callback wiedergegeben, damit sie
nicht hinter der allgemeinen Systemaudio-Queue verloren beziehungsweise
verspaetet ausgegeben werden. Start und Abschluss stehen explizit im
Runtime-Log; bei einem Fehler wird der aufgeloeste Audiopfad gemeldet.
Nach OCR links wartet der inkrementelle Capture-Runner auf das Completion-
Event des Page-Ingests. Bei einer Warnung wird der laufende Foreground-Job
abgebrochen; dadurch werden Bildvorbereitung und OCR rechts nicht mehr
gestartet. Das anschliessende `CANCELLED`-Ereignis bringt die Runtime ohne
zusaetzliche Abbruchansage zurueck nach `IDLE`.

### 8b. Lange Zusammenfassungen in mehrere TTS-Teile zerlegen

Der zuvor komplette Summary-Text wurde als eine einzelne TTS-Anfrage
gesendet. Mit der erweiterten SSML-Aufbereitung konnte diese Anfrage fuer
Google zu gross werden; die wahrgenommene Ausgabe bestand dann unter
Umstaenden nur aus einem kurzen vorproduzierten Hinweis beziehungsweise
brach vor der eigentlichen Zusammenfassung ab.

`PageAudioPlayer.enqueue_text()` teilt Summary-Ausgaben nun bei maximal
`900` Byte gerenderter Eingabe an Satzgrenzen; `3800` Byte bleibt die
allgemeine Google-Sicherheitsgrenze. Die Teile werden unter
Labels wie `kapitel-zusammenfassung:10-20:1/2` lueckenlos nacheinander
ausgegeben. Das Runtime-Log nennt die Zahl der Teile. Kurze Texte werden
nicht veraendert.

Summary-Intro und erstes `bing` laufen synchron vor dem Job. Sobald die
Summary-Audio aktiv ist, werden noch wartende Heartbeat-Bings verworfen.
Das verhindert das zuvor beobachtete `bing` nach dem Ende der kurzen
Summary-WAV.

Das anschliessende Pi-Log zeigte nur `100 Zeichen` TTS-Eingabe und eine dazu
plausible `6.2 s` lange WAV. Die vom Pi kopierten Dateien bestaetigten
anschliessend, dass bereits `chapter_0001_summary.json` mitten im Wort endete.
Die Ursache lag in `GeminiSummaryBackend.generate()`: Ein vorhandener
Teiltext wurde sofort akzeptiert, obwohl Gemini mit
`finishReason=MAX_TOKENS` den Abbruch gemeldet hatte. Der bereits vorhandene
zweite Versuch ohne `maxOutputTokens` wurde nur bei einer vollstaendig
textlosen Antwort ausgefuehrt.

Nun wird auch ein nichtleerer, mit `MAX_TOKENS` beendeter Teiltext verworfen
und die Anfrage einmal ohne explizites Ausgabelimit wiederholt. Bleibt auch
diese Antwort abgebrochen, wird ein Fehler gemeldet und nichts gespeichert.
Die Diagnose nennt neben dem Finish-Grund auch vorhandene Prompt-, Ausgabe-,
Thinking- und Gesamt-Tokenzahlen.

Erfolgreich erzeugte Kapitel- und Buchzusammenfassungen erhalten den
Cache-Merker `generation_complete=true`. Vorhandene Dateien ohne diesen
Merker werden beim naechsten Aufruf einmalig neu erzeugt; damit werden auch
die bereits auf dem Pi gespeicherten abgeschnittenen Texte ersetzt.

Zusaetzlich enthalten Buch-Summaries einen SHA-256-Fingerabdruck aus
Kapitel-ID, `updated_at` und Text. Dadurch wird `book_so_far_summary.json`
auch neu erzeugt, wenn sich eine Kapitelzusammenfassung geaendert hat, aber
die Liste der Kapitel gleich geblieben ist. Der Job loggt den exakten
Quellpfad und die Zeichenanzahl.

Die Summary-Laenge ist nun proportionaler steuerbar: Eine konfigurierte
Zielseite entspricht `250` Woertern. Damit bedeuten `1.0`, `0.75` und `0.5`
konkrete Grenzen von `250`, `188` und `125` Woertern. Gemini erhaelt fuer
Thinking plus sichtbare Antwort ein technisches Budget von `2048` Tokens.
Ueberschreitet die erste Antwort die Wortgrenze um mehr als zehn Prozent,
folgt automatisch ein Kuerzungsdurchlauf. Auch dieser muss innerhalb der
Toleranz bleiben, sonst wird keine Summary gespeichert. Metadaten enthalten
`target_words`, `initial_word_count`, `actual_word_count` und
`length_policy_version`. Durch die neue Policy-Version werden vorhandene
Summaries beim naechsten Aufruf einmalig neu erzeugt, auch wenn
`target_pages` unveraendert blieb.

### 9. E-Mail-Fernwartung

Die E-Mail-Fernwartung ist implementiert und auf dem Pi praktisch getestet.

Download vom Pi:

- der global installierte Befehl `email_download DATEI` ist aus jedem
  Verzeichnis nutzbar
- er sendet die angegebene Datei an `recipient` aus der lokalen `mail.ini`
- der Aufruf verwendet SMTP ueber SSL/TLS

Upload zum Pi:

- `abr-email-upload.timer` startet alle zwei Minuten einen IMAP-Prueflauf
- akzeptiert werden nur Mails vom exakten Absender, der lokal als `recipient`
  konfiguriert ist
- der Betreff hat die Form `save PFAD/`, zum Beispiel `save src/abr/`
- der Betreff nennt nur das bereits vorhandene Zielverzeichnis
- der Zieldateiname wird aus dem Namen des einzigen Mailanhangs uebernommen
- relative Pfade beziehen sich auf das Home-Verzeichnis des Pi-Benutzers
- vorhandene Dateien werden durch atomare Anlage mit `O_EXCL` niemals
  ueberschrieben
- Anhangsnamen mit Pfadbestandteilen wie `../datei` werden abgelehnt
- nach erfolgreichem Speichern wird die Upload-Mail per IMAP geloescht
- gelesene und ungelesene Mails werden beruecksichtigt
- bereits verarbeitete IMAP-UIDs werden unter
  `~/.local/state/abr/mail_upload.json` gespeichert

Konfiguration und Installation:

- Implementierung: [abr/remote_mail.py](../abr/remote_mail.py)
- Installer: [deploy/install_remote_mail.sh](../deploy/install_remote_mail.sh)
- Konfiguration auf dem Pi: `~/.config/abr/mail.ini`, Dateimodus `0600`
- Mailkonto, Wartungsempfaenger und anbieterspezifische SMTP-/IMAP-Daten
  stehen ausschliesslich in der lokalen `mail.ini`; die Repository-Vorlage
  enthaelt nur `example.com`-Werte
- je nach Anbieter ist gegebenenfalls ein separates App-Passwort fuer
  E-Mail-Programme erforderlich
- vollstaendige Anleitung:
  [docs/REMOTE_MAINTENANCE_EMAIL.md](../docs/REMOTE_MAINTENANCE_EMAIL.md)

### 10. Buchweise Nutzerstatistik

Implementiert in
[abr/usage_statistics.py](../abr/usage_statistics.py)
und [abr/usage_report.py](../abr/usage_report.py).

Aktueller Stand:

- Statistikperiode ist taeglich `04:00` bis `04:00` in `Europe/Berlin`
- auch ohne Geraetenutzung wird fuer jede abgeschlossene Periode ein Bericht
  mit Nullwerten verschickt; ein Archivmarker verhindert Doppelversand
- nach mehreren ausgeschalteten Tagen werden fehlende, noch nicht archivierte
  Perioden in zeitlicher Reihenfolge nachgeholt
- pro Buch werden eindeutige gescannte Seiten, tatsaechliche Wiedergabedauer,
  Kapitel-/Letzte-Seiten-Zusammenfassungen und `Was bisher geschah` erfasst
- Systemhinweise wie `bing.wav` zaehlen nicht zur Vorlesedauer
- Speicherung unter `library/usage_statistics/current.json`, atomar und gegen
  parallele Threads/Prozesse gesperrt
- abgeschlossene Perioden werden um `04:00` per bestehendem SMTP-Account an
  den lokal konfigurierten Empfaenger geschickt
- erst ein erfolgreicher Versand verschiebt die Periode nach
  `library/usage_statistics/archive/YYYY-MM-DD.json`; Mailfehler verlieren
  deshalb keine Statistik
- `abr-usage-report.timer` ist persistent und holt einen bei ausgeschaltetem
  Pi verpassten Lauf nach
- Installation: `sudo deploy/install_usage_statistics.sh`; danach
  `sudo systemctl restart abr-control-panel.service`

Vollstaendige Anleitung:
[docs/USAGE_STATISTICS.md](../docs/USAGE_STATISTICS.md).

Wichtige Verifikation nach Installation:

```bash
systemctl status abr-usage-report.timer
systemctl list-timers abr-usage-report.timer
python -m json.tool library/usage_statistics/current.json
```

Eine sofortige Vorschau-Mail ohne Ruecksetzung der laufenden Periode:

```bash
.venv/bin/python -m abr.usage_report \
  --library-root library \
  --config ~/.config/abr/mail.ini \
  --preview-current
```

Der regulaere Dienstlauf und sein Log:

```bash
sudo systemctl start abr-usage-report.service
journalctl -u abr-usage-report.service -n 100 --no-pager
```

### 11. Mehrere WLAN-Profile

Implementiert in
[abr/wifi_profiles.py](../abr/wifi_profiles.py).

Aktueller, am Pi bestaetigter Stand:

- vorhandene NetworkManager-Profile werden weiterverwendet
- neue WPA/WPA2-Profile werden per `add` mit interaktiver Passwortabfrage
  gespeichert; Zugangsdaten liegen nicht im Repository
- Speichern und Aktivieren sind getrennt, damit ein neues Profil gefahrlos
  ueber die laufende SSH-Verbindung angelegt werden kann
- `switch` aktiviert gezielt einen Profilnamen oder eine UUID
- `configure` setzt fuer alle WLAN-Profile `connection.autoconnect=yes` und
  `connection.autoconnect-retries=0`
- der fruehere `abr-wifi-autoconnect.service` scheiterte als normaler
  Dienstbenutzer reproduzierbar mit `Insufficient privileges`; er wird nicht
  als Root-Dienst weitergefuehrt
- `install_wifi_autoconnect.sh` setzt die persistenten Eigenschaften einmalig
  mit den ohnehin durch `sudo` erteilten Rechten und entfernt die alte Unit;
  NetworkManager uebernimmt danach selbst das Verhalten bei jedem Boot
- NetworkManager waehlt dadurch beim Boot oder nach Verbindungsverlust ein
  erreichbares gespeichertes Netz
- disruptive Befehle erfordern in einer erkannten SSH-Sitzung die bewusste
  Option `--allow-ssh-disconnect`
- der Wechsel zwischen einem lokalen WLAN-Profil und einem mobilen Hotspot
  wurde praktisch bestaetigt
- der Rueckweg kann bei fehlendem direktem SSH-Zugang ueber Raspberry Pi
  Connect angestossen werden
- Profilname und SSID koennen verschieden sein; `switch` erwartet den exakten
  Profilnamen aus `list`, nicht die vermutete SSID

Wichtige Kommandos:

```bash
sudo .venv/bin/python -m abr.wifi_profiles list
sudo .venv/bin/python -m abr.wifi_profiles add "Handy" "Beispiel-Hotspot"
sudo .venv/bin/python -m abr.wifi_profiles configure
sudo .venv/bin/python -m abr.wifi_profiles \
  --allow-ssh-disconnect switch "Zuhause"
nmcli -g 802-11-wireless.ssid connection show "Example WiFi"
```

Optionale Boot-Absicherung:

- Installer: `deploy/install_wifi_autoconnect.sh`
- vollstaendige Anleitung:
  [docs/WIFI_PROFILES.md](../docs/WIFI_PROFILES.md)

## Bevorzugte Kommandos

### E-Mail-Fernwartung

Datei vom aktuellen Verzeichnis senden:

```bash
email_download DATEI
```

Upload-Pruefung sofort ausloesen und Log ansehen:

```bash
sudo systemctl start abr-email-upload.service
journalctl -u abr-email-upload.service -n 50 --no-pager
```

Beispiel fuer eine Upload-Mail:

```text
Betreff: save src/abr/
Anhang: test1.txt
Ziel: ~/src/abr/test1.txt
```

### Voller Frontpanel-Dienst auf dem Pi

Das folgende Kommando ist nur noch der manuelle Referenzlauf. Im Dauerbetrieb
startet `abr-control-panel.service` dieselben Parameter unabhaengig von SSH.
Installation und Diagnose:
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

Nuetzliche optionale Parameter:

- `--artifact-mode debug|production`
- `--cleanup-stage after-ocr|after-ingest`
- `--page-tts-speed 0.9`
- `--volume-mixer-control auto`
- `--summary-gemini-model gemini-3.5-flash`
- `--summary-gcp-project <PROJECT_ID>`
- `--summary-gcp-location global`
- `--chapter-summary-target-pages <SEITEN>`
- `--book-summary-target-pages <SEITEN>`

### OCR-Seiten offline erneut ingestieren

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/page_ingest_debug.py \
  --library-root library \
  --book-tag-id TESTBOOK \
  --report-path captures/scan_xxx/ocr_text/report.json
```

### Warnhinweis auf dem Pi erzeugen

Repo-Pfad vermeiden, wenn die Datei erst auf den Mac kopiert und dort committed
werden soll:

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/generate_audio_message.py \
  --ssml \
  --output-root ~/tmp_audio_export \
  fehler \
  '<speak>Fehler.<break time="700ms"/>Bitte erneut versuchen.</speak>'
```

Dann von dort auf den Mac kopieren. So entstehen spaeter keine `git pull`-
Konflikte auf dem Raspi.

## Aktuelle Grenzen und bekannte offene Punkte

Noch offen bleiben aktuell vor allem:

- Feinschliff der Abschnittsheuristiken
- Prompt- und Modell-Tuning fuer Gemini-Zusammenfassungen
- Feintuning der Token-Skalierung fuer `target-pages`
- Langzeittest des jetzt integrierten PN5180-Zwei-Reader-Pfads
- Robustheit der ISO15693-Aliaszuordnung mit mehreren realen Buechern

Bewusst aktueller Grenzverlauf:

- `PageIngestor` normalisiert Seiten
- `ChapterAssembler` baut daraus persistente Abschnitte
- `SummaryManager` erzeugt Abschnitts- und Buchzusammenfassungen
- `SummaryService` bleibt als optionaler asynchroner Helfer im Repo, ist aber
  im produktiven Startpfad nicht mehr der primaere Mechanismus
- Runtime spielt Seiten und Zusammenfassungen vor

Aktueller Sonderfall:

- wenn OCR fuer eine Doppelseite gar keinen vorlesbaren Text liefert, werden
  trotzdem `PageRecord`s gespeichert
- die Runtime bricht dann die Wartephase sauber ab und spielt `fehler`

## Wichtigste Dateien fuer den naechsten Chat

### Jetzt bereits stabil und relevant

- [hardware/control_panel_service.py](../hardware/control_panel_service.py)
- [abr/control/runtime.py](../abr/control/runtime.py)
- [abr/capture_ocr.py](../abr/capture_ocr.py)
- [abr/ocr/rapidocr_backend.py](../abr/ocr/rapidocr_backend.py)
- [abr/book/store.py](../abr/book/store.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/models.py](../abr/book/models.py)
- [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)
- [abr/remote_mail.py](../abr/remote_mail.py)
- [deploy/install_remote_mail.sh](../deploy/install_remote_mail.sh)
- [abr/usage_statistics.py](../abr/usage_statistics.py)
- [abr/usage_report.py](../abr/usage_report.py)
- [deploy/install_usage_statistics.sh](../deploy/install_usage_statistics.sh)
- [docs/USAGE_STATISTICS.md](../docs/USAGE_STATISTICS.md)
- [abr/wifi_profiles.py](../abr/wifi_profiles.py)
- [deploy/install_wifi_autoconnect.sh](../deploy/install_wifi_autoconnect.sh)
- [docs/WIFI_PROFILES.md](../docs/WIFI_PROFILES.md)
- [docs/SYSTEMD_CONTROL_PANEL_SERVICE.md](../docs/SYSTEMD_CONTROL_PANEL_SERVICE.md)
- [hardware/pn5180_gateway_client.py](../hardware/pn5180_gateway_client.py)
- [hardware/pn5180_gateway/src/pico_gateway.cpp](../hardware/pn5180_gateway/src/pico_gateway.cpp)
- [hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO14443.cpp](../hardware/pn5180_gateway/lib/PN5180_Library_Minimal/src/PN5180ISO14443.cpp)

### Startpunkt fuer das naechste Thema

Naechste sinnvolle Vertiefungen sind:

- Qualitaet der Abschnittsgrenzen mit echtem Buchmaterial nachjustieren
- Summary-Prompts, Modelle, Token-Skalierung und Fehlertoleranz auf dem Pi
  testen
- spaetere Status-/Telemetry-Ereignisse fuer Abschnitt und Summary ergaenzen
- ohne Vermischung mit `RuntimeController`
- den integrierten PN5180-Dual-Reader-Pfad mit beiden Tag-Technologien im
  Dauerbetrieb pruefen

Ziel fuer den Folgechat:

1. Abschnittsgrenzen mit echtem Material gegenpruefen und nachjustieren
2. Summary-Qualitaet und -Laenge mit echten Pi-Laeufen feinjustieren
3. Status-/Telemetry-Ereignisse fuer Abschnitt und Summary ergaenzen

## Weitere Doku im Repo

- [readme.md](../readme.md)
- [readme_DE.md](../readme_DE.md)
- [docs/CONTROL_PANEL_ARCHITECTURE.md](../docs/CONTROL_PANEL_ARCHITECTURE.md)
- [docs/CONTROL_RUNTIME_ARCHITECTURE.md](../docs/CONTROL_RUNTIME_ARCHITECTURE.md)
- [docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md](../docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [docs/SOFTWARE_STRUCTURE.md](../docs/SOFTWARE_STRUCTURE.md)
- [docs/REMOTE_MAINTENANCE_EMAIL.md](../docs/REMOTE_MAINTENANCE_EMAIL.md)
- [docs/USAGE_STATISTICS.md](../docs/USAGE_STATISTICS.md)
- [docs/WIFI_PROFILES.md](../docs/WIFI_PROFILES.md)
