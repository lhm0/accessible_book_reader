#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
abr_user=${SUDO_USER:-$(id -un)}
abr_home=$(getent passwd "$abr_user" | cut -d: -f6)
python="$repo_dir/.venv/bin/python"
config_dir="$abr_home/.config/abr"
config="$config_dir/device.json"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo deploy/install_language_switch.sh" >&2
    exit 1
fi
if [ ! -x "$python" ]; then
    echo "Python der Projekt-venv fehlt: $python" >&2
    exit 1
fi

install -d -m 700 -o "$abr_user" -g "$abr_user" "$config_dir"
runuser -u "$abr_user" -- "$python" -m abr.language_config --config "$config" init

wrapper=/usr/local/bin/abr-language
{
    echo '#!/bin/sh'
    echo 'set -eu'
    printf 'abr_user=%s\n' "$abr_user"
    printf 'python=%s\n' "$python"
    printf 'config=%s\n' "$config"
    cat <<'EOF'
if [ "$#" -ne 1 ]; then
    echo "Verwendung: abr-language de|en|status" >&2
    exit 2
fi
case "$1" in
    status)
        "$python" -m abr.language_config --config "$config" status
        systemctl is-active abr-control-panel.service
        ;;
    de|en)
        if [ "$(id -u)" -ne 0 ]; then
            echo "Sprachwechsel erfordert sudo: sudo abr-language $1" >&2
            exit 1
        fi
        runuser -u "$abr_user" -- "$python" -m abr.language_config --config "$config" set "$1"
        systemctl restart abr-control-panel.service
        systemctl is-active abr-control-panel.service
        ;;
    *)
        echo "Nicht unterstuetzte Buchsprache: $1; erlaubt: de, en." >&2
        exit 2
        ;;
esac
EOF
} > "$wrapper"
chmod 755 "$wrapper"

echo "Installiert: $wrapper"
echo "Aktueller Stand: abr-language status"
