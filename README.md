# Accessible Book Reader

Software- und Hardware-Repository fuer den `Accessible Book Reader` (`ABR`).

## Lizenz

Der Accessible Book Reader ist ein Open-Source-/Open-Hardware-Projekt mit
starkem Copyleft. Wegen der unterschiedlichen Arten von Projektmaterial gilt
ein klar abgegrenztes Mehrfachlizenzmodell:

- eigener Software- und Firmwarecode: `GPL-3.0-or-later`
- eigene Elektronik-, Mechanik- und sonstige Hardwaredesigns:
  `CERN-OHL-S-2.0`
- Dokumentation und eindeutig eigene Medien: `CC-BY-SA-4.0`
- Fremdbibliotheken: unveraendert unter ihrer jeweiligen Originallizenz

Die mit Google Cloud Text-to-Speech erzeugten Systemansagen enthalten einen
eigenen [Herkunfts- und Nutzungshinweis](system_audio/messages/README.md).

Die GPL und CERN-OHL-S erlauben auch kommerzielle Nutzung, verlangen bei der
Weitergabe abgeleiteter Software beziehungsweise Hardware aber die jeweils
vorgesehene Bereitstellung des vollstaendigen Quellmaterials unter den
Copyleft-Bedingungen. Eine allgemeine Ausnahme fuer geschlossene kommerzielle
Weiterentwicklungen besteht nicht.

Die verbindliche Abgrenzung, Ausnahmen fuer Fremdcode und Hinweise zu nicht
mitlizenzierten Drittmaterialien stehen in [LICENSE.md](LICENSE.md); die
vollstaendigen Lizenztexte liegen unter [`LICENSES/`](LICENSES/). Hinweise zu
eingebundenem Fremdcode stehen in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Fuer
Beitraege gelten [CONTRIBUTING.md](CONTRIBUTING.md) und die
[Contributor License Agreement](CLA.md). Die Contributor-Vereinbarung erhaelt
das Eigentum der Beitragenden, erlaubt dem Projektinhaber aber zusaetzlich eine
parallele kommerzielle Lizenzierung fuer spaetere Firmenkooperationen.
Firmenkooperationen, die von diesen oeffentlichen Lizenzen abweichen sollen,
erfordern einen separaten Entwicklungs- und Lizenzvertrag mit den jeweiligen
Rechteinhabern.

Es wurde keine Patent- oder Freedom-to-Operate-Recherche durchgefuehrt. Die
Lizenzen koennen nur Rechte einraeumen, ueber die der jeweilige Lizenzgeber
verfuegen darf; sie geben keine Zusicherung, dass Herstellung, Nutzung oder
Vertrieb keine Rechte Dritter beruehren. Der vollstaendige Hinweis und die
besondere Abgrenzung zwischen privatem Nachbau und kommerzieller Nutzung
stehen in [PATENT_NOTICE.md](PATENT_NOTICE.md).

Der Projektstand ist inzwischen ueber den reinen OCR-/TTS-Prototyp hinaus:

- realer Capture-Pfad mit `2` Pi-Kameras ist verifiziert
- `RapidOCR` laeuft stabil auf dem Pi
- `Google Cloud TTS` ist integriert
- Bedienpanel, NFC-Buchkontext, Seitenspeicherung und automatische
  Seitenausgabe sind implementiert
- E-Mail-Fernwartung fuer Datei-Download und kontrollierten Datei-Upload ist
  implementiert
- mehrere gespeicherte WLAN-Profile koennen automatisch ausgewaehlt oder
  gezielt umgeschaltet werden
- zentrale Buchsprachenprofile fuer Deutsch und U.S.-Englisch steuern
  Runtime-TTS, Kapitelansagen und die RapidOCR-Modellauswahl; Deutsch bleibt
  der kompatible Default
- neue NFC-Buecher speichern ihre Sprache dauerhaft in `book.json`; OCR,
  Ingest, Kapitel, Zusammenfassungen und TTS verhindern gemischte Buchdaten

Der aktuelle Entwicklungsschwerpunkt liegt jetzt auf:

- Stabilisierung und Feinschliff der neuen Abschnitts- und Summary-Ebene
- Langzeittest des integrierten PN5180-Zwei-Reader-Pfads mit
  `ISO14443A` und `ISO15693`

## Aktueller Produktpfad

Der derzeit bevorzugte reale Lauf auf dem Raspberry Pi 5 ist:

- Runtime: `hardware/control_panel_service.py`
- TTS fuer Seiten: `Google Cloud TTS`, Stimme aus dem aktiven Sprachprofil
- Systemhinweise: vorproduzierte WAV-Dateien aus dem Unterordner des aktiven
  Sprachprofils (`system_audio/messages/de/` oder `system_audio/messages/en/`)
- Buchidentifikation: `PN5180`-Gateway ueber UART
- Audiohardware: `MAX98357A` ueber I2S; ALSA-`default` muss systemweit per
  symbolischem Kartennamen auf diese Karte zeigen

Im Runtime-Pfad gilt aktuell:

- beim Start wird die PN5180-Abfrage sofort per `STATUS_START` angestossen
- die beiden Fotos werden aufgenommen, bevor das Ergebnis per `STATUS_FETCH`
  fuer Buchzuordnung und Orientierung abgeholt wird
- `ISO14443A` ist der fuehrende Buchschluessel; ein gleichzeitig gelesener
  `ISO15693`-Tag wird im Buchordner als alternative Zuordnung gespeichert
- Reader 2 kennzeichnet Orientierung 1: die beim Capture erzeugte
  Links-/Rechts-Zuordnung bleibt bestehen
- Reader 1 kennzeichnet Orientierung 2: `case/left.jpg` und
  `case/right.jpg` werden direkt nach `STATUS_FETCH` vertauscht
- danach wird `case/right.jpg` einmalig um `180` Grad gedreht; in der
  OCR-Vorverarbeitung erfolgt keine weitere feste Seitendrehung
- beide Seiten werden zuerst komplett aufgenommen
- danach wird links vor rechts verarbeitet
- Bildvorbereitung, OCR, `PageIngestor` und TTS starten zunaechst nur fuer die
  linke Seite
- waehrend die linke Seite bereits abgespielt wird, folgen Bildvorbereitung,
  OCR, `PageIngestor` und TTS fuer die rechte Seite

## Was Jetzt Implementiert Ist

### Laufende Geraetelogik

- langlebiger Frontpanel-Monitor
- `Start / Stop / NFC` fuer echten Lauf `capture -> Bildvorbereitung -> OCR -> page-ingest`
- Heartbeat-Signal waehrend der Wartezeit bis zur ersten Seitenaudio
- abbrechbare Seitenausgabe
- Lautstaerkeregelung ueber EC11-Flankeninterrupts mit threadsicherem
  Sollwert; wirkt blockweise auch waehrend `bing.wav` und Seitenaudio
- Buch-Loeschdialog ueber Dreifachtaste und `EC11`-Taster
- persistente, buchweise Nutzerstatistik fuer gescannte Seiten,
  Vorlesedauer und beide Zusammenfassungsfunktionen; taeglicher E-Mail-Report
  fuer den Zeitraum `04:00` bis `04:00`, auch an Tagen ohne Nutzung

### Buch- und Seitendaten

- Speicherung pro Buch unter `library/<TAG_ID>/`
- alternative ISO15693-Zuordnungen unter
  `library/<ISO14443A_TAG_ID>/iso15693_tag_ids.txt`
- `BookStore`
- `PageIngestor`
- `ChapterAssembler` fuer 10-20 Seiten lange Abschnitte mit Mid-Page-Grenzen
- `SummaryManager` fuer Abschnitts- und Gesamtzusammenfassungen ueber Gemini
- `PageRecord`-Ablage pro Seite
- `ChapterRecord`-Ablage pro Abschnitt
- `ScanRecord`-Ablage pro Doppelseite
- automatische Seitenausgabe auf Basis von `speak_text`

### Bereits sauber behandelte Textfaelle

- fehlende Seitenzahl auf nur einer Seite eines vollstaendigen Doppelseiten-
  Reports
- mehrere Kapitelmarker auf einer Seite
- reine Ueberschriftenseiten wie `INTERMEZZO`
- unvollstaendige Satzreste ueber Seiten hinweg
- Worttrennungen ueber Zeilen und ueber die linke/rechte Seitenkante
- gesperrt gesetzte Woerter wie `U E B E R S C H R I F T` werden fuer die
  Ausgabe ohne Buchstabenabstaende geschrieben
- kurze, vollstaendig grossgeschriebene Ueberschriften werden im
  `speak_text` lesbar geschrieben und als eigener Absatz markiert
- deutsche Vorlesetexte ersetzen `Dr.` durch `Doktor` und `Notre-Dame` durch
  `Notre Damm`; der originalgetreue `clean_text` bleibt unveraendert
  (bereits gespeicherte Seiten erhalten diese Ersetzungen erst bei erneutem
  Page-Ingest)
- kurze eingeklammerte OCR-Artefakte mit Ziffern werden nicht als Satzrest
  auf die Folgeseite uebernommen
- Kapitelansagen als Kardinalzahlen wie `Kapitel zwei`
- deutliche SSML-Pausen vor und nach Kapitelansagen

Wichtig zum aktuellen Satzrest-Verhalten:

- der Satzrest einer rechten Seite wird zusaetzlich unter
  `library/<TAG_ID>/state/pending_right_tail_fragment.json` gehalten
- fehlt bei einer frueh ingestierten linken Einzelseite die Seitenzahl, wird
  genau dieser Pending-Speicher fuer den Uebergang zur naechsten Seite genutzt

## Was Jetzt Neu Hinzugekommen Ist

- Abschnitte werden nach jedem Ingest aus vorhandenen `PageRecord`s gebildet
- Abschnittsenden liegen an der ersten erkannten Kapitelgrenze im Fenster
  `10..20` Seiten
- ohne Kapitelmarke endet ein Abschnitt am letzten vollstaendigen Absatz der
  `20.` Seite; die Folgegrenze wird persistent gespeichert
- abgeschlossene Abschnitte werden unter `library/<TAG_ID>/chapters/`
  gespeichert
- neue Abschnittszusammenfassungen werden direkt beim Erzeugen eines neuen
  Abschnitts ueber Gemini geschrieben
- `Kapitel-/Letzte-Seiten-Zusammenfassung` spricht die letzte
  Abschnittszusammenfassung, erzeugt oder aktualisiert sie bei Bedarf und
  signalisiert waehrenddessen per Intro plus `bing`-Heartbeat
- liegt nach dem letzten abgeschlossenen Abschnitt bereits weiterer Text vor,
  kombiniert dieselbe Taste dessen gespeicherte Zusammenfassung mit dem
  offenen Text zu einer temporaeren aktuellen Rueckschau; diese wird nur
  vorgelesen und nicht gespeichert
- vor dem ersten abgeschlossenen Abschnitt wird der vorhandene offene Text
  allein temporaer zusammengefasst
- `Buch-Zusammenfassung` erzeugt und spricht ein aktuelles
  "Was bisher geschah" in Kapitelreihenfolge, ebenfalls mit Intro plus
  `bing`-Heartbeat
- wenn noch keine Zusammenfassung vorliegt, spielt die Runtime
  `keine_zusammenfassung`

## Installation

Die README ist der Einstieg fuer eine Neuinstallation. Die ausfuehrliche,
hardwarebezogene Schritt-fuer-Schritt-Anleitung steht in
[docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md); der abschliessende
Funktionstest steht in
[docs/RASPBERRY_PI_SMOKETEST.md](docs/RASPBERRY_PI_SMOKETEST.md).

### 1. Raspberry Pi vorbereiten und Repository auschecken

Empfohlen ist Raspberry Pi OS Lite (64-bit). Nach dem ersten Boot und dem
Systemupdate werden die benoetigten Systempakete installiert:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  git curl ca-certificates \
  build-essential pkg-config \
  python3 python3-venv python3-pip python3-dev \
  tesseract-ocr tesseract-ocr-deu \
  libgl1 libopenblas-dev \
  espeak-ng alsa-utils pulseaudio-utils \
  htop tmux

mkdir -p ~/src
git clone https://github.com/lhm0/accessible_book_reader.git ~/src/abr
cd ~/src/abr
```

Die Kameras, der Header-UART und der MAX98357A benoetigen zusaetzlich die in
[docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md) beschriebenen
Eintraege in `/boot/firmware/config.txt` sowie die dort dokumentierte
`/etc/asound.conf`. Die Repository-Datei `config.txt` ist eine Referenz fuer
die verifizierte Hardware, darf aber nicht ungeprueft eine vorhandene
Boot-Konfiguration ersetzen. Anschliessend neu starten und Kameras, UART und
Audio wie in der Setup-Anleitung pruefen.

Die Firmware und Verdrahtung des bevorzugten PN5180-Gateways sind unter
[hardware/pn5180_gateway/README.md](hardware/pn5180_gateway/README.md)
dokumentiert. Alternativ steht der PN532-Pfad unter
[hardware/pn532_gateway/README.md](hardware/pn532_gateway/README.md).

### 2. Python-Umgebung installieren

Empfohlen ist eine frische virtuelle Umgebung mit dem normalen `python3`,
nicht mit dem PlatformIO-Python und nicht aus einem anderen Rechner kopiert.

```bash
cd ~/src/abr
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[ocr-rapidocr,dev,tts-google]"
```

Optional:

```bash
pip install ".[ocr-tesseract]"
pip install ".[ocr-paddle]"
```

### 3. Google Cloud fuer TTS und Zusammenfassungen einrichten

Der produktive Dienst benoetigt Application Default Credentials (`ADC`) eines
Google-Cloud-Projekts, in dem die verwendeten APIs und Abrechnung aktiviert
sind. Nach Installation des Google-Cloud-CLI fuer Raspberry Pi OS:

```bash
gcloud services enable \
  texttospeech.googleapis.com \
  aiplatform.googleapis.com \
  --project DEIN_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project DEIN_PROJECT_ID
gcloud config set project DEIN_PROJECT_ID
```

Die Befehle legen die Anmeldedaten ausserhalb des Repositorys unter
`~/.config/gcloud/` ab. Keine Credential-Datei in das Projekt kopieren. Der
systemd-Installer setzt `HOME` auf das Home-Verzeichnis des installierenden
Benutzers, sodass der Dienst dieselben ADC-Daten findet. Alternativ kann ein
Service-Account ueber den von Google dokumentierten ADC-Mechanismus
bereitgestellt werden. Details und Testbefehle stehen in
[docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md).

### 4. Lokale Geraetekonfiguration und Dienste

Die Installer werden aus dem Repository mit `sudo` aufgerufen. Sie ermitteln
Benutzer, Home-Verzeichnis, Repository und `.venv` aus der aktuellen
Installation; ein bestimmter Benutzername oder absoluter Projektpfad ist
nicht erforderlich.

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
sudo deploy/install_control_panel_service.sh
```

Damit wird `~/.config/abr/device.json` bei Bedarf mit Deutsch als Default
angelegt und der produktive Dienst installiert. Die Sprache kann danach mit
`sudo abr-language de` beziehungsweise `sudo abr-language en` gesetzt werden.
Details stehen in [docs/LANGUAGE_PROFILES.md](docs/LANGUAGE_PROFILES.md).

Weitere Funktionen sind optional:

```bash
# Gespeicherte NetworkManager-WLAN-Profile beim Boot vorbereiten
sudo deploy/install_wifi_autoconnect.sh

# Beim ersten Lauf mail.ini anlegen, dann ausfuellen und erneut aufrufen
sudo deploy/install_remote_mail.sh
sudo deploy/install_remote_mail.sh

# Erst nach eingerichteter mail.ini installieren
sudo deploy/install_usage_statistics.sh
```

WLAN-Zugangsdaten bleiben in NetworkManager; neue Profile werden mit den
Befehlen aus [docs/WIFI_PROFILES.md](docs/WIFI_PROFILES.md) interaktiv
angelegt. Die E-Mail-Konfiguration wird im folgenden Abschnitt sowie in
[docs/REMOTE_MAINTENANCE_EMAIL.md](docs/REMOTE_MAINTENANCE_EMAIL.md)
beschrieben.

### Lokale und generierte Konfigurationsdateien

| Pfad | Inhalt und Erzeugung | Im Repository? |
|---|---|---|
| `/boot/firmware/config.txt` | Kamera-, UART- und I2S-Konfiguration; manuell nach Pi-Setup-Anleitung | Nein |
| `/etc/asound.conf` | ALSA-Default fuer MAX98357A; manuell nach Pi-Setup-Anleitung | Nein |
| `~/.config/gcloud/` | Google ADC und Quota-Projekt; durch `gcloud` oder Service-Account | Nein |
| `~/.config/abr/device.json` | Buchsprache; durch `install_language_switch.sh` | Nein |
| `~/.config/abr/mail.ini` | Mailkonto und Empfaenger; neutrale Vorlage durch `install_remote_mail.sh` | Nein |
| NetworkManager-Profile | SSIDs und WLAN-Passwoerter; interaktiv mit `abr.wifi_profiles` | Nein |
| `/etc/systemd/system/abr-*.service` und `abr-*.timer` | Lokale Benutzer- und Projektpfade; durch die Installer erzeugt | Nein |
| `calibration/out/cam0_planar.npz`, `cam1_planar.npz` | Mitgelieferte Referenzkalibrierung; fuer abweichende Kameramechanik neu erzeugen | Ja |

Es gibt keine erforderliche `.env`-Datei. API-Schluessel fuer optionale
experimentelle Backends werden nur ueber `OPENAI_API_KEY` beziehungsweise
`ELEVENLABS_API_KEY` aus der lokalen Prozessumgebung gelesen; der produktive
Google-Pfad verwendet ADC.

### 5. Installation pruefen

```bash
cd ~/src/abr
source .venv/bin/activate
python -m pytest -q
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 100 --no-pager
```

Danach den Hardware- und Runtime-Smoke-Test aus
[docs/RASPBERRY_PI_SMOKETEST.md](docs/RASPBERRY_PI_SMOKETEST.md)
durchfuehren.

### Lokale E-Mail-Konfiguration

Persoenliche Mailadressen, Benutzernamen und Passwoerter werden nicht im
Repository gespeichert. Der Mailbetrieb liest sie auf dem Raspberry Pi aus
`~/.config/abr/mail.ini`.

Eine Vorlage wird beim ersten Aufruf von
`sudo deploy/install_remote_mail.sh` mit Dateimodus `0600` angelegt. Danach
die lokale Datei bearbeiten:

```ini
[mail]
address = abr-device@example.com
recipient = owner@example.com
username = abr-device@example.com
password = PASSWORT_FUER_E_MAIL_PROGRAMME
smtp_host = smtp.example.com
smtp_port = 465
imap_host = imap.example.com
imap_port = 993
inbox = INBOX
```

`address` und `username` bezeichnen das Konto des Geraets. An `recipient`
gehen Fernwartungsdateien und Nutzungsberichte; nur exakt diese Adresse wird
zugleich als Absender fuer Upload-Mails akzeptiert. Die echten Werte bleiben
ausschliesslich in dieser lokalen, nicht versionierten Datei. Bei einer
bestehenden Installation ohne `recipient` wird aus Kompatibilitaetsgruenden
der Wert von `address` verwendet.

Wichtig:

- `rapidocr` plus `onnxruntime` sind fuer den Hauptpfad noetig
- `Tesseract` bleibt Fallback und Vergleich
- `PaddleOCR` ist auf dem Raspberry Pi derzeit kein belastbarer Produktpfad
- fuer automatische Zusammenfassungen werden dieselben Google-Cloud-
  Zugangsdaten wie fuer den aktuellen TTS-Pfad verwendet (`ADC` /
  Service-Account / `gcloud auth application-default login`)
- `target-pages` wird mit `250` Woertern pro Textseite in eine konkrete
  Wortzielgrenze umgerechnet; `0.5` bedeutet somit ein Ziel von `125` Woertern
- Gemini erhaelt ein grosszuegiges technisches Tokenbudget, damit interne
  Thinking-Tokens die sichtbare Antwort nicht vorzeitig abschneiden
- liegt die erste Antwort mehr als zehn Prozent ueber der Wortgrenze, folgt
  automatisch ein eigener Kuerzungsdurchlauf
- nur eine nicht wegen des Tokenlimits abgebrochene Gemini-Antwort wird mit
  `generation_complete=true` gespeichert; alte Summary-Dateien ohne diesen
  Merker werden beim naechsten Aufruf einmalig neu erzeugt
- auf dem Raspberry Pi muss `/etc/asound.conf` ein `plug`-PCM namens `default`
  auf `hw:CARD=MAX98357A,DEV=0` legen; sonst kann `aplay` versehentlich HDMI
  oeffnen und mit `Unknown error 524` abbrechen
- vollstaendige Einrichtung und Diagnose:
  [docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md)

## Schnellstart

### Manueller Pi-Referenzlauf fuer Capture und OCR

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/capture_double_page.py --no-denoise
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/latest_rapidocr \
  --orientation-mode off \
  --overlay
```

### Voller Runtime-Dienst auf dem Pi

Fuer kurze manuelle Tests kann die Runtime weiterhin direkt gestartet
werden. Im Dauerbetrieb wird der SSH-unabhaengige systemd-Dienst
`abr-control-panel.service` verwendet; Installation, Logs, Neustarttest und
Fehlersuche stehen in
[docs/SYSTEMD_CONTROL_PANEL_SERVICE.md](docs/SYSTEMD_CONTROL_PANEL_SERVICE.md).

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

### Separater Neural2-H-Test

Der bestehende produktive Google-Pfad bleibt unveraendert:

- Backend `google`
- Stimme `de-DE-Standard-H`
- ohne weiteren Parameter weiterhin der Default

Neural2-H ist als eigener Opt-in-Pfad gekapselt und wird nur mit diesem
Zusatz aktiviert:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-neural2 \
  --page-tts-speed 0.85
```

Rueckkehr zum bisherigen Stand:

```bash
--page-tts-backend google
```

Oder den Parameter ganz weglassen. Optional kann im Neural2-Testpfad eine
andere Neural2-Stimme mit `--google-neural2-voice-name` gewaehlt werden;
Standard ist `de-DE-Neural2-H`.

### Standard-H mit erweiterter SSML-Aufbereitung

Der optionale Pfad `google-standard-enhanced` verwendet weiterhin
`de-DE-Standard-H` und dasselbe Google-Cloud-TTS-Backend. Nur die
Textaufbereitung ist erweitert: Absätze und Sätze werden strukturiert,
Kapitel behalten ihre lange Pause und kurze Überschriften werden moderat
hervorgehoben und vom Folgetext abgesetzt. Bei Fragen wird versuchsweise das
vollständige letzte Wort um `+3st` angehoben. Der Renderer prüft, dass keine
gesprochenen Wörter verändert wurden; andernfalls verwendet er automatisch
die bisherige SSML-Aufbereitung. Nach Saetzen innerhalb eines Absatzes wird
eine Pause von `900ms` gesetzt; nach dem letzten Satz jedes Absatzes sind es
stattdessen `2000ms`.
Die Absatzgrenzen stammen aus den `layout_blocks` des OCR-Reports und werden
beim Page-Ingest als Leerzeilen in `speak_text` übernommen. Als Fallback für
bereits gespeicherte Seiten gilt im Enhanced-Renderer außerdem ein einfacher
Zeilenumbruch nach `.` oder `?` als Absatzende. Ein direkt folgendes
schließendes Anführungszeichen wird dabei berücksichtigt.
Folgt auf einen vollstaendig eingerahmten Dialogsatz in `"..."`, `»...«` oder
`„...“` ein neuer Absatz, wird diese konkrete Absatzgrenze fuer die
Audioausgabe wie eine normale Satzgrenze behandelt: Es gelten `900ms` statt
`2000ms` Pause. Die gespeicherten Absatzdaten bleiben dabei erhalten.

Aktivierung:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-standard-enhanced \
  --page-tts-speed 0.9
```

Der unveränderte Standard-H-Pfad bleibt mit
`--page-tts-backend google` beziehungsweise ohne den Schalter verfügbar.

### Kontrolle der Blaetterrichtung und wiederholter Seiten

Die Runtime merkt sich pro Buch die Seitenzahlen der zuletzt zur Wiedergabe
angenommenen Doppelseite:

- ueberschneidet sich ein neuer Scan mit diesen Seitenzahlen, wird
  `system_audio/messages/<Sprache>/repeat_page.wav` abgespielt und die Seitenausgabe
  dieses Scans abgebrochen
- liegt die kleinste neue Seitenzahl unter der kleinsten zuletzt
  vorgelesenen Seitenzahl, wird
  `system_audio/messages/<Sprache>/wrong_direction.wav` abgespielt und die
  Seitenausgabe dieses Scans abgebrochen
- der unmittelbar folgende neue Scan darf die jeweils beanstandete
  Bedingung einmal passieren; der zugehoerige Merker wird dabei
  zurueckgesetzt
- trifft nach einer Warnung noch das rechte Teilergebnis desselben Scans
  ein, wird auch dieses nicht vorgelesen
- Scans ohne erkannte Seitenzahl werden ohne diese beiden Pruefungen
  ausgegeben

Die Merker und die zuletzt vorgelesenen Seiten werden getrennt pro Buch
verwaltet und beim Loeschen eines Buches entfernt.
Die beiden Seitenfolge-Hinweise werden direkt im Ingest-Ablauf abgespielt,
nicht ueber die allgemeine asynchrone Systemaudio-Warteschlange. Im
Runtime-Log erscheinen Start und erfolgreicher Abschluss; bei einer
fehlenden WAV-Datei wird der konkrete Pfad als Fehler ausgegeben.
Im inkrementellen Capture-Pfad wartet der Runner nach OCR links auf das
zugehoerige Page-Ingest-Ergebnis. Loest dieses eine Warnung aus, wird der
Foreground-Job abgebrochen, bevor Bildvorbereitung und OCR rechts beginnen.
Nach Abschluss der Warnung kehrt die Runtime ueber das normale
`CANCELLED`-Ereignis in `IDLE` zurueck.

### Lange Zusammenfassungen

Kapitel- und Buchzusammenfassungen werden vor Google TTS anhand vollstaendiger
Saetze in mehrere Audioteile zerlegt, wenn die gerenderte Eingabe sonst zu
gross wuerde. Fuer Zusammenfassungen bleiben pro Teil inklusive SSML maximal
`900` Byte; die allgemeinere Google-Sicherheitsgrenze liegt bei `3800` Byte.
Die Teile laufen ueber dieselbe Audio-Queue und werden in Reihenfolge
vorgelesen. Im Log steht die Anzahl der erzeugten Teile; die einzelnen
Labels tragen den Zusatz `1/N`, `2/N` usw. Kurze Zusammenfassungen bleiben
unveraendert eine einzelne TTS-Anfrage.

Die vorproduzierte Summary-Ansage und das erste `bing` werden vor dem
Summary-Job synchron abgespielt. Heartbeats, die nach Aktivierung der
Summary-Audio noch in der Queue liegen, werden verworfen. Dadurch kann kein
verspaetetes `bing` mehr nach der Zusammenfassung erklingen.

Die Cache-Gültigkeit von `book_so_far_summary.json` berücksichtigt neben den
Kapitel-IDs einen SHA-256-Fingerabdruck aus Inhalt und Aktualisierungszeit
aller Kapitelzusammenfassungen. Dadurch wird eine alte kurze
Buchzusammenfassung neu erzeugt, sobald ihre Quellen korrigiert oder
erweitert wurden. Alte Buch-Summary-Dateien ohne Fingerabdruck werden beim
nächsten Aufruf einmalig erneuert.

Kapitel- und Buchzusammenfassungen folgen außerdem dem aktiven Sprachprofil:
Deutsch verwendet weiterhin die bisherigen deutschen Prompts, Englisch
verwendet U.S.-englische Prompts. Persistente Summary-Dateien speichern die
Sprache unter `metadata.language`. Ein anderssprachiger Cache wird neu erzeugt;
alte Cachedateien ohne Sprachfeld gelten kompatibel als Deutsch.

### Separater Gemini-2.5-Flash-TTS-Test

Gemini TTS ist ebenfalls nur als eigener Opt-in-Pfad aktiv:

```bash
python hardware/control_panel_service.py \
  --gpio-backend auto \
  --job-mode capture-ocr \
  --library-root library \
  --nfc-mode gateway \
  --page-tts-backend google-gemini-flash \
  --page-tts-speed 0.85
```

Standardwerte dieses Versuchspfads:

- Modell `gemini-2.5-flash-tts`
- Stimme `Charon`
- eigener deutscher Hoerbuch-Prompt
- Klartexteingabe statt SSML; Pausen und Vortragsstil werden ueber den Prompt
  gesteuert

Optionale Anpassung:

```bash
--google-gemini-flash-voice-name Charon
--google-gemini-flash-prompt "Lies ruhig und natuerlich wie ein Hoerbuchsprecher."
```

Google begrenzt bei Gemini TTS Text und Prompt jeweils auf `4000` Byte. Der
Backendpfad prueft dieses Limit und meldet eine klare Fehlermeldung, statt
Text unbemerkt abzuschneiden.

Rueckkehr zum bisherigen produktiven Pfad:

```bash
--page-tts-backend google
```

Oder `--page-tts-backend` weglassen.

### Offline-Ingest eines vorhandenen OCR-Reports

```bash
cd ~/src/abr
source .venv/bin/activate
python hardware/page_ingest_debug.py \
  --library-root library \
  --book-tag-id TESTBOOK \
  --report-path captures/scan_xxx/ocr_text/report.json
```

## Systemhinweise erzeugen

Tool:

- [hardware/generate_audio_message.py](hardware/generate_audio_message.py)

Beispiel:

```bash
python hardware/generate_audio_message.py \
  --ssml \
  --output-root ~/tmp_audio_export/de \
  fehler \
  '<speak>Fehler.<break time="700ms"/>Bitte erneut versuchen.</speak>'
```

Empfehlung:

- auf dem Raspi fuer neu erzeugte Warnhinweise `--output-root` ausserhalb des
  Repo-Pfads verwenden
- danach auf den Mac kopieren und dort erst in den passenden Sprachordner
  `system_audio/messages/de/` oder `system_audio/messages/en/` verschieben

## Wichtige Doku

- [docs/CHAT_HANDOVER.md](docs/CHAT_HANDOVER.md)
- [docs/LANGUAGE_PROFILES.md](docs/LANGUAGE_PROFILES.md)
- [docs/CONTROL_RUNTIME_ARCHITECTURE.md](docs/CONTROL_RUNTIME_ARCHITECTURE.md)
- [docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md](docs/BOOK_RUNTIME_DATA_ARCHITECTURE.md)
- [docs/SOFTWARE_STRUCTURE.md](docs/SOFTWARE_STRUCTURE.md)
- [docs/WIFI_PROFILES.md](docs/WIFI_PROFILES.md)
- [docs/REMOTE_MAINTENANCE_EMAIL.md](docs/REMOTE_MAINTENANCE_EMAIL.md)
- [hardware/README.md](hardware/README.md)
