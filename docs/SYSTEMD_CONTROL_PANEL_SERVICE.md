# systemd Service for the ABR Control Panel

Last reviewed: `2026-08-01`

Deutsche Fassung: [systemd-Dienst für das ABR-Control-Panel](../docs_DE/SYSTEMD_CONTROL_PANEL_SERVICE.md)

## Purpose

`abr-control-panel.service` runs the production ABR runtime independently of
an SSH session. Losing Wi-Fi or SSH therefore no longer stops the reader.
systemd automatically restarts the process after an unexpected exit and
stores standard output and errors in the journal.

The installer derives the user, home directory, repository, and Python paths
from the local environment instead of hard-coding them in the repository. The
installed unit is written to
`/etc/systemd/system/abr-control-panel.service`.

## Installing the Unit

Before installation, make sure no manually started second instance is
running:

```bash
pgrep -af control_panel_service.py
```

Stop an existing foreground instance with `Ctrl+C` in its terminal. Then
install the unit from the repository template:

```bash
cd ~/src/abr
sudo deploy/install_control_panel_service.sh
```

The installer substitutes placeholders in
`deploy/abr-control-panel.service` and writes only the completed unit to
`/etc/systemd/system/`. It explicitly sets `HOME` so the user's Google Cloud
credentials can be found. `KillSignal=SIGINT` uses the runtime's existing
orderly `KeyboardInterrupt` shutdown path.

Verify the unit and inspect its status after the installer has loaded,
enabled, and started it:

```bash
sudo systemd-analyze verify /etc/systemd/system/abr-control-panel.service
systemctl status abr-control-panel.service --no-pager -l
```

## Operation and Logs

```bash
sudo systemctl start abr-control-panel.service
sudo systemctl stop abr-control-panel.service
sudo systemctl restart abr-control-panel.service
systemctl is-active abr-control-panel.service
```

Live log and recent messages:

```bash
journalctl -u abr-control-panel.service -f
journalctl -u abr-control-panel.service -n 100 --no-pager
journalctl -u abr-control-panel.service --since today --no-pager
```

Restart counter and current main process:

```bash
systemctl show abr-control-panel.service -p MainPID -p NRestarts -p ExecMainCode -p ExecMainStatus
```

After changing the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart abr-control-panel.service
```

After a code-only update, restarting the service is sufficient:

```bash
sudo systemctl restart abr-control-panel.service
```

## Functional Verification

After starting the service, deliberately disconnect SSH, reconnect, and
verify:

```bash
systemctl is-active abr-control-panel.service
pgrep -af control_panel_service.py
```

Automatic restart can be tested deliberately:

```bash
sudo systemctl kill --signal=SIGKILL abr-control-panel.service
sleep 6
systemctl status abr-control-panel.service --no-pager
systemctl show abr-control-panel.service -p NRestarts
```

By contrast, `systemctl stop` is an intentional stop and does not trigger a
restart despite `Restart=always`.

## Diagnostics

If the service does not start:

```bash
systemctl status abr-control-panel.service --no-pager -l
journalctl -u abr-control-panel.service -n 200 --no-pager
```

Common causes:

- `.venv/bin/python` is missing or not executable
- a second manually started instance is occupying GPIO, cameras, NFC, or audio
- Google Cloud credentials are unavailable to the configured service user
- hardware-device access or group membership differs from the manual run
- `systemctl daemon-reload` was omitted after changing the unit

A previously observed outage was not a Raspberry Pi restart. A short Wi-Fi
interruption caused the SSH session to time out, and the foreground runtime
was terminated when its session scope was removed. The systemd service
eliminates this dependency.
