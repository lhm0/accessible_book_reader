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

command -v nmcli >/dev/null
"$python" -m abr.wifi_profiles configure

cat > "$target" <<EOF
[Unit]
Description=ABR persistent Wi-Fi recovery
Wants=NetworkManager.service
After=NetworkManager.service

[Service]
Type=simple
User=root
WorkingDirectory=$repo_dir
Environment=PYTHONUNBUFFERED=1
ExecStart="$python" -m abr.wifi_profiles watch
Restart=always
RestartSec=10
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable abr-wifi-autoconnect.service
systemctl restart abr-wifi-autoconnect.service
echo "Dauerhafte WLAN-Suche aktiviert (abr-wifi-autoconnect.service)."
