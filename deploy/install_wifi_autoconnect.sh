#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
abr_user=${SUDO_USER:-$(id -un)}
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

sed \
    -e "s|__ABR_USER__|$abr_user|g" \
    -e "s|__ABR_REPO__|$repo_dir|g" \
    -e "s|__ABR_PYTHON__|$python|g" \
    "$repo_dir/deploy/abr-wifi-autoconnect.service" > "$target"

chmod 644 "$target"
systemctl daemon-reload
systemctl enable --now abr-wifi-autoconnect.service
echo "Installiert. Status: systemctl status abr-wifi-autoconnect.service"
