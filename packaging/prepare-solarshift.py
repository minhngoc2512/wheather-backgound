#!/usr/bin/env python3
"""Chuyen anh SolarShift (5504x3072 PNG, ~18MB/anh) sang JPEG dong goi duoc.

Nguon: https://github.com/TemujinCalidius/SolarShift  (MIT, (c) 2026 Samuel Lison)
"""

import sys
from pathlib import Path

from PIL import Image

TARGET = (2560, 1440)
QUALITY = 88
SEASONS = ("spring", "summer", "autumn", "winter")
TIMES = ("dawn", "morning", "midday", "afternoon",
         "golden_hour", "dusk", "twilight", "night")


def fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cat giua ve dung ti le roi thu nho. Anh goc 1.79 vs 16:9 = 1.78 nen
    chi mat khoang 43px chieu ngang."""
    tw, th = size
    w, h = img.size
    if w / h > tw / th:
        new_w = round(h * tw / th)
        box = ((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h)
    else:
        new_h = round(w * th / tw)
        box = (0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h)
    return img.crop(box).resize(size, Image.LANCZOS)


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    total = 0
    for season in SEASONS:
        out_dir = dst / season
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in TIMES:
            f = src / season / f"{name}.png"
            if not f.exists():
                print(f"  thieu {f}", file=sys.stderr)
                continue
            out = out_dir / f"{name}.jpg"
            fit(Image.open(f).convert("RGB"), TARGET).save(
                out, "JPEG", quality=QUALITY, subsampling=0, optimize=True)
            total += out.stat().st_size
    print(f"  tong {total/1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
