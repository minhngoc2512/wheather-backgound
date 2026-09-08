#!/usr/bin/env bash
# Build weather-background into a .deb (Architecture: all).
# Usage:  ./packaging/build-deb.sh  [version]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.0.0}"
PKG="weather-background"
BUILD="$ROOT/build/${PKG}_${VERSION}"

# astral 3.2 is vendored because Ubuntu 22.04 ships python3-astral 1.6.1,
# which has a completely different API (no Observer).
ASTRAL_SRC="${ASTRAL_SRC:-$(ls -d "$ROOT"/.venv/lib/python3.*/site-packages/astral 2>/dev/null | head -1)}"
if [ -z "$ASTRAL_SRC" ] || [ ! -d "$ASTRAL_SRC" ]; then
    echo "No astral to vendor. Run ./install.sh first, or set ASTRAL_SRC=..." >&2
    exit 1
fi
ASTRAL_VER="$("$ROOT/.venv/bin/python" -c 'import astral;print(astral.__version__)' 2>/dev/null || echo 3.2)"

rm -rf "$BUILD"
mkdir -p "$BUILD"/DEBIAN \
         "$BUILD"/usr/bin \
         "$BUILD"/usr/lib/"$PKG" \
         "$BUILD"/usr/lib/systemd/user \
         "$BUILD"/usr/share/"$PKG"/wallpapers \
         "$BUILD"/usr/share/doc/"$PKG" \
         "$BUILD"/etc/xdg/"$PKG"

# ---- payload ------------------------------------------------------------
install -m 0644 "$ROOT/wallpaper.py" "$BUILD/usr/lib/$PKG/wallpaper.py"
install -m 0644 "$ROOT/catalog.py"   "$BUILD/usr/lib/$PKG/catalog.py"
install -m 0644 "$ROOT/settings.py"  "$BUILD/usr/lib/$PKG/settings.py"
mkdir -p "$BUILD/usr/lib/$PKG/_vendor"
cp -r "$ASTRAL_SRC" "$BUILD/usr/lib/$PKG/_vendor/astral"
find "$BUILD/usr/lib/$PKG/_vendor" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$BUILD/usr/lib/$PKG/_vendor" -type f -exec chmod 0644 {} +
find "$BUILD/usr/lib/$PKG/_vendor" -type d -exec chmod 0755 {} +

cat > "$BUILD/usr/bin/weather-wallpaper" <<'EOF'
#!/bin/sh
# Mot so session X11 khong import DISPLAY vao systemd --user; dat mac dinh.
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
    DISPLAY=:0
    export DISPLAY
fi
exec python3 /usr/lib/weather-background/wallpaper.py "$@"
EOF
chmod 0755 "$BUILD/usr/bin/weather-wallpaper"

cat > "$BUILD/usr/bin/weather-background-settings" <<'EOF'
#!/bin/sh
exec python3 /usr/lib/weather-background/settings.py "$@"
EOF
chmod 0755 "$BUILD/usr/bin/weather-background-settings"

mkdir -p "$BUILD/usr/share/applications"
cat > "$BUILD/usr/share/applications/weather-background-settings.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Weather Background
Comment=Pick wallpapers and configure the dynamic background
Exec=weather-background-settings
Icon=preferences-desktop-wallpaper
Terminal=false
Categories=Settings;DesktopSettings;
Keywords=wallpaper;background;weather;
EOF

# Default wallpapers. PNG -> JPEG q92 4:4:4 for the package: the dithered PNGs
# reach 3MB each, while JPEG q92 is nearly 5x smaller with no visible loss.
# Keep 4:4:4 - chroma subsampling smears the sky gradients.
# wallpapers/ is not in git (it is reproducible from code), so regenerate it
# when missing. This block used to skip silently -> a package with no wallpapers.
if ! ls "$ROOT"/wallpapers/*.png >/dev/null 2>&1; then
    echo "==> No wallpapers yet, regenerating"
    "$ROOT/.venv/bin/python" "$ROOT/wallpaper.py" --generate-bases -c "$ROOT/config.toml" >/dev/null
fi

if ls "$ROOT"/wallpapers/*.png >/dev/null 2>&1; then
    "$ROOT/.venv/bin/python" - "$ROOT/wallpapers" "$BUILD/usr/share/$PKG/wallpapers" <<'PY'
import sys
from pathlib import Path
from PIL import Image
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
for f in sorted(src.glob("*.png")):
    Image.open(f).convert("RGB").save(
        dst / f"{f.stem}.jpg", "JPEG", quality=92, subsampling=0, optimize=True
    )
PY
fi

# SolarShift set (4 seasons x 8 times of day) if it has been fetched.
SS_SRC="${SS_SRC:-$ROOT/build/solarshift-src}"
if [ -d "$SS_SRC/spring" ]; then
    echo "==> Converting SolarShift images to JPEG"
    "$ROOT/.venv/bin/python" "$ROOT/packaging/prepare-solarshift.py" \
        "$SS_SRC" "$BUILD/usr/share/$PKG/wallpapers"
    SS_INCLUDED=1
else
    echo "==> $SS_SRC not found, skipping seasonal images"
    echo "    (fetch them with ./packaging/fetch-solarshift.sh)"
    SS_INCLUDED=0
fi

# ---- system config (conffile) ------------------------------------------
cat > "$BUILD/etc/xdg/$PKG/config.toml" <<'EOF'
# System-wide config for weather-background.
# Per-user override: ~/.config/weather-background/config.toml

[location]
# Default: Hanoi
latitude  = 21.0278
longitude = 105.8342

[display]
# Leave unset to auto-detect, in this order:
#   ~/.local/share/weather-background/wallpapers
#   /usr/share/weather-background/wallpapers   (the set shipped with the package)
# wallpapers = "~/.local/share/weather-background/wallpapers"

# auto | gnome | kde | swaybg | feh | none
setter = "auto"

# auto | off | spring | summer | autumn | winter
# auto = derived from the month and hemisphere (using latitude above).
# off  = ignore season folders, use images in the root folder.
season = "auto"

# Screen resolution. Leave unset to keep the source image size.
resolution = "2560x1440"

[weather]
# false = ignore weather, follow the sun only
enabled = true
EOF

# ---- systemd user units -------------------------------------------------
cat > "$BUILD/usr/lib/systemd/user/weather-wallpaper.service" <<'EOF'
[Unit]
Description=Update wallpaper from sun position and weather
After=graphical-session.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/weather-wallpaper
EOF

cat > "$BUILD/usr/lib/systemd/user/weather-wallpaper.timer" <<'EOF'
[Unit]
Description=Run weather-wallpaper every 15 minutes

[Timer]
OnStartupSec=30s
OnUnitActiveSec=15min
# Catch up if the machine just resumed from suspend
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

# ---- documentation ------------------------------------------------------
install -m 0644 "$ROOT/README.md" "$BUILD/usr/share/doc/$PKG/README.md"

cat > "$BUILD/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: weather-background

Files: *
Copyright: $(date +%Y) Nguyen Minh Ngoc <ngocnm95.backend@cdtgames.com>
License: MIT

Files: usr/share/weather-background/wallpapers/spring/*
 usr/share/weather-background/wallpapers/summer/*
 usr/share/weather-background/wallpapers/autumn/*
 usr/share/weather-background/wallpapers/winter/*
Copyright: 2026 Samuel Lison
License: MIT
Comment: SolarShift wallpapers, https://github.com/TemujinCalidius/SolarShift
 32 images (4 seasons x 8 times of day), AI-generated from the prompts in
 the upstream repo. Downscaled to 2560x1440 and encoded as JPEG q88 here.

Files: usr/lib/weather-background/_vendor/astral/*
Copyright: 2009-2022 Simon Kennedy <sffjunkie+code@gmail.com>
License: Apache-2.0
Comment: astral $ASTRAL_VER is vendored because Ubuntu 22.04 ships
 python3-astral 1.6.1, whose API is incompatible.
 Full licence text: /usr/share/common-licenses/Apache-2.0
EOF

printf '%s (%s) unstable; urgency=medium\n\n  * Initial .deb packaging.\n\n -- Nguyen Minh Ngoc <ngocnm95.backend@cdtgames.com>  %s\n' \
    "$PKG" "$VERSION" "$(date -R)" \
    | gzip -9n > "$BUILD/usr/share/doc/$PKG/changelog.Debian.gz"
chmod 0644 "$BUILD/usr/share/doc/$PKG/changelog.Debian.gz"

# ---- metadata -----------------------------------------------------------
INSTALLED_KB="$(du -sk "$BUILD" | cut -f1)"

cat > "$BUILD/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: x11
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-pil, python3-tomli | python3 (>= 3.11),
 python3-gi, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0
Recommends: libglib2.0-bin
Suggests: feh, swaybg
Installed-Size: $INSTALLED_KB
Maintainer: Nguyen Minh Ngoc <ngocnm95.backend@cdtgames.com>
Description: Dynamic wallpaper driven by sun position and real weather
 Picks a wallpaper from the real solar elevation at your coordinates across
 eight times of day, then layers weather effects fetched from Open-Meteo on
 top of it with Pillow at run time.
 .
 Supports GNOME, KDE Plasma, sway and feh. Runs on a systemd user timer,
 every 15 minutes by default.
 .
 Ships a GTK settings window (weather-background-settings) for coordinates,
 resolution, seasonal sets, and browsing photos from Wikimedia Commons.
 .
 Includes 32 SolarShift wallpapers (4 seasons x 8 times of day) plus a
 procedurally generated set of 8 used when seasonal mode is off.
EOF

echo "/etc/xdg/$PKG/config.toml" > "$BUILD/DEBIAN/conffiles"

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && [ -n "${2:-}" ]; then
    # Nang cap: unit file da doi tren dia nhung systemd --user van giu ban cu
    # trong bo nho. Khong the reload ho tu postinst (chay bang root, con unit
    # thi thuoc tung phien user), nen phai nhac.
    cat <<'MSG'

weather-background upgraded. If the timer is already enabled, refresh systemd:
    systemctl --user daemon-reload

MSG
    exit 0
fi
if [ "$1" = configure ]; then
    cat <<'MSG'

weather-background is installed.

Enable it for the current user (do NOT run this with sudo):
    systemctl --user daemon-reload
    systemctl --user enable --now weather-wallpaper.timer

Try it right away:
    weather-wallpaper --dry-run

Pick wallpapers and change settings:
    weather-background-settings
(or look for "Weather Background" in your application list)

System config:    /etc/xdg/weather-background/config.toml
Per-user config:  ~/.config/weather-background/config.toml
Your own images:  ~/.local/share/weather-background/wallpapers/

MSG
fi
exit 0
EOF
chmod 0755 "$BUILD/DEBIAN/postinst"

cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = purge ]; then
    rm -rf /etc/xdg/weather-background
fi
exit 0
EOF
chmod 0755 "$BUILD/DEBIAN/postrm"

# Normalise permissions: dirs 0755, files 0644, except executable scripts.
find "$BUILD" -path "$BUILD/DEBIAN" -prune -o -type d -exec chmod 0755 {} +
find "$BUILD" -path "$BUILD/DEBIAN" -prune -o -type f -exec chmod 0644 {} +
chmod 0755 "$BUILD"/usr/bin/*

# ---- build --------------------------------------------------------------
DEB="$ROOT/build/${PKG}_${VERSION}_all.deb"
fakeroot dpkg-deb --build --root-owner-group "$BUILD" "$DEB" >/dev/null
echo "$DEB"
