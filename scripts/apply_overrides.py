#!/usr/bin/env python3
"""Bake the live edit layer into confirmed.json so polygons can be rebuilt offline.

The deployed editor writes point moves/adds/deletes to a KV-backed overrides layer that the viewer
merges live, but polygons are derived from confirmed.json by the watershed step. Periodically fold
the overrides back into confirmed.json, then rerun extract_polygons.py to refresh the polygons.

Get the production overrides into data/review/overrides.json first, e.g.:
  npx wrangler kv key get --binding=OVERRIDES overrides > data/review/overrides.json
(locally it already lives there.) Then:
  micromamba run -n abbots_langley_map python scripts/apply_overrides.py [--clear]
  micromamba run -n abbots_langley_map python scripts/extract_polygons.py

--clear empties overrides.json after baking (housekeeping; safe to skip since re-applying is idempotent).
"""
import json
import os
import sys

CONFIRMED = "data/review/confirmed.json"
OVERRIDES = "data/review/overrides.json"
SHEETS = "data/review/sheets.json"


def sheet_for(sheets, lon, lat):
    """Smallest sheet bbox containing the point (sheets overlap at the seams)."""
    best, area = None, 1e18
    for n, b in sheets.items():
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]:
            a = (b[2] - b[0]) * (b[3] - b[1])
            if a < area:
                area, best = a, n
    return best


def main(clear):
    if not os.path.exists(OVERRIDES):
        print("no overrides to apply")
        return
    confirmed = json.load(open(CONFIRMED))
    overrides = json.load(open(OVERRIDES))
    sheets = json.load(open(SHEETS))
    moved = deleted = skipped = 0
    for no, o in overrides.items():
        if o.get("deleted"):
            if confirmed.pop(no, None) is not None:
                deleted += 1
        elif isinstance(o.get("lat"), (int, float)):
            n = sheet_for(sheets, o["lon"], o["lat"])
            if not n:
                print(f"  {no}: outside all sheets, skipped")
                skipped += 1
                continue
            confirmed[no] = {"sheet": int(n), "lon": round(o["lon"], 6), "lat": round(o["lat"], 6)}
            moved += 1
    json.dump(confirmed, open(CONFIRMED, "w"))
    print(f"applied: {moved} moved/added, {deleted} deleted, {skipped} skipped -> {CONFIRMED} ({len(confirmed)} plots)")
    if clear:
        json.dump({}, open(OVERRIDES, "w"))
        print("cleared overrides.json")
    print("now run: micromamba run -n abbots_langley_map python scripts/extract_polygons.py")


if __name__ == "__main__":
    main("--clear" in sys.argv)
