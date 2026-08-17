# systemd-Dienst fuer das ABR-Control-Panel

Stand: `2026-08-01`

## Zweck

`abr-control-panel.service` startet die produktive ABR-Runtime unabhaengig
von einer SSH-Sitzung. Ein Abbruch der WLAN- oder SSH-Verbindung beendet den
Reader damit nicht mehr. systemd startet den Prozess nach einem unerwarteten
Ende automatisch neu und schreibt Standardausgabe sowie Fehler dauerhaft ins
Journal.

Benutzer-, Home-, Repository- und Pythonpfad werden bei der Installation aus
der lokalen Umgebung ermittelt und nicht im Repository fest vorgegeben. Die
installierte Unit liegt unter `/etc/systemd/system/abr-control-panel.service`.

## Unit installieren

Vor der Installation darf keine manuell gestartete zweite Instanz laufen:

```bash
pgrep -af control_panel_service.py
```

Eine vorhandene Vordergrundinstanz im zugehoerigen Terminal mit `Ctrl+C`
beenden. Anschliessend die Unit aus der Repository-Vorlage installieren:

```bash
cd ~/src/abr
sudo deploy/install_control_panel_service.sh
```

Der Installer setzt die Platzhalter in `deploy/abr-control-panel.service` und
schreibt erst die fertige Unit nach `/etc/systemd/system/`. `HOME` ist darin
explizit gesetzt, damit Google-Cloud-Anmeldedaten des Benutzers
gefunden werden. `KillSignal=SIGINT` verwendet beim Stoppen den vorhandenen
geordneten `KeyboardInterrupt`-Pfad der Runtime.

Unit pruefen, laden, beim Boot aktivieren und sofort starten:

```bash
sudo systemd-analyze verify /etc/systemd/system/abr-control-panel.service
systemctl status abr-control-panel.service --no-pager -l
```

## Betrieb und Logs

```bash
sudo systemctl start abr-control-panel.service
sudo systemctl stop abr-control-panel.service
sudo systemctl restart abr-control-panel.service
systemctl is-active abr-control-panel.service
```

Live-Log und letzte Meldungen:

```bash
journalctl -u abr-control-panel.service -f
journalctl -u abr-control-panel.service -n 100 --no-pager
journalctl -u abr-control-panel.service --since today --no-pager
```

Neustartzaehler und aktueller Hauptprozess:

```bash
systemctl show abr-control-panel.service -p MainPID -p NRestarts -p ExecMainCode -p ExecMainStatus
```

Nach einer Aenderung an der Unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart abr-control-panel.service
```

Nach einer reinen Code-Aktualisierung genuegt:

```bash
sudo systemctl restart abr-control-panel.service
```

## Funktion pruefen

Nach dem Start SSH bewusst trennen, neu verbinden und kontrollieren:

```bash
systemctl is-active abr-control-panel.service
pgrep -af control_panel_service.py
```

Ein automatischer Neustart kann gezielt getestet werden:

```bash
sudo systemctl kill --signal=SIGKILL abr-control-panel.service
sleep 6
systemctl status abr-control-panel.service --no-pager
systemctl show abr-control-panel.service -p NRestarts
```

Ein `systemctl stop` gilt dagegen als gewollter Stopp und loest trotz
`Restart=always` keinen Neustart aus.

## Diagnose

Wenn der Dienst nicht startet:

```bash
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 200 --no-pager
```

Typische Ursachen:

- `.venv/bin/python` fehlt oder ist nicht ausfuehrbar
- eine zweite manuelle Instanz belegt GPIO, Kamera, NFC oder Audio
- Google-Cloud-Anmeldedaten sind fuer den konfigurierten Dienstbenutzer nicht erreichbar
- Hardwaregeraete oder Benutzergruppen unterscheiden sich vom manuellen Lauf
- nach einer Unit-Aenderung wurde `systemctl daemon-reload` vergessen

Der zuvor beobachtete Ausfall war kein Pi-Neustart: Eine kurze
WLAN-Unterbrechung liess die SSH-Sitzung auslaufen. Die im Vordergrund dieser
Sitzung gestartete Runtime wurde beim Entfernen des Session-Scopes beendet.
Der systemd-Dienst beseitigt genau diese Kopplung.
