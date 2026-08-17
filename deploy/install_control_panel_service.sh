#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
abr_user=${SUDO_USER:-$(id -un)}
abr_group=$(id -gn "$abr_user")
abr_home=$(getent passwd "$abr_user" | cut -d: -f6)
venv_bin="$repo_dir/.venv/bin"
python="$venv_bin/python"
target=/etc/systemd/system/abr-control-panel.service

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo deploy/install_control_panel_service.sh" >&2
    exit 1
fi
if [ ! -x "$python" ]; then
    echo "Python der Projekt-venv fehlt: $python" >&2
    exit 1
fi

sed \
    -e "s|__ABR_USER__|$abr_user|g" \
    -e "s|__ABR_GROUP__|$abr_group|g" \
    -e "s|__ABR_HOME__|$abr_home|g" \
    -e "s|__ABR_REPO__|$repo_dir|g" \
    -e "s|__ABR_VENV_BIN__|$venv_bin|g" \
    -e "s|__ABR_PYTHON__|$python|g" \
    "$repo_dir/deploy/abr-control-panel.service" > "$target"

chmod 644 "$target"
systemctl daemon-reload
systemctl enable --now abr-control-panel.service
echo "Installiert. Status: systemctl status abr-control-panel.service"
