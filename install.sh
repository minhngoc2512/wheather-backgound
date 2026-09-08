#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$HOME/.config/systemd/user"

echo "==> Looking for python >= 3.11 (needs tomllib)"
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PY="$(command -v "$cand")"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "No python >= 3.11 found. Run: sudo apt install python3.12 python3.12-venv"
    exit 1
fi
echo "    using $PY ($("$PY" -V))"

echo "==> Checking venv"
if ! "$PY" -c "import venv" 2>/dev/null; then
    echo "Missing the venv module. Run: sudo apt install $(basename "$PY")-venv"
    exit 1
fi

echo "==> Creating virtualenv at $ROOT/.venv"
"$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet astral Pillow

chmod +x "$ROOT/wallpaper.py"

if ! ls "$ROOT"/wallpapers/day.{jpg,jpeg,png,webp} >/dev/null 2>&1; then
    echo "==> No wallpapers yet, generating the default set"
    "$ROOT/.venv/bin/python" "$ROOT/wallpaper.py" --generate-bases
fi

echo "==> Test run"
"$ROOT/.venv/bin/python" "$ROOT/wallpaper.py" --dry-run

echo "==> Installing systemd user units"
mkdir -p "$UNITS"
sed "s|%h/Projects/weather_background|$ROOT|g" \
    "$ROOT/weather-wallpaper.service" > "$UNITS/weather-wallpaper.service"
cp "$ROOT/weather-wallpaper.timer" "$UNITS/weather-wallpaper.timer"

systemctl --user daemon-reload
systemctl --user enable --now weather-wallpaper.timer

echo
echo "Done. Check with:"
echo "  systemctl --user list-timers weather-wallpaper.timer"
echo "  journalctl --user -u weather-wallpaper.service -n 20"
