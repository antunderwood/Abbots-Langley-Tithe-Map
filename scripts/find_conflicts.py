#!/usr/bin/env python3
"""Find confirmed labels that share a location (same physical number read as several plots).

The multi-rotation OCR proposes one label several times with slightly different reads; if more than
one was confirmed, two seeds land on one field. Cluster confirmed entries that sit within TOL pixels
on the same sheet, write data/review/conflicts.json + a crop per cluster for the resolver UI.

Usage: micromamba run -n abbots_langley_map python scripts/find_conflicts.py
"""
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op  # noqa: E402

PLOTS = json.load(open("data/plots.json"))
OUT = "data/review"
TOL = 12   # px: entries this close on a sheet are the same label
CROP = 150


def clusters(entries):
    """Greedy spatial clustering of (num, col, row) on one sheet."""
    out = []
    for num, x, y in entries:
        for c in out:
            if abs(c["col"] - x) <= TOL and abs(c["row"] - y) <= TOL:
                c["members"].append(num)
                break
        else:
            out.append({"col": x, "row": y, "members": [num]})
    return [c for c in out if len(c["members"]) > 1]


def main():
    confirmed = json.load(open(OUT + "/confirmed.json"))
    bysheet = {}
    for num, v in confirmed.items():
        if "col" not in v or "row" not in v:
            continue  # map-added points have no pixel; skip (can't crop reliably)
        bysheet.setdefault(str(v["sheet"]), []).append((num, v["col"], v["row"]))

    os.makedirs(OUT + "/crops", exist_ok=True)
    conflicts = []
    for n, entries in bysheet.items():
        cs = clusters(entries)
        if not cs:
            continue
        img = cv2.imread(op.SCANS % n)
        h, w = img.shape[:2]
        for c in cs:
            x, y = int(c["col"]), int(c["row"])
            crop = f"crops/conflict_{n}_{x}_{y}.png"
            cv2.imwrite(f"{OUT}/{crop}",
                        img[max(0, y - CROP):min(h, y + CROP), max(0, x - CROP):min(w, x + CROP)])
            members = sorted(c["members"], key=op.natkey)
            conflicts.append({
                "sheet": n, "col": c["col"], "row": c["row"], "members": members, "crop": crop,
                "records": {m: ({k: PLOTS[m].get(k, "") for k in ("name", "owner", "occupier", "use")}
                                if m in PLOTS else None) for m in members},
            })
    conflicts.sort(key=lambda c: (c["sheet"], op.natkey(c["members"][0])))
    json.dump(conflicts, open(OUT + "/conflicts.json", "w"))
    print(f"{len(conflicts)} conflict clusters -> {OUT}/conflicts.json")


if __name__ == "__main__":
    main()
