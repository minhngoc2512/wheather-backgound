#!/usr/bin/env bash
# Fetch the SolarShift wallpapers (32 PNG, ~570 MB) into build/solarshift-src.
# Source: https://github.com/TemujinCalidius/SolarShift (MIT)
set -uo pipefail
BASE="https://raw.githubusercontent.com/TemujinCalidius/SolarShift/main/images"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${OUT:-$ROOT/build/solarshift-src}"
SEASONS="spring summer autumn winter"
TIMES="dawn morning midday afternoon golden_hour dusk twilight night"
fail=0
for s in $SEASONS; do
  mkdir -p "$OUT/$s"
  for t in $TIMES; do
    f="$OUT/$s/$t.png"
    [ -s "$f" ] && continue
    if curl -sS -fL --retry 3 --retry-delay 2 -m 600 -o "$f" "$BASE/$s/$t.png"; then
      echo "ok   $s/$t.png $(stat -c %s "$f")"
    else
      echo "FAIL $s/$t.png"; rm -f "$f"; fail=$((fail+1))
    fi
  done
done
echo "DONE, failures: $fail"
du -sh "$OUT"
