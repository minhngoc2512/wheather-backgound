#!/usr/bin/env python3
"""Tim anh phong canh tren Wikimedia Commons de lam hinh nen.

Tach rieng khoi GUI de test duoc bang CLI va de doi nguon anh sau nay.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "https://commons.wikimedia.org/w/api.php"
UA = "weather-background/1.2 (dynamic wallpaper; contact via local install)"

# Chu de -> tu khoa tim kiem. Nguoi dung chon trong UI.
THEMES = {
    "mountain_lake": ("Mountains & lakes", "mountain lake landscape"),
    "sea":           ("Sea & coast", "sea coast seascape"),
    "forest":        ("Forest & trees", "forest trees woodland"),
    "desert":        ("Desert & dunes", "desert sand dunes"),
}
DEFAULT_THEME = "mountain_lake"

# Tu khoa them theo tung khung gio.
PHASE_TERMS = {
    "night":       "night stars",
    "dawn":        "sunrise dawn",
    "morning":     "morning light",
    "midday":      "daylight noon",
    "afternoon":   "afternoon light",
    "golden_hour": "golden hour warm light",
    "dusk":        "sunset dusk",
    "twilight":    "twilight blue hour",
}

MIN_WIDTH = 1600
MIN_RATIO, MAX_RATIO = 1.25, 2.60      # loai anh doc va panorama qua dai


@dataclass
class Candidate:
    title: str
    width: int
    height: int
    thumb_url: str
    artist: str
    license: str
    page_url: str

    @property
    def label(self) -> str:
        return self.title[5:-4] if self.title.startswith("File:") else self.title


def _strip_html(raw: str) -> str:
    out, depth = [], 0
    for ch in raw:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return " ".join("".join(out).split())


class RateLimited(RuntimeError):
    """Commons dang chan vi goi qua day."""


def _call(params: dict, timeout: int, tries: int = 3) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    delay = 2.0
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                if exc.code == 429:
                    raise RateLimited(
                        "Wikimedia is rate-limiting requests. Wait about a minute and retry."
                    ) from exc
                raise
            # Ton trong Retry-After neu server co gui.
            wait = exc.headers.get("Retry-After") if exc.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else delay)
            delay *= 2
    raise RuntimeError("khong the goi API")


def _query(search_terms: str, limit: int, thumb_width: int,
           timeout: int) -> list[Candidate]:
    data = _call({
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap filemime:image/jpeg {search_terms}".strip(),
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": str(thumb_width),
    }, timeout)

    out: list[Candidate] = []
    for page in data.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [None])[0]
        if not info or not info.get("thumburl"):
            continue
        w, h = info.get("width", 0), info.get("height", 1)
        if w < MIN_WIDTH or not (MIN_RATIO <= w / max(h, 1) <= MAX_RATIO):
            continue
        meta = info.get("extmetadata", {})
        out.append(Candidate(
            title=page.get("title", "?"),
            width=w, height=h,
            thumb_url=info["thumburl"],
            artist=_strip_html(meta.get("Artist", {}).get("value", "")) or "khong ro",
            license=meta.get("LicenseShortName", {}).get("value", "?"),
            page_url=info.get("descriptionurl", ""),
        ))
    return out


def search(theme: str, phase: str, limit: int = 12, thumb_width: int = 240,
           timeout: int = 20) -> list[Candidate]:
    terms = THEMES.get(theme, THEMES[DEFAULT_THEME])[1]
    phase_terms = PHASE_TERMS.get(phase, "")

    found = _query(f"{terms} {phase_terms}", 50, thumb_width, timeout)

    # Vai chu de (rung, sa mac) it anh khop ca hai nhom tu khoa. Bo tu khoa
    # khung gio de con co gi do hien ra, con hon bao "khong tim thay".
    if len(found) < limit:
        seen = {c.title for c in found}
        for cand in _query(terms, 50, thumb_width, timeout):
            if cand.title not in seen:
                found.append(cand)

    # Anh to xep truoc: phong to len 2560 tu ban nho se bi mem.
    found.sort(key=lambda c: c.width * c.height, reverse=True)
    return found[:limit]


def scaled_url(title: str, width: int, timeout: int = 20) -> str:
    """URL ban da thu nho san ve dung chieu rong can - khong tai ban goc
    hang chuc MB ve roi moi resize."""
    data = _call({
        "action": "query", "format": "json", "formatversion": "2",
        "titles": title, "prop": "imageinfo",
        "iiprop": "url", "iiurlwidth": str(width),
    }, timeout)
    pages = data.get("query", {}).get("pages", [])
    if not pages or not pages[0].get("imageinfo"):
        raise LookupError(f"Khong lay duoc anh: {title}")
    info = pages[0]["imageinfo"][0]
    return info.get("thumburl") or info["url"]


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def is_photo(data: bytes, min_saturation: float = 8.0) -> bool:
    """Loc ban khac / anh scan den trang ra khoi ket qua.

    Tu khoa am cua Commons khong dung duoc (no khop ca trong category va
    template nen loai nham gan het), nen loc o phia client tren chinh
    thumbnail da tai ve. Anh xam co do bao hoa gan 0.
    """
    try:
        import io

        from PIL import Image, ImageStat

        img = Image.open(io.BytesIO(data)).convert("HSV")
        return ImageStat.Stat(img).mean[1] >= min_saturation
    except Exception:
        return True          # khong doc duoc thi cu cho qua, de nguoi dung tu nhin
