#!/usr/bin/env bash
# Dong goi weather-background thanh .deb (Architecture: all).
# Chay:  ./packaging/build-deb.sh  [version]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.0.0}"
PKG="weather-background"
BUILD="$ROOT/build/${PKG}_${VERSION}"

# astral 3.2 duoc nhung vao goi vi python3-astral cua Ubuntu 22.04 la ban 1.6.1
# voi API hoan toan khac (khong co Observer).
ASTRAL_SRC="${ASTRAL_SRC:-$(ls -d "$ROOT"/.venv/lib/python3.*/site-packages/astral 2>/dev/null | head -1)}"
if [ -z "$ASTRAL_SRC" ] || [ ! -d "$ASTRAL_SRC" ]; then
    echo "Khong tim thay astral de nhung. Chay ./install.sh truoc, hoac dat ASTRAL_SRC=..." >&2
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

# 4 anh nen mac dinh. Chuyen PNG -> JPEG q92 4:4:4 cho goi: PNG cua anh co
# nhieu dither nen len toi 3MB/anh, JPEG q92 nho gan 5 lan ma mat thuong khong
# phan biet duoc. Giu 4:4:4 vi lay mau con chroma lam ban bau troi gradient.
# wallpapers/ khong nam trong git (tai tao duoc tu code), nen sinh lai neu thieu.
# Truoc day khoi nay im lang bo qua -> goi ra doi khong co anh nen nao.
if ! ls "$ROOT"/wallpapers/*.png >/dev/null 2>&1; then
    echo "==> Chua co anh nen, sinh lai"
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

# Bo anh SolarShift (4 mua x 8 khung gio) neu da tai ve.
SS_SRC="${SS_SRC:-$ROOT/build/solarshift-src}"
if [ -d "$SS_SRC/spring" ]; then
    echo "==> Chuyen anh SolarShift sang JPEG"
    "$ROOT/.venv/bin/python" "$ROOT/packaging/prepare-solarshift.py" \
        "$SS_SRC" "$BUILD/usr/share/$PKG/wallpapers"
    SS_INCLUDED=1
else
    echo "==> Khong thay $SS_SRC, bo qua anh theo mua"
    echo "    (tai bang ./packaging/fetch-solarshift.sh)"
    SS_INCLUDED=0
fi

# ---- config he thong (conffile) ----------------------------------------
cat > "$BUILD/etc/xdg/$PKG/config.toml" <<'EOF'
# Config he thong cho weather-background.
# Ghi de rieng cho tung user tai ~/.config/weather-background/config.toml

[location]
# Mac dinh: Ha Noi
latitude  = 21.0278
longitude = 105.8342

[display]
# Bo trong de tu dong do theo thu tu:
#   ~/.local/share/weather-background/wallpapers
#   /usr/share/weather-background/wallpapers   (bo gradient di kem goi)
# wallpapers = "~/.local/share/weather-background/wallpapers"

# auto | gnome | kde | swaybg | feh | none
setter = "auto"

# auto | off | spring | summer | autumn | winter
# auto = suy ra tu thang va ban cau (theo latitude o tren).
# off  = bo qua thu muc mua, dung anh o ngay thu muc goc.
season = "auto"

# Do phan giai man hinh. Bo trong de giu nguyen kich thuoc anh goc.
resolution = "2560x1440"

[weather]
# false = bo qua thoi tiet, chi doi anh theo mat troi
enabled = true
EOF

# ---- systemd user units -------------------------------------------------
cat > "$BUILD/usr/lib/systemd/user/weather-wallpaper.service" <<'EOF'
[Unit]
Description=Cap nhat hinh nen theo goc mat troi va thoi tiet
After=graphical-session.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/weather-wallpaper
EOF

cat > "$BUILD/usr/lib/systemd/user/weather-wallpaper.timer" <<'EOF'
[Unit]
Description=Chay weather-wallpaper moi 15 phut

[Timer]
OnStartupSec=30s
OnUnitActiveSec=15min
# Chay bu neu may vua thuc day tu suspend
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

# ---- tai lieu -----------------------------------------------------------
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
Comment: Bo anh SolarShift, https://github.com/TemujinCalidius/SolarShift
 32 anh (4 mua x 8 khung gio), do AI sinh theo prompt trong repo goc.
 Duoc thu nho ve 2560x1440 va nen JPEG q88 khi dong goi.

Files: usr/lib/weather-background/_vendor/astral/*
Copyright: 2009-2022 Simon Kennedy <sffjunkie+code@gmail.com>
License: Apache-2.0
Comment: astral $ASTRAL_VER duoc nhung vi python3-astral cua Ubuntu 22.04 la
 ban 1.6.1 voi API khong tuong thich.
 Toan van giay phep: /usr/share/common-licenses/Apache-2.0
EOF

printf '%s (%s) unstable; urgency=medium\n\n  * Dong goi .deb dau tien.\n\n -- Nguyen Minh Ngoc <ngocnm95.backend@cdtgames.com>  %s\n' \
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
Description: Hinh nen dong theo goc mat troi va thoi tiet thuc te
 Chon anh nen theo goc mat troi that tai toa do cua ban (night / dawn /
 day / dusk), roi phu hieu ung theo thoi tiet lay tu Open-Meteo bang
 Pillow luc chay. Chi can 4 anh goc thay vi 20+ anh.
 .
 Ho tro GNOME, KDE Plasma, sway va feh. Chay dinh ky qua systemd user
 timer, mac dinh 15 phut mot lan.
 .
 Kem cua so cai dat GTK (weather-background-settings) de chinh toa do,
 do phan giai va chon anh nen that tu Wikimedia Commons theo chu de.
 .
 Anh mac dinh gom 32 anh SolarShift (4 mua x 8 khung gio) cong mot bo 8 anh
 dung bang code lam du phong khi tat che do theo mua.
EOF

echo "/etc/xdg/$PKG/config.toml" > "$BUILD/DEBIAN/conffiles"

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    cat <<'MSG'

weather-background da duoc cai.

Bat cho user hien tai (KHONG chay bang sudo):
    systemctl --user daemon-reload
    systemctl --user enable --now weather-wallpaper.timer

Chay thu ngay:
    weather-wallpaper --dry-run

Chon anh nen that va chinh cau hinh:
    weather-background-settings
(hoac tim "Weather Background" trong danh sach ung dung)

Config he thong: /etc/xdg/weather-background/config.toml
Ghi de rieng:    ~/.config/weather-background/config.toml
Anh nen rieng:   ~/.local/share/weather-background/wallpapers/

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

# Chuan hoa quyen: thu muc 0755, file 0644, tru cac script thuc thi.
find "$BUILD" -path "$BUILD/DEBIAN" -prune -o -type d -exec chmod 0755 {} +
find "$BUILD" -path "$BUILD/DEBIAN" -prune -o -type f -exec chmod 0644 {} +
chmod 0755 "$BUILD"/usr/bin/*

# ---- build --------------------------------------------------------------
DEB="$ROOT/build/${PKG}_${VERSION}_all.deb"
fakeroot dpkg-deb --build --root-owner-group "$BUILD" "$DEB" >/dev/null
echo "$DEB"
