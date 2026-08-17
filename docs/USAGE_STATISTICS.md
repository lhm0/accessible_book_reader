# Nutzerstatistik

Stand: `2026-08-07`

## Zweck und Zeitraum

Die Geraeteruntime erfasst die Nutzung buchweise. Ein Statistiktag beginnt in
der Zeitzone `Europe/Berlin` um `04:00` Uhr und endet am Folgetag unmittelbar
vor `04:00` Uhr.

Pro Buch werden erfasst:

- Anzahl erfolgreich ingestierter Seiten
- tatsaechliche Dauer der Wiedergabe von Seiten- und Zusammenfassungsaudio
- Anzahl Nutzungen der Kapitel-/Letzte-Seiten-Zusammenfassung
- Anzahl Nutzungen von `Was bisher geschah`

Systemhinweise und Signalklaenge wie `bing.wav` zaehlen nicht zur Vorlesezeit.
Ein wegen des inkrementellen Ablaufs mehrfach gemeldetes Seitenartefakt wird
ueber `scan_id` und `page_id` innerhalb derselben Statistikperiode nur einmal
gezaehlt. Ein neuer Scan derselben Buchseite zaehlt dagegen erneut.

## Speicherung und Ausfallsicherheit

Der laufende Zustand liegt unter:

```text
library/usage_statistics/current.json
```

Zugriffe aus Audio- und Ingest-Threads sowie aus dem Report-Prozess sind per
Thread-Lock und Dateisperre serialisiert. Die JSON-Datei wird atomar ersetzt.
Ein Fehler der Statistik wird geloggt, unterbricht aber nicht die eigentliche
Geraetefunktion.

Um `04:00` startet `abr-usage-report.timer` den einmaligen Dienst
`abr-usage-report.service`. Dieser sendet alle abgeschlossenen, noch nicht
versandten Perioden an den in `mail.ini` konfigurierten Empfaenger. Erst nach erfolgreichem SMTP-
Versand wird eine Periode aus `current.json` entfernt und abgelegt unter:

```text
library/usage_statistics/archive/YYYY-MM-DD.json
```

Seit dem Stand vom `2026-08-07` wird fuer jede abgeschlossene Periode ein
Bericht versendet, auch wenn das Geraet gar nicht benutzt wurde. Ein solcher
Bericht enthaelt `Keine Nutzung erfasst.` und Gesamtwerte von null. Auch leere
Perioden erhalten nach erfolgreichem Versand eine Archivdatei. Dadurch wird
derselbe Nullbericht bei einem manuellen zweiten Dienstlauf nicht erneut
verschickt. Nach einer mehrtaegigen Abschaltung werden noch nicht archivierte
Perioden der Reihe nach nachgeholt.

Schlaegt der Versand fehl oder ist der Pi um `04:00` ausgeschaltet, bleiben
die Daten erhalten. Durch `Persistent=true` holt systemd den Lauf nach; ein
spaeterer Lauf versendet weiterhin alle noch offenen abgeschlossenen
Perioden.

## Installation auf dem Raspberry Pi

Voraussetzungen:

- das Projekt liegt wie bisher unter `~/src/abr`
- die virtuelle Umgebung `~/src/abr/.venv` existiert
- der vorhandene Mail-Account ist in `~/.config/abr/mail.ini` eingerichtet
- die aktuelle Projektversion wurde auf den Pi uebertragen

Installation:

```bash
cd ~/src/abr
timedatectl status
sudo deploy/install_usage_statistics.sh
```

Bei `Time zone` muss `Europe/Berlin` stehen. Falls nicht:

```bash
sudo timedatectl set-timezone Europe/Berlin
```

Das Skript setzt den aktuellen Benutzer, Repo-, Python-, Bibliotheks- und
Mailkonfigurationspfad in die Unit ein, installiert beide systemd-Dateien und
aktiviert den Timer sofort.

Danach den Control-Panel-Dienst neu starten, damit die Runtime die neuen
Zaehler verwendet:

```bash
sudo systemctl restart abr-control-panel.service
```

Timer kontrollieren:

```bash
systemctl status abr-usage-report.timer
systemctl list-timers abr-usage-report.timer
```

## Manueller Test

Sobald erste Nutzungsdaten erfasst wurden, kann sofort eine Vorschau-Mail
gesendet werden. Sie veraendert oder archiviert die laufenden Zaehler nicht:

```bash
cd ~/src/abr
.venv/bin/python -m abr.usage_report \
  --library-root library \
  --config ~/.config/abr/mail.ini \
  --preview-current
```

Die regulaere Ausfuehrung versendet abgeschlossene Perioden einschliesslich
Perioden ohne Nutzung. Der systemd-Dienst kann nach dem naechsten
Periodenwechsel manuell gestartet werden:

```bash
sudo systemctl start abr-usage-report.service
journalctl -u abr-usage-report.service -n 100 --no-pager
```

Alternativ laesst sich derselbe regulaere Lauf direkt ausfuehren:

```bash
.venv/bin/python -m abr.usage_report \
  --library-root library \
  --config ~/.config/abr/mail.ini
```

Statistikdatei ansehen:

```bash
python -m json.tool library/usage_statistics/current.json
```

Bei einem erfolgreichen Versand erscheint im Journal die gesendete
Periodenkennung und der Archivpfad. Bei einem SMTP-Fehler endet der Dienst mit
Fehlerstatus; die Periode bleibt fuer den naechsten Versuch erhalten.
