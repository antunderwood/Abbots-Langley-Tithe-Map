#!/usr/bin/env python3
"""Locate tithe-map plot numbers by OCR and write data/plot_points.geojson.

For each original scan: run several OCR passes (raw + upscaled/threshold variants, psm 11 & 12,
digits only), keep only reads that match a known plot number from plots.json, and convert their
pixel positions to lon/lat using that sheet's saved georeferencing GCPs (the .points file).
Every number should occur once; we keep the highest-confidence detection across all sheets.

Coverage is partial by nature (faint/tiny numbers are missed). Missing numbers are written to
data/plots_missing.txt so they can be placed by hand in QGIS (see README).

Usage:
  micromamba run -n abbots_langley_map python scripts/ocr_plots.py            # all sheets
  micromamba run -n abbots_langley_map python scripts/ocr_plots.py 3          # one sheet (test)
"""
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import cv2
import numpy as np

KNOWN = set(json.load(open("data/plots.json")).keys())
SCANS = "source_images/IR30-15-1_%s_Abbotts_Langley_Herts.jpg"
R = 6378137.0  # web-mercator sphere radius


def natkey(s):
    """Sort key tolerant of letter-suffixed plot numbers (e.g. '958a')."""
    m = re.match(r"(\d+)", s)
    return (int(m.group(1)) if m else 0, s)

# OCR confidence floor by digit length: short numbers are easy to hallucinate, so demand more.
MIN_CONF = {1: 75, 2: 55}


# Map numbers sit at field-aligned angles, so OCR each variant at a few rotations and map the
# detections back. Rotation (not contrast) is what recovers most missed numbers.
ANGLES = (0, -10, -6, -3, 3, 6, 10)


def _ocr_image(img, scale, M=None, psms=(11, 12)):
    """OCR one image; yield (number, conf, col, row) in original-scan coords. M maps this
    (possibly rotated) image's coords back to the unrotated variant (cv2 affine, dst->src)."""
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        cv2.imwrite(f.name, img)
        for psm in psms:
            out = subprocess.run(
                ["tesseract", f.name, "stdout", "--psm", str(psm),
                 "-c", "tessedit_char_whitelist=0123456789", "tsv"],
                capture_output=True, text=True).stdout
            for r in csv.DictReader(io.StringIO(out), delimiter="\t"):
                t = (r.get("text") or "").strip()
                if t not in KNOWN:
                    continue
                try:
                    c = float(r.get("conf", -1))
                except ValueError:
                    continue
                if c < MIN_CONF.get(len(t), 30):
                    continue
                col = int(r["left"]) + int(r["width"]) / 2
                row = int(r["top"]) + int(r["height"]) / 2
                if M is not None:  # back to unrotated variant coords (M is the warpAffine matrix)
                    col, row = (M @ np.array([col, row, 1.0]))[:2]
                yield t, c, col / scale, row / scale


def ocr_detections(scan):
    """List of (number, conf, col, row) validated against KNOWN, from several OCR passes."""
    gray = cv2.cvtColor(cv2.imread(scan), cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    dets = []
    # Upright pass: both variants, both PSMs (the original recall).
    dets.extend(_ocr_image(gray, 1))
    dets.extend(_ocr_image(otsu, 2))
    # Rotated passes: cheaper (non-upscaled grey, single PSM) to recover field-angled numbers.
    h, w = gray.shape
    for a in ANGLES:
        if a == 0:
            continue
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        rot = cv2.warpAffine(gray, M, (w, h), borderValue=255)
        dets.extend(_ocr_image(rot, 1, cv2.invertAffineTransform(M), psms=(11,)))
    return dets


def load_gcps(points_path):
    with open(points_path) as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    gcps = []
    for r in csv.DictReader(lines):
        if str(r.get("enable", "1")).strip() == "1":
            gcps.append((float(r["sourceX"]), float(r["sourceY"]), float(r["mapX"]), float(r["mapY"])))
    return gcps


def fit_transform(gcps):
    """Fit pixel(sourceX, sourceY) -> mercator(mapX, mapY). Poly2 if enough points, else affine."""
    src = np.array([(x, y) for x, y, _, _ in gcps])
    dst = np.array([(mx, my) for _, _, mx, my in gcps])
    poly2 = len(gcps) >= 6

    def terms(x, y):
        return [1, x, y, x * x, x * y, y * y] if poly2 else [1, x, y]

    A = np.array([terms(x, y) for x, y in src])
    cx = np.linalg.lstsq(A, dst[:, 0], rcond=None)[0]
    cy = np.linalg.lstsq(A, dst[:, 1], rcond=None)[0]
    return cx, cy, poly2


def to_lonlat(cx, cy, poly2, col, row):
    x, y = col, -row  # QGIS stores sourceY as -row
    t = np.array([1, x, y, x * x, x * y, y * y] if poly2 else [1, x, y])
    mx, my = t @ cx, t @ cy
    lon = mx / R * 180 / math.pi
    lat = (2 * math.atan(math.exp(my / R)) - math.pi / 2) * 180 / math.pi
    return round(lon, 6), round(lat, 6)


def main(sheets):
    located = {}  # number -> (conf, lon, lat, sheet)
    for n in sheets:
        scan = SCANS % n
        pts = scan + ".points"
        if not (os.path.exists(scan) and os.path.exists(pts)):
            print(f"sheet {n}: missing scan or .points, skipping")
            continue
        cx, cy, poly2 = fit_transform(load_gcps(pts))
        dets = ocr_detections(scan)
        kept = 0
        for num, conf, col, row in dets:
            if num not in located or conf > located[num][0]:
                lon, lat = to_lonlat(cx, cy, poly2, col, row)
                located[num] = (conf, lon, lat, int(n))
                kept += 1
        print(f"sheet {n}: {len({d[0] for d in dets})} distinct numbers ({'poly2' if poly2 else 'affine'})")

    features = [{
        "type": "Feature",
        "properties": {"number": num, "conf": round(c, 1), "sheet": sh},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    } for num, (c, lon, lat, sh) in sorted(located.items(), key=lambda kv: natkey(kv[0]))]

    os.makedirs("data", exist_ok=True)
    with open("data/plot_points.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    missing = sorted(KNOWN - located.keys(), key=natkey)
    with open("data/plots_missing.txt", "w") as f:
        f.write("\n".join(missing) + "\n")

    print(f"\nlocated {len(located)}/{len(KNOWN)} plots ({100*len(located)/len(KNOWN):.0f}%)")
    print(f"-> data/plot_points.geojson; {len(missing)} missing -> data/plots_missing.txt")


if __name__ == "__main__":
    sheets = sys.argv[1:] or [str(i) for i in range(1, 8)]
    main(sheets)
