#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python="$repo_dir/.venv/bin/python"
target=/etc/systemd/system/abr-wifi-autoconnect.service

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo deploy/install_wifi_autoconnect.sh" >&2
    exit 1
fi
if [ ! -x "$python" ]; then
    echo "Python der Projekt-venv fehlt: $python" >&2
    exit 1
fi

# Aeltere Installationen verwendeten hier eine systemd-Unit als normaler
# Benutzer. NetworkManager verweigert diesem nicht-interaktiven Prozess das
# Aendern systemweiter Profile. Die Einstellungen sind persistent, daher ist
# kein privilegierter ABR-Dienst bei jedem Boot erforderlich.
if [ -e "$target" ]; then
    systemctl disable --now abr-wifi-autoconnect.service 2>/dev/null || true
    rm -f "$target"
    systemctl daemon-reload
    systemctl reset-failed abr-wifi-autoconnect.service 2>/dev/null || true
fi

"$python" -m abr.wifi_profiles configure
echo "WLAN-Autoconnect ist in den gespeicherten NetworkManager-Profilen konfiguriert."
