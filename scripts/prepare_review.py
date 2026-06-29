#!/usr/bin/env python3
"""Classify OCR detections into auto-accepted seeds and a review queue, for the confirmation app.

Confident (auto-accepted): a known number, 3+ digits, OCR confidence >= threshold. Everything else
- short 1-2 digit reads (unreliable), low confidence, or a number found in two places - goes to the
review queue with a cropped thumbnail and its record, for you to confirm/correct/reject.

Writes under data/review/: confirmed.json (seeds), candidates.json (queue), crops/, sheets.json.
Reuses scripts/ocr_plots.py. Re-run any time; it rebuilds from scratch (keeps no manual edits, so
run BEFORE reviewing, not after).

Usage: micromamba run -n abbots_langley_map python scripts/prepare_review.py [sheet ...]
"""
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op  # noqa: E402

PLOTS = json.load(open("data/plots.json"))
OUT = "data/review"
CONF_MIN = 70
CROP = 130  # half-size of the thumbnail around a label


def digits(num):
    return sum(c.isdigit() for c in num)


def main(sheets):
    os.makedirs(OUT + "/crops", exist_ok=True)
    tf = {}      # sheet -> (cx, cy, poly2)
    bounds = {}  # sheet -> [W,S,E,N] lon/lat
    best = {}    # number -> (conf, sheet, col, row)
    for n in sheets:
        scan, pts = op.SCANS % n, op.SCANS % n + ".points"
        if not (os.path.exists(scan) and os.path.exists(pts)):
            continue
        cx, cy, poly2 = op.fit_transform(op.load_gcps(pts))
        tf[n] = (cx, cy, poly2)
        for num, c, x, y in op.ocr_detections(scan):
            if num not in best or c > best[num][0]:
                best[num] = (c, n, x, y)

    # Preserve any prior review: keep existing confirmed seeds, and don't re-queue confirmed numbers.
    confirmed = {}
    if os.path.exists(OUT + "/confirmed.json"):
        confirmed = json.load(open(OUT + "/confirmed.json"))
    candidates, bysheet = [], {}
    for num, (c, n, x, y) in best.items():
        if num in confirmed:
            continue  # already decided in a previous review pass
        cx, cy, poly2 = tf[n]
        lon, lat = op.to_lonlat(cx, cy, poly2, x, y)
        seed = {"sheet": n, "col": round(x, 1), "row": round(y, 1), "lon": lon, "lat": lat}
        if num in PLOTS and digits(num) >= 3 and c >= CONF_MIN:
            confirmed[num] = seed
        else:
            rec = PLOTS.get(num)
            candidates.append({
                "id": f"{n}_{num}", "number": num, **seed, "conf": round(c, 1),
                "crop": f"crops/{n}_{num}.png",
                "record": {k: rec.get(k, "") for k in ("name", "owner", "occupier", "use")} if rec else None,
            })
            bysheet.setdefault(n, []).append((num, x, y))

    # crop thumbnails: load each sheet once
    for n, items in bysheet.items():
        img = cv2.imread(op.SCANS % n)
        h, w = img.shape[:2]
        for num, x, y in items:
            x, y = int(x), int(y)
            cv2.imwrite(f"{OUT}/crops/{n}_{num}.png",
                        img[max(0, y - CROP):min(h, y + CROP), max(0, x - CROP):min(w, x + CROP)])

    # sheet lon/lat bounds (so the add-on-map tool can assign a click to a sheet)
    for n, (cx, cy, poly2) in tf.items():
        ds = cv2.imread(op.SCANS % n)
        H, W = ds.shape[:2]
        cs = [op.to_lonlat(cx, cy, poly2, X, Y) for X in (0, W) for Y in (0, H)]
        bounds[n] = [min(p[0] for p in cs), min(p[1] for p in cs),
                     max(p[0] for p in cs), max(p[1] for p in cs)]

    json.dump(confirmed, open(OUT + "/confirmed.json", "w"))
    json.dump(candidates, open(OUT + "/candidates.json", "w"))
    json.dump(bounds, open(OUT + "/sheets.json", "w"))
    print(f"auto-accepted {len(confirmed)} confident seeds; {len(candidates)} queued for review")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(i) for i in range(1, 8)])
