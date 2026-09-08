#!/usr/bin/env python3
"""
weather_background - dynamic wallpaper theo goc mat troi + thoi tiet thuc te.

Chi can 4 anh nen goc (night / dawn / day / dusk). Hieu ung thoi tiet
duoc phu len luc chay bang Pillow, nen khong phai luu 20+ anh.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:                            # Python >= 3.11
    import tomllib
except ModuleNotFoundError:     # Ubuntu 22.04 tro xuong
    import tomli as tomllib     # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent

# Khi cai tu goi .deb, astral duoc nhung o _vendor canh script. Chay tu thu muc
# source thi khong co _vendor, dung ban trong venv / he thong.
_VENDOR = ROOT / "_vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

from astral import Observer
from astral.sun import elevation, noon
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "weather-wallpaper"
STATE = CACHE / "state.json"

# Uu tien: config rieng cua user -> config he thong -> thu muc source.
CONFIG_CANDIDATES = (
    XDG_CONFIG / "weather-background" / "config.toml",
    Path("/etc/xdg/weather-background/config.toml"),
    ROOT / "config.toml",
)

# Anh nen rieng cua user duoc uu tien hon bo gradient mac dinh cua goi.
WALLPAPER_CANDIDATES = (
    XDG_DATA / "weather-background" / "wallpapers",
    ROOT / "wallpapers",
    Path("/usr/share/weather-background/wallpapers"),
)


def find_config(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None
    for cand in CONFIG_CANDIDATES:
        if cand.exists():
            return cand
    return None


def writable_wallpapers(preferred: Path) -> Path:
    """Thu muc de --generate-bases ghi vao.

    default_wallpapers() tra ve thu muc dau tien CO SAN anh, ma sau khi cai
    goi thi do luon la /usr/share/... thuoc root. Sinh anh phai ghi duoc, nen
    lui ve thu muc XDG cua user khi cho uu tien khong ghi duoc.
    """
    probe = preferred if preferred.is_dir() else preferred.parent
    if probe.is_dir() and os.access(probe, os.W_OK):
        return preferred
    return WALLPAPER_CANDIDATES[0]


# Ten dung de do xem mot thu muc co anh nen hay khong. Gom ca "day" cua bo 4
# anh cu, vi thu muc do van dung duoc qua PHASE_ALIASES.
_PROBE_NAMES = ("midday", "day", "night", "dawn", "dusk")


def has_bases(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    if any(any(folder.glob(f"{n}.*")) for n in _PROBE_NAMES):
        return True
    # Bo anh chia theo mua thi thu muc goc rong, anh nam trong <mua>/.
    return any(
        any(any((folder / season).glob(f"{n}.*")) for n in _PROBE_NAMES)
        for season in SEASONS
        if (folder / season).is_dir()
    )


def default_wallpapers() -> Path:
    """Thu muc anh nen khi config khong chi dinh."""
    for cand in WALLPAPER_CANDIDATES:
        if has_bases(cand):
            return cand
    # Chua co gi: tro toi cho ghi duoc de --generate-bases hoat dong.
    return WALLPAPER_CANDIDATES[0]

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

@dataclass
class Config:
    latitude: float
    longitude: float
    wallpapers: Path
    setter: str          # auto | gnome | kde | swaybg | feh | none
    resolution: tuple[int, int] | None
    weather: bool
    season: str          # auto | off | spring | summer | autumn | winter


def load_config(path: Path) -> Config:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    loc = raw.get("location", {})
    disp = raw.get("display", {})

    res = disp.get("resolution")
    if isinstance(res, str) and "x" in res:
        w, h = res.lower().split("x")
        res = (int(w), int(h))
    else:
        res = None

    raw_wp = disp.get("wallpapers")
    wp = Path(raw_wp).expanduser() if raw_wp else default_wallpapers()

    return Config(
        latitude=float(loc.get("latitude", 21.0278)),
        longitude=float(loc.get("longitude", 105.8342)),
        wallpapers=wp,
        setter=disp.get("setter", "auto"),
        resolution=res,
        weather=bool(raw.get("weather", {}).get("enabled", True)),
        season=str(disp.get("season", "auto")).lower(),
    )


# --------------------------------------------------------------------------
# mat troi -> khung thoi gian
# --------------------------------------------------------------------------

# Thu tu theo dong thoi gian trong ngay, bat dau tu dem.
PHASES = ("night", "dawn", "morning", "midday", "afternoon",
          "golden_hour", "dusk", "twilight")

# Khi thieu anh cho mot khung gio, lui ve ten thay the. Nho vay bo 4 anh cu
# (night / dawn / day / dusk) van chay duoc voi 8 nac moi.
PHASE_ALIASES = {
    "night":       ("night",),
    "dawn":        ("dawn",),
    "morning":     ("morning", "day", "midday"),
    "midday":      ("midday", "day"),
    "afternoon":   ("afternoon", "day", "midday"),
    "golden_hour": ("golden_hour", "dusk"),
    "dusk":        ("dusk",),
    "twilight":    ("twilight", "night", "dusk"),
}

# Nguong goc mat troi (do). Chieu co nhieu nac hon sang vi mat troi lan dep
# hon va bo anh cung chia nho phia do (golden_hour / dusk / twilight).
#
# Nguong tren khong the co dinh: o vi do cao mua dong mat troi khong bao gio
# len toi 28 do, nen "midday" se khong bao gio xay ra. Vi vay no duoc neo theo
# do cao luc chinh ngo cua chinh ngay do.
MIDDAY_CAP = 28.0        # tran cho vung nhiet doi, noi mat troi len rat cao
MIDDAY_SHARE = 0.80      # midday bat dau tu 80% do cao chinh ngo
GOLDEN_CAP = 12.0
GOLDEN_SHARE = 0.60


def _monotonic(bands):
    """Ep nguong khong giam dan.

    Khi ngay qua ngan (mua dong vung cuc) cac nguong co the dao thu tu; kep lai
    se lam dai tuong ung rong di - dung y nghia: hom do khong co khung gio do.
    """
    out, prev = [], -90.0
    for limit, name in bands:
        if limit is None:
            out.append((None, name))
            continue
        limit = max(limit, prev)
        prev = limit
        out.append((limit, name))
    return tuple(out)


def _bands(noon_elev: float):
    top = min(MIDDAY_CAP, MIDDAY_SHARE * noon_elev)
    gold = min(GOLDEN_CAP, top * GOLDEN_SHARE)
    rising = ((-6.0, "night"), (8.0, "dawn"), (top, "morning"), (None, "midday"))
    falling = ((-9.0, "night"), (-3.0, "twilight"), (3.0, "dusk"),
               (gold, "golden_hour"), (top, "afternoon"), (None, "midday"))
    return _monotonic(rising), _monotonic(falling)

SEASONS = ("spring", "summer", "autumn", "winter")

# Thang 1..12 -> mua o bac ban cau.
_NORTH_SEASON = ("winter", "winter", "spring", "spring", "spring", "summer",
                 "summer", "summer", "autumn", "autumn", "autumn", "winter")
_FLIP = {"spring": "autumn", "summer": "winter", "autumn": "spring", "winter": "summer"}


def current_season(lat: float, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    north = _NORTH_SEASON[when.month - 1]
    return north if lat >= 0 else _FLIP[north]


def _band(elev: float, bands) -> str:
    for limit, name in bands:
        if limit is None or elev < limit:
            return name
    return bands[-1][1]


def solar_phase(lat: float, lon: float, when: datetime | None = None) -> tuple[str, float]:
    """Tra ve (phase, elevation_degrees).

    Dang len hay dang xuong duoc xac dinh bang cach so voi 10 phut truoc.
    Cach nay khong phu thuoc mui gio, khac voi viec doi chieu solar noon theo
    ngay UTC (se sai o cac mui gio lech xa nhu UTC+7).
    """
    when = when or datetime.now(timezone.utc)
    obs = Observer(latitude=lat, longitude=lon)
    elev = elevation(obs, when)
    earlier = elevation(obs, when - timedelta(minutes=10))
    try:
        noon_elev = elevation(obs, noon(obs, when.date()))
    except Exception:                      # vung cuc: astral co the khong tinh duoc
        noon_elev = MIDDAY_CAP
    rising, falling = _bands(noon_elev)
    return _band(elev, rising if elev > earlier else falling), elev


# --------------------------------------------------------------------------
# thoi tiet
# --------------------------------------------------------------------------

# WMO weather code -> nhom hieu ung
WMO_GROUPS = {
    "clear":     {0, 1},
    "cloudy":    {2},
    "overcast":  {3},
    "fog":       {45, 48},
    "rain":      {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82},
    "snow":      {71, 73, 75, 77, 85, 86},
    "storm":     {95, 96, 99},
}


def code_to_group(code: int) -> str:
    for name, codes in WMO_GROUPS.items():
        if code in codes:
            return name
    return "clear"


def fetch_weather(lat: float, lon: float, timeout: int = 10) -> str:
    url = (
        f"{OPEN_METEO}?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=weather_code&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-background/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return code_to_group(int(data["current"]["weather_code"]))


def cached_weather() -> str:
    """Dung ket qua lan truoc khi mat mang."""
    try:
        return json.loads(STATE.read_text()).get("weather", "clear")
    except Exception:
        return "clear"


# --------------------------------------------------------------------------
# hieu ung anh
# --------------------------------------------------------------------------
# saturation, brightness, contrast, (tint_rgb, tint_alpha), blur_radius

EFFECTS = {
    "clear":    (1.00, 1.00, 1.00, None, 0.0),
    "cloudy":   (0.85, 0.95, 0.95, ((150, 160, 175), 0.08), 0.0),
    "overcast": (0.60, 0.82, 0.85, ((130, 138, 150), 0.20), 0.0),
    "fog":      (0.45, 1.02, 0.72, ((214, 218, 222), 0.34), 3.5),
    "rain":     (0.55, 0.72, 0.92, ((58, 74, 96), 0.26), 0.8),
    "snow":     (0.50, 1.10, 0.80, ((228, 234, 244), 0.26), 1.2),
    "storm":    (0.40, 0.58, 1.08, ((40, 44, 70), 0.34), 0.6),
}


def apply_weather(img: Image.Image, group: str) -> Image.Image:
    sat, bright, contrast, tint, blur = EFFECTS.get(group, EFFECTS["clear"])
    out = img.convert("RGB")

    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    if sat != 1.0:
        out = ImageEnhance.Color(out).enhance(sat)
    if bright != 1.0:
        out = ImageEnhance.Brightness(out).enhance(bright)
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if tint:
        rgb, alpha = tint
        layer = Image.new("RGB", out.size, rgb)
        out = Image.blend(out, layer, alpha)

    return out


def render_key(base: Path, resolution) -> str:
    """Van tay cua dau vao render.

    Chi so phase + weather la khong du: doi anh goc (nang cap goi, hoac user bo
    anh rieng vao) hay doi resolution deu phai ve lai, nhung hai thu do khong
    lam phase/weather thay doi.
    """
    st = base.stat()
    res = f"{resolution[0]}x{resolution[1]}" if resolution else "native"
    return f"{base}|{st.st_mtime_ns}|{st.st_size}|{res}"


def find_base(folder: Path, phase: str, season: str | None = None) -> Path:
    """Tim anh goc cho mot khung gio.

    Uu tien thu muc mua (wallpapers/<mua>/<phase>.jpg) roi moi den thu muc goc,
    va trong moi thu muc thi thu lan luot cac ten thay the trong PHASE_ALIASES.
    """
    roots = [folder / season, folder] if season else [folder]
    for root in roots:
        for name in PHASE_ALIASES.get(phase, (phase,)):
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                cand = root / f"{name}{ext}"
                if cand.exists():
                    return cand
    raise FileNotFoundError(
        f"Khong tim thay anh nen '{phase}.*' trong {folder}. "
        "Chay voi --generate-bases de tao bo anh mac dinh."
    )


# --------------------------------------------------------------------------
# tao anh nen mac dinh: canh nui + bau troi theo tung khung gio
# --------------------------------------------------------------------------
# Moi khung gio mo ta bang:
#   sky   : cac diem dung mau tu dinh troi xuong duong chan troi
#   glow  : ((x, y) theo ti le anh, ban kinh theo ti le, mau, cuong do)
#   stars : so sao rai o nua tren
#   ridge : mau ray nui gan nhat (cac ray xa duoc pha dan ve mau chan troi)

SCENES = {
    "night": {
        "sky":   [(5, 8, 24), (11, 18, 48), (24, 38, 78), (44, 66, 104)],
        "glow":  ((0.76, 0.18), 0.26, (198, 216, 248), 0.55),
        "stars": 460,
        "ridge": (13, 17, 34),
    },
    "dawn": {
        "sky":   [(20, 30, 76), (78, 62, 122), (198, 110, 100), (250, 192, 134)],
        "glow":  ((0.30, 0.60), 0.34, (255, 196, 128), 0.85),
        "stars": 90,
        "ridge": (26, 21, 42),
    },
    "morning": {
        "sky":   [(22, 74, 168), (64, 124, 206), (140, 180, 226), (226, 214, 196)],
        "glow":  ((0.42, 0.38), 0.30, (255, 232, 186), 0.70),
        "stars": 0,
        "ridge": (44, 66, 100),
    },
    "midday": {
        "sky":   [(26, 90, 184), (70, 136, 218), (138, 188, 236), (210, 234, 248)],
        "glow":  ((0.58, 0.14), 0.30, (255, 246, 214), 0.60),
        "stars": 0,
        "ridge": (52, 74, 104),
    },
    "afternoon": {
        "sky":   [(30, 96, 180), (84, 142, 210), (164, 190, 220), (238, 222, 190)],
        "glow":  ((0.70, 0.32), 0.31, (255, 238, 194), 0.68),
        "stars": 0,
        "ridge": (50, 66, 92),
    },
    "golden_hour": {
        "sky":   [(36, 72, 146), (120, 116, 166), (226, 146, 92), (255, 204, 132)],
        "glow":  ((0.78, 0.55), 0.35, (255, 190, 110), 0.90),
        "stars": 0,
        "ridge": (34, 28, 46),
    },
    "dusk": {
        "sky":   [(14, 18, 54), (68, 42, 94), (172, 66, 86), (242, 142, 86)],
        "glow":  ((0.82, 0.63), 0.32, (255, 158, 92), 0.85),
        "stars": 150,
        "ridge": (19, 14, 32),
    },
    "twilight": {
        "sky":   [(8, 12, 40), (34, 32, 78), (86, 58, 110), (150, 92, 110)],
        "glow":  ((0.80, 0.70), 0.28, (206, 126, 116), 0.60),
        "stars": 300,
        "ridge": (14, 12, 28),
    },
}

HORIZON = 0.66      # duong chan troi, theo ti le chieu cao

# (day theo ti le chieu cao, bien do, do pha suong, do gap ghenh)
RIDGES = (
    (0.595, 0.130, 0.42, 0.50),
    (0.700, 0.100, 0.18, 0.63),
    (0.845, 0.070, 0.03, 0.74),
)


def _srgb_to_linear(c: float) -> float:
    return (c / 255.0) ** 2.2


def _linear_to_srgb(v: float) -> int:
    return max(0, min(255, round((v ** (1 / 2.2)) * 255)))


def _lerp_rgb(a, b, f: float):
    """Noi suy trong khong gian tuyen tinh; tron thang trong sRGB se bi xam."""
    return tuple(
        _linear_to_srgb(_srgb_to_linear(a[c]) + (_srgb_to_linear(b[c]) - _srgb_to_linear(a[c])) * f)
        for c in range(3)
    )


def make_gradient(stops, size) -> Image.Image:
    """Gradient doc, noi suy tuyen tinh, tra ve anh full size."""
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    n = len(stops) - 1
    for y in range(h):
        t = y / max(h - 1, 1) * n
        i = min(int(t), n - 1)
        px[0, y] = _lerp_rgb(stops[i], stops[i + 1], t - i)
    return strip.resize((w, h), Image.BILINEAR)


def _radial_mask(size, centre, radius, power: float = 2.2, grid: int = 320) -> Image.Image:
    """Mask tron dan deu, ve o do phan giai thap roi phong to cho nhanh + muot.

    Luoi giu dung ti le cua anh cuoi nen khoang cach tinh thang, khong bu gi
    them - bu them chinh la thu lam quang sang bi bep thanh elip.
    """
    w, h = size
    sw = grid
    sh = max(1, round(grid * h / w))
    cx, cy = centre[0] * sw, centre[1] * sh
    r = max(radius * sw, 1e-6)
    mask = Image.new("L", (sw, sh))
    px = mask.load()
    for y in range(sh):
        for x in range(sw):
            d = math.hypot(x - cx, y - cy) / r
            px[x, y] = 0 if d >= 1 else round(255 * (1 - d) ** power)
    return mask.resize((w, h), Image.BICUBIC)


def _ridge_profile(rng: random.Random, n: int, roughness: float) -> list[float]:
    """Dich chuyen trung diem 1 chieu -> duong nui tu nhien, chuan hoa ve 0..1."""
    pts = [rng.random(), rng.random()]
    scale = 1.0
    while len(pts) < n:
        nxt = []
        for i in range(len(pts) - 1):
            nxt.append(pts[i])
            nxt.append((pts[i] + pts[i + 1]) / 2 + rng.uniform(-scale, scale) * roughness)
        nxt.append(pts[-1])
        pts = nxt
        scale *= 0.5
    lo, hi = min(pts), max(pts)
    span = hi - lo or 1.0
    return [(v - lo) / span for v in pts[:n]]


def _draw_stars(img: Image.Image, count: int, rng: random.Random) -> None:
    w, h = img.size
    d = ImageDraw.Draw(img)
    limit = HORIZON * h
    for _ in range(count):
        x = rng.uniform(0, w)
        # Thua dan khi xuong gan chan troi.
        y = limit * (rng.random() ** 1.7)
        b = rng.randint(120, 255)
        fade = 1 - (y / limit) * 0.65
        c = round(b * fade)
        if c < 30:
            continue
        col = (c, c, min(255, round(c * 1.04)))
        if rng.random() < 0.06:                       # vai ngoi sao sang hon
            d.ellipse((x - 1.4, y - 1.4, x + 1.4, y + 1.4), fill=col)
        else:
            d.point((x, y), fill=col)


def make_scene(phase: str, size: tuple[int, int], seed: int = 7) -> Image.Image:
    spec = SCENES[phase]
    w, h = size
    # crc32 chu khong phai hash(): hash() cua chuoi bi ngau nhien hoa moi tien
    # trinh (PYTHONHASHSEED), nen moi lan --generate-bases se ra day nui khac.
    rng = random.Random(seed + zlib.crc32(phase.encode()) % 1000)

    img = make_gradient(spec["sky"], size)

    if spec["stars"]:
        _draw_stars(img, spec["stars"], rng)

    # Quang mat troi / mat trang.
    (gx, gy), grad, gcol, gstr = spec["glow"]
    glow = _radial_mask(size, (gx, gy), grad)
    if gstr != 1.0:
        glow = glow.point(lambda v: round(v * gstr))
    img.paste(Image.new("RGB", size, gcol), (0, 0), glow)

    # Dia mat troi / mat trang: ve that o full res roi lam mem vien, neu dung
    # mask do phan giai thap thi phong to len se nhoe thanh vet.
    disc_r = max(6.0, grad * w * 0.085)
    disc = Image.new("L", size, 0)
    ImageDraw.Draw(disc).ellipse(
        (gx * w - disc_r, gy * h - disc_r, gx * w + disc_r, gy * h + disc_r), fill=255
    )
    disc = disc.filter(ImageFilter.GaussianBlur(disc_r * 0.30))
    img.paste(Image.new("RGB", size, _lerp_rgb(gcol, (255, 255, 255), 0.45)), (0, 0), disc)

    # Dai suong sat duong chan troi.
    horizon_col = spec["sky"][-1]
    haze = Image.new("L", (1, h))
    hpx = haze.load()
    hy = HORIZON * h
    for y in range(h):
        dist = abs(y - hy) / (h * 0.13)
        hpx[0, y] = 0 if dist >= 1 else round(64 * (1 - dist) ** 2)
    img.paste(Image.new("RGB", size, horizon_col), (0, 0), haze.resize(size, Image.BILINEAR))

    # Cac ray nui, ve tu xa toi gan.
    npts = 257
    for base, amp, hazing, rough in RIDGES:
        prof = _ridge_profile(rng, npts, rough)
        top = base * h
        pts = [(i * w / (npts - 1), top - (v - 0.5) * amp * h) for i, v in enumerate(prof)]
        colour = _lerp_rgb(spec["ridge"], horizon_col, hazing)
        ImageDraw.Draw(img).polygon(pts + [(w, h), (0, h)], fill=colour)

    # Toi bon goc mot chut cho anh co chieu sau.
    vignette = _radial_mask(size, (0.5, 0.45), 0.95, power=1.1)
    img = Image.composite(img, ImageChops.multiply(img, Image.new("RGB", size, (150, 150, 160))), vignette)

    # Nhieu rat nhe: pha vo banding cua gradient 8-bit tren man hinh lon.
    noise = Image.effect_noise(size, 7).convert("RGB")
    img = Image.blend(img, ImageChops.add(img, noise, scale=1.0, offset=-128), 0.34)

    return img


def generate_bases(folder: Path, size: tuple[int, int]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for phase in PHASES:
        out = folder / f"{phase}.png"
        make_scene(phase, size).save(out)
        print(f"  tao {out}")


# --------------------------------------------------------------------------
# dat hinh nen
# --------------------------------------------------------------------------

def detect_setter() -> str:
    de = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    if "gnome" in de or "unity" in de or "cinnamon" in de:
        return "gnome"
    if "kde" in de or "plasma" in de:
        return "kde"
    if os.environ.get("SWAYSOCK") or "sway" in de:
        return "swaybg"
    if shutil.which("gsettings"):
        return "gnome"
    if shutil.which("feh"):
        return "feh"
    return "none"


def set_wallpaper(path: Path, setter: str) -> None:
    if setter == "auto":
        setter = detect_setter()

    uri = path.resolve().as_uri()

    if setter == "gnome":
        for key in ("picture-uri", "picture-uri-dark"):
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.background", key, uri],
                check=False,
            )
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.background", "picture-options", "zoom"],
            check=False,
        )

    elif setter == "kde":
        script = (
            "var ds = desktops();"
            "for (i = 0; i < ds.length; i++) {"
            "  ds[i].wallpaperPlugin = 'org.kde.image';"
            "  ds[i].currentConfigGroup = ['Wallpaper','org.kde.image','General'];"
            f"  ds[i].writeConfig('Image', '{uri}');"
            "}"
        )
        tool = shutil.which("qdbus6") or shutil.which("qdbus")
        if tool:
            subprocess.run(
                [tool, "org.kde.plasmashell", "/PlasmaShell",
                 "org.kde.PlasmaShell.evaluateScript", script],
                check=False,
            )

    elif setter == "swaybg":
        subprocess.run(["pkill", "-x", "swaybg"], check=False)
        subprocess.Popen(
            ["swaybg", "-i", str(path), "-m", "fill"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    elif setter == "feh":
        subprocess.run(["feh", "--bg-fill", str(path)], check=False)

    elif setter == "none":
        print(f"Khong co setter phu hop. Anh da tao tai: {path}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Dynamic wallpaper theo mat troi + thoi tiet")
    ap.add_argument("-c", "--config", help="duong dan config.toml (mac dinh: tu dong do)")
    ap.add_argument("--weather", help="ep buoc nhom thoi tiet (clear/cloudy/overcast/fog/rain/snow/storm)")
    ap.add_argument("--phase", choices=PHASES, help="ep buoc khung thoi gian")
    ap.add_argument("--season", choices=(*SEASONS, "off"), help="ep buoc mua")
    ap.add_argument("--offline", action="store_true", help="khong goi API, dung cache")
    ap.add_argument("--dry-run", action="store_true", help="tinh toan va tao anh nhung khong doi hinh nen")
    ap.add_argument("--generate-bases", action="store_true", help="tao 4 anh gradient mac dinh roi thoat")
    args = ap.parse_args()

    cfg_path = find_config(args.config)
    if cfg_path is None:
        looked = args.config or "\n  ".join(str(c) for c in CONFIG_CANDIDATES)
        print(f"Khong thay config. Da tim tai:\n  {looked}", file=sys.stderr)
        return 1
    cfg = load_config(cfg_path)

    size = cfg.resolution or (2560, 1440)

    if args.generate_bases:
        target = writable_wallpapers(cfg.wallpapers)
        if target != cfg.wallpapers:
            print(f"{cfg.wallpapers} khong ghi duoc, dung {target} thay the.")
        print(f"Tao anh nen {size[0]}x{size[1]} trong {target}:")
        generate_bases(target, size)
        return 0

    CACHE.mkdir(parents=True, exist_ok=True)

    phase, elev = (args.phase, float("nan")) if args.phase else solar_phase(
        cfg.latitude, cfg.longitude
    )

    if args.weather:
        group = args.weather
    elif not cfg.weather or args.offline:
        group = cached_weather()
    else:
        try:
            group = fetch_weather(cfg.latitude, cfg.longitude)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            print(f"Khong lay duoc thoi tiet ({exc}); dung gia tri cu.", file=sys.stderr)
            group = cached_weather()

    if args.season:
        season = None if args.season == "off" else args.season
    elif cfg.season == "auto":
        season = current_season(cfg.latitude)
    elif cfg.season in SEASONS:
        season = cfg.season
    else:                       # "off" hoac gia tri la
        season = None

    base = find_base(cfg.wallpapers, phase, season)

    # doc state cu
    try:
        prev = json.loads(STATE.read_text())
    except Exception:
        prev = {}

    key = render_key(base, cfg.resolution)

    if (
        prev.get("phase") == phase
        and prev.get("weather") == group
        and prev.get("key") == key
        and not args.dry_run
    ):
        out = Path(prev.get("output", ""))
        if out.exists():
            print(f"Khong doi: {phase} / {group}")
            return 0

    img = Image.open(base)
    if cfg.resolution:
        img = img.resize(cfg.resolution, Image.LANCZOS)
    img = apply_weather(img, group)

    # doi luan phien 2 file de GNOME chiu reload
    slot = "b" if prev.get("slot") == "a" else "a"
    out = CACHE / f"wallpaper_{slot}.jpg"
    img.save(out, "JPEG", quality=92)

    elev_txt = "n/a" if args.phase else f"{elev:+.1f}\u00b0"
    print(f"phase={phase}  elevation={elev_txt}  season={season or '-'}  "
          f"weather={group}  ->  {out}")

    if not args.dry_run:
        set_wallpaper(out, cfg.setter)
        STATE.write_text(json.dumps(
            {"phase": phase, "weather": group, "slot": slot,
             "output": str(out), "key": key}
        ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
