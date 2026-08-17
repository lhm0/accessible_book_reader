#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
abr_user=${SUDO_USER:-$(id -un)}
abr_home=$(getent passwd "$abr_user" | cut -d: -f6)
python="$repo_dir/.venv/bin/python"
config_dir="$abr_home/.config/abr"
config="$config_dir/mail.ini"

if [ ! -x "$python" ]; then
    echo "Python der Projekt-venv fehlt: $python" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo deploy/install_remote_mail.sh" >&2
    exit 1
fi

install -d -m 700 -o "$abr_user" -g "$abr_user" "$config_dir"
if [ ! -e "$config" ]; then
    install -m 600 -o "$abr_user" -g "$abr_user" "$repo_dir/deploy/mail.ini.example" "$config"
    echo "Konfiguration angelegt: $config"
    echo "Bitte zuerst ausfuellen und das Installationsskript erneut starten."
    exit 2
fi

wrapper=/usr/local/bin/email_download
{
    echo '#!/bin/sh'
    printf 'exec %s -m abr.remote_mail_download --config %s "$@"\n' "$python" "$config"
} > "$wrapper"
chmod 755 "$wrapper"

sed \
    -e "s|__ABR_USER__|$abr_user|g" \
    -e "s|__ABR_REPO__|$repo_dir|g" \
    -e "s|__ABR_PYTHON__|$python|g" \
    -e "s|__ABR_CONFIG__|$config|g" \
    -e "s|__ABR_HOME__|$abr_home|g" \
    "$repo_dir/deploy/abr-email-upload.service" > /etc/systemd/system/abr-email-upload.service
install -m 644 "$repo_dir/deploy/abr-email-upload.timer" /etc/systemd/system/abr-email-upload.timer

systemctl daemon-reload
systemctl enable --now abr-email-upload.timer
echo "Installiert. Status: systemctl status abr-email-upload.timer"
