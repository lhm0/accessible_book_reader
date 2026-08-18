# Buchsprachen Deutsch und U.S.-Englisch

Stand: `2026-08-07` – Etappen 1 bis 5 und mehrsprachige Systemhinweise implementiert

## Ziel

Der ABR soll deutsche und englischsprachige Buecher verarbeiten koennen. Die
Sprache wird bewusst per Befehl gewaehlt; eine automatische Spracherkennung
ist nicht vorgesehen. Englisch verwendet durchgaengig U.S.-Englisch
(`en-US`).

Der bestehende deutsche Produktpfad bleibt Default. Fehlt die neue
Konfigurationsdatei, verwendet der Code exakt die bisherigen deutschen Werte.

## Etappe 1: zentrale Sprachprofile

Implementiert sind:

- [abr/language_config.py](../abr/language_config.py)
- unveraenderlicher `LanguageProfile` fuer `de`
- unveraenderlicher `LanguageProfile` fuer `en` mit U.S.-Englisch
- persistente Auswahl unter `~/.config/abr/device.json`
- atomisches Schreiben mit Dateimodus `0600`
- fehlende Konfiguration faellt auf Deutsch zurueck
- ungueltige Konfiguration bricht mit einer deutlichen Fehlermeldung ab
- CLI fuer `status`, `set` und idempotentes `init`
- Installer fuer den Systembefehl `abr-language`

Vorbereitete Werte:

| Wert | Deutsch | Englisch |
|---|---|---|
| Profilcode | `de` | `en` |
| OCR-Sprache | `de` | `en` |
| Google-Sprachcode | `de-DE` | `en-US` |
| Google-Standardstimme | `de-DE-Standard-H` | `en-US-Standard-D` |
| Google-Neural2-Stimme | `de-DE-Neural2-H` | `en-US-Neural2-D` |
| Kapitelwort | `Kapitel` | `Chapter` |
| Summary-Sprache | German | English |

Auch die Promptvorlage fuer Gemini Flash TTS ist pro Profil vorbereitet.

## Etappe 2: Runtime, TTS und Kapitelansagen

Die produktive Runtime liest `~/.config/abr/device.json` beim Start. Eine
ungueltige vorhandene Konfiguration verhindert den Start mit einer deutlichen
Fehlermeldung; eine fehlende Datei verwendet weiterhin Deutsch.

Das aktive Profil steuert jetzt:

- Google-Standardstimme und `languageCode`
- Google Neural2-Stimme
- ElevenLabs-Sprachcode
- deutschen oder U.S.-englischen Gemini-Flash-Hoerbuchprompt
- Kapitelwort `Kapitel` oder `Chapter`
- ausgeschriebene isolierte Kapitelnummern, zum Beispiel
  `Kapitel zwei.` oder `Chapter forty-two.`
- Kapitelpausen im normalen und im Enhanced-SSML-Renderer

Das aktive Profil waehlt auch die vorproduzierten Systemhinweise aus
`system_audio/messages/de/` beziehungsweise `system_audio/messages/en/`.
Die logischen Dateinamen wie `bing`, `fehler` und `buch_nicht_erkannt` bleiben
in beiden Ordnern identisch. Dadurch muss die Runtime nur den Sprachordner,
nicht aber einzelne Meldungsnamen umschalten. Da das Profil beim Dienststart
gelesen wird, wird die Auswahl nach dem von `abr-language` ausgefuehrten
Dienstneustart wirksam.

## Etappe 3: RapidOCR

Der OCR-Sprachcode wird jetzt durchgaengig transportiert:

- `CaptureOCRJobConfig.language`
- `hardware/run_rapidocr.py --language de|en`
- normaler und inkrementeller Runtime-Pfad
- Orientierungstest und finale Seitenerkennung
- `ocr_language` in `report.json` und den `ScanRecord`-Metadaten
- Sprache und Modellprofil in den Metadaten jeder RapidOCR-Zeile

Die Modellstrategie schuetzt den bestaetigten deutschen Stand:

- `de` konstruiert weiterhin exakt den bisherigen parameterlosen
  `RapidOCR()`-Enginepfad
- `en` verwendet fuer die Recognition-Stufe explizit
  `LangRec.EN`, `ModelType.MOBILE` und `OCRVersion.PPOCRV5`
- deutsche und englische Engines werden getrennt im Prozess gehalten

RapidOCR muss mindestens Version `3.4` haben. Die optionale Abhaengigkeit ist
deshalb jetzt auf `rapidocr>=3.4,<4` begrenzt. Auf dem Pi nach dem Update:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install -e ".[ocr-rapidocr]"
```

Beim ersten englischen OCR-Lauf kann RapidOCR das englische Modell laden. Das
sollte bei bestehender Internetverbindung einmal vor dem eigentlichen
Erprobungslauf erfolgen. Mit vorhandenen Capture-Bildern:

```bash
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/english_rapidocr \
  --orientation-mode off \
  --language en \
  --overlay
```

Danach stehen Sprache und Modellprofil im Report:

```bash
python -m json.tool runs/english_rapidocr/report.json | less
```

Die API-Konfiguration folgt der offiziellen
[RapidOCR-Modelluebersicht](https://rapidai.github.io/RapidOCRDocs/latest/model_list/).

## Etappe 4: Zusammenfassungen und Cache

Das aktive Sprachprofil wird beim Start an den `SummaryManager` uebergeben.
Es steuert jetzt:

- Kapitelzusammenfassungen
- temporaere Rueckschauen aus fertigem Abschnitt und offenen Seiten
- Buchrueckschauen im Stil `Was bisher geschah` beziehungsweise
  `Previously in the book`
- den zweiten Kuerzungsdurchlauf bei Ueberschreitung des Wortlimits
- englische Seitenbereichsbezeichnungen in den Gemini-Prompts

Die englischen Instruktionen verlangen natuerliches U.S.-Englisch und
gut vorlesbaren Fliesstext. Die deutschen Prompttexte bleiben unveraendert.

Persistente Kapitel- und Buchzusammenfassungen tragen jetzt
`metadata.language` mit `de` oder `en`. Ein Cache wird nur wiederverwendet,
wenn seine Sprache zum aktiven Profil passt. Alte Summary-Dateien ohne Sprachfeld
werden aus Kompatibilitaetsgruenden als Deutsch behandelt; vorhandene deutsche
Caches bleiben dadurch gueltig. Temporaere Rueckschauen werden weiterhin nicht
gespeichert, tragen ihre Sprache aber ebenfalls in den Laufzeitmetadaten.

## Etappe 5: Buchschutz und Integration

Beim ersten Scan eines neuen NFC-Buchs wird das aktive Profil dauerhaft als
`BookRecord.language` in `book.json` gespeichert. Danach gelten folgende
Schutzregeln:

- OCR-Report und aktives Profil muessen uebereinstimmen
- aktives Profil und gespeicherte Buchsprache muessen uebereinstimmen
- alle Seiten eines Buchs muessen dieselbe Sprache wie das Buch tragen
- Kapitel erhalten die validierte Buchsprache in ihren Metadaten
- Summary-Erzeugung und Summary-Wiedergabe lehnen eine andere Sprache ab
- Seitenausgabe lehnt Seiten ab, deren Sprache nicht zur aktiven TTS-Sprache passt

Ein englisch angelegtes Buch kann daher nicht versehentlich im deutschen Modus
fortgesetzt oder zusammengefasst werden und umgekehrt. Vor dem Wechsel zu einem
anderen Buch muss zuerst dessen Sprache mit `abr-language` aktiviert werden.

Alte Buecher ohne `language` gelten bewusst als Deutsch. Wird ein solches Buch
im deutschen Modus erneut eingelesen, wird `language: de` nachgetragen. Dadurch
bleibt der bisherige deutsche Bestand kompatibel.

Englische Erprobungsbuecher, die bereits vor Etappe 5 angelegt wurden, muessen
einmal kontrolliert migriert oder neu angelegt werden. `language` darf dabei nur
auf `en` gesetzt werden, wenn die Seitenmetadaten durchgaengig `en` enthalten.
Fuer das aktuelle Erprobungsbuch kann dies nach Sicherung und Sichtpruefung mit
einem kleinen Python-Lauf erfolgen:

```bash
cp library/53C78C6D220001/book.json \
  library/53C78C6D220001/book.json.before-language-migration

.venv/bin/python - <<'PY'
from dataclasses import replace
from pathlib import Path
from abr.book import BookStore

tag_id = "53C78C6D220001"
store = BookStore(Path("library"))
book = store.load_book(tag_id)
if book is None:
    raise SystemExit("Buch nicht gefunden")
if book.language not in {None, "en"}:
    raise SystemExit(f"Buch ist bereits als {book.language} gebunden")
bad_pages = [
    page.page_id for page in store.list_pages(tag_id)
    if page.metadata.get("language") != "en"
]
if bad_pages:
    raise SystemExit(f"Migration abgebrochen; nicht-englische Seiten: {bad_pages}")
store.save_book(replace(book, language="en"))
print(f"{tag_id} wurde sicher auf en gebunden.")
PY
```

Der automatisierte Test `tests/test_english_book_integration.py` prueft:

```text
Capture-Bilder -> englischer OCR-Report -> Ingest -> BookRecord.language
-> Kapitel -> englische Summary -> en-US-TTS-Uebergabe
```

RapidOCR, Gemini und Google TTS werden darin durch deterministische Backends
ersetzt; ihre produktiven Schnittstellen und alle Sprachpruefungen werden real
durchlaufen. Der Qualitaets- und Laufzeittest mit echten Diensten bleibt ein
manueller Pi-Test.

Direkter Entwicklungstest ohne Installation:

```bash
.venv/bin/python -m abr.language_config status
.venv/bin/python -m abr.language_config set en
.venv/bin/python -m abr.language_config set de
```

Installation des Systembefehls auf dem Pi:

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
abr-language status
```

Umgeschaltet wird mit:

```bash
sudo abr-language en
sudo abr-language de
```

Der Befehl schreibt die Auswahl als konfigurierter Dienstbenutzer, startet danach
`abr-control-panel.service` neu und prueft, ob der Dienst aktiv ist. Der
Sprachwechsel gilt daher ab dem naechsten Scan; ein laufender Scan wird durch
den Dienstneustart beendet.

Der Installer legt eine fehlende Konfiguration mit `de` an. Eine bereits
gespeicherte Auswahl wird bei erneuter Installation nicht ueberschrieben.

## Erweiterung: mehrsprachige Systemhinweise

Die Bedienhinweise folgen jetzt ebenfalls dem manuell gewaehlten Profil. Das
Verzeichnislayout lautet:

```text
system_audio/messages/
  de/
    <logischer-name>.wav
  en/
    <logischer-name>.wav
```

`hardware/control_panel_service.py` erzeugt beim Start eine
`SystemAudioConfig`, deren `root_dir` auf den Unterordner
`language_profile.code` zeigt. Der Pfad wird absolut aus `PROJECT_ROOT`
gebildet und ist damit unabhaengig vom Arbeitsverzeichnis des systemd-Dienstes.
Alle Aufrufe in `RuntimeController` verwenden diese eine Konfiguration.

Die Dateinamen sind in beiden Sprachen identisch. Nur die Aufnahme ist
uebersetzt. Beim Hinzufuegen einer neuen Runtime-Meldung sind deshalb immer
eine deutsche und eine englische WAV-Datei anzulegen. Ein fehlender Hinweis
wird als Fehler gemeldet und nicht aus dem jeweils anderen Sprachordner
ersetzt.

Zum Erzeugen weiterer englischer Aufnahmen kann zum Beispiel verwendet werden:

```bash
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"

python hardware/generate_audio_message.py \
  --ssml \
  --output-root "$HOME/tmp_audio_export/en" \
  --google-tts-language-code en-US \
  --google-tts-voice-name en-US-Standard-C \
  fehler \
  '<speak>An error occurred.<break time="700ms"/>Please try again.</speak>'
```

Die explizite Zertifikatsvariable ist insbesondere auf dem Entwicklungs-Mac
noetig, wenn die Projekt-`.venv` auf PlatformIOs Python basiert und dessen
eingebauter CA-Pfad nicht existiert. Die SSL-Pruefung darf nicht abgeschaltet
werden.

## Tests der Etappen 1 bis 5 und der Systemhinweise

[tests/test_language_config.py](../tests/test_language_config.py)
deckt ab:

- deutscher Default ohne Konfigurationsdatei
- Erhalt der bisherigen deutschen Stimmen und Codes
- explizite U.S.-englische Werte
- atomische persistente Speicherung und Dateirechte
- idempotente Initialisierung
- Ablehnung unbekannter Sprachen
- Statusausgabe ohne unbeabsichtigtes Anlegen einer Datei
- unveraenderte deutsche Runtime-TTS-Werte
- U.S.-englische Runtime-TTS-Werte
- explizite Voice- und Prompt-Overrides
- sprachabhaengige Auswahl der deutschen und englischen Systemhinweise
- englische Zahlwoerter fuer isolierte Kapitelnummern
- englische Kapitelpausen im normalen und Enhanced-SSML-Pfad
- unveraenderter parameterloser RapidOCR-Konstruktor fuer Deutsch
- englische PP-OCRv5-Mobile-Modellauswahl
- getrennte Engine-Caches fuer Deutsch und Englisch
- Sprachweitergabe an Orientierungstest und Seitenerkennung
- `ocr_language` und OCR-Zeilenmetadaten im Report
- unveraenderte deutsche Summary-Prompts und Cache-Kompatibilitaet
- U.S.-englische Kapitel-, Fortschritts-, Buch- und Kuerzungsprompts
- Sprache in persistenten und temporaeren Summary-Metadaten
- sprachabhaengige Summary-Cachevalidierung
- persistente Sprachbindung neuer NFC-Buecher
- Deutsch-Migration alter Buecher ohne Sprachfeld
- Ablehnung gemischter OCR-, Seiten-, Summary- und TTS-Daten
- englischer Integrationstest vom Capture-Bild bis zur en-US-TTS-Uebergabe

Der reale Qualitaets- und Laufzeitvergleich mit englischen Buchseiten auf dem
Raspberry Pi bleibt als praktische Verifikation offen.
