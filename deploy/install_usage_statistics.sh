#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
abr_user=${SUDO_USER:-$(id -un)}
abr_home=$(getent passwd "$abr_user" | cut -d: -f6)
python="$repo_dir/.venv/bin/python"
config="$abr_home/.config/abr/mail.ini"
library="$repo_dir/library"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo deploy/install_usage_statistics.sh" >&2
    exit 1
fi
if [ ! -x "$python" ]; then
    echo "Python der Projekt-venv fehlt: $python" >&2
    exit 1
fi
if [ ! -f "$config" ]; then
    echo "Mail-Konfiguration fehlt: $config" >&2
    echo "Bitte zuerst die bestehende ABR-E-Mail-Funktion installieren/konfigurieren." >&2
    exit 2
fi

sed \
    -e "s|__ABR_USER__|$abr_user|g" \
    -e "s|__ABR_REPO__|$repo_dir|g" \
    -e "s|__ABR_PYTHON__|$python|g" \
    -e "s|__ABR_CONFIG__|$config|g" \
    -e "s|__ABR_LIBRARY__|$library|g" \
    "$repo_dir/deploy/abr-usage-report.service" > /etc/systemd/system/abr-usage-report.service
install -m 644 "$repo_dir/deploy/abr-usage-report.timer" /etc/systemd/system/abr-usage-report.timer

systemctl daemon-reload
systemctl enable --now abr-usage-report.timer
echo "Installiert. Status: systemctl status abr-usage-report.timer"

