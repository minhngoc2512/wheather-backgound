#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$HOME/.config/systemd/user"

echo "==> Tim python >= 3.11 (can tomllib)"
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PY="$(command -v "$cand")"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Khong tim thay python >= 3.11. Chay: sudo apt install python3.12 python3.12-venv"
    exit 1
fi
echo "    dung $PY ($("$PY" -V))"

echo "==> Kiem tra venv"
if ! "$PY" -c "import venv" 2>/dev/null; then
    echo "Thieu module venv. Chay: sudo apt install $(basename "$PY")-venv"
    exit 1
fi

echo "==> Tao virtualenv tai $ROOT/.venv"
"$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet astral Pillow

chmod +x "$ROOT/wallpaper.py"

if ! ls "$ROOT"/wallpapers/day.{jpg,jpeg,png,webp} >/dev/null 2>&1; then
    echo "==> Chua co anh nen, tao gradient tam"
    "$ROOT/.venv/bin/python" "$ROOT/wallpaper.py" --generate-bases
fi

echo "==> Chay thu"
"$ROOT/.venv/bin/python" "$ROOT/wallpaper.py" --dry-run

echo "==> Cai systemd user units"
mkdir -p "$UNITS"
sed "s|%h/Projects/weather_background|$ROOT|g" \
    "$ROOT/weather-wallpaper.service" > "$UNITS/weather-wallpaper.service"
cp "$ROOT/weather-wallpaper.timer" "$UNITS/weather-wallpaper.timer"

systemctl --user daemon-reload
systemctl --user enable --now weather-wallpaper.timer

echo
echo "Xong. Kiem tra bang:"
echo "  systemctl --user list-timers weather-wallpaper.timer"
echo "  journalctl --user -u weather-wallpaper.service -n 20"
