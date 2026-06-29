#!/usr/bin/env python3
"""Bake live KV overrides into data/plot_points.geojson.

Get the production overrides first (or use the Download button in edit.html):
  npx wrangler kv key get --binding=OVERRIDES overrides > data/review/overrides.json

Then:
  python scripts/apply_overrides.py [--clear]

--clear empties overrides.json after baking (safe to skip; re-applying is idempotent).
"""
import json
import os
import sys

POINTS = "data/plot_points.geojson"
OVERRIDES = "data/review/overrides.json"


def main(clear):
    if not os.path.exists(OVERRIDES):
        print("no overrides file found")
        return

    overrides = json.load(open(OVERRIDES))
    if not overrides:
        print("overrides is empty, nothing to do")
        return

    geo = json.load(open(POINTS)) if os.path.exists(POINTS) else {"type": "FeatureCollection", "features": []}

    # Index existing features by plot number for fast lookup
    by_no = {f["properties"]["number"]: i for i, f in enumerate(geo["features"])}

    added = moved = deleted = 0
    for no, o in overrides.items():
        if o.get("deleted"):
            if no in by_no:
                geo["features"].pop(by_no[no])
                # Re-index after deletion
                by_no = {f["properties"]["number"]: i for i, f in enumerate(geo["features"])}
                deleted += 1
        elif isinstance(o.get("lat"), (int, float)) and isinstance(o.get("lon"), (int, float)):
            feat = {
                "type": "Feature",
                "properties": {"number": no},
                "geometry": {"type": "Point", "coordinates": [round(o["lon"], 6), round(o["lat"], 6)]},
            }
            if no in by_no:
                geo["features"][by_no[no]] = feat
                moved += 1
            else:
                geo["features"].append(feat)
                by_no[no] = len(geo["features"]) - 1
                added += 1

    json.dump(geo, open(POINTS, "w"))
    print(f"applied: {added} added, {moved} moved, {deleted} deleted -> {POINTS} ({len(geo['features'])} plots)")

    if clear:
        json.dump({}, open(OVERRIDES, "w"))
        print("cleared overrides.json")


if __name__ == "__main__":
    main("--clear" in sys.argv)
