#!/usr/bin/env python3
"""Build plot points + field polygons from seeds, via seed-controlled watershed.

Each plot number sits inside its field. Watershed grows one bounded region per seed, splitting
adjacent fields (e.g. 62 vs 69) and giving every seed a polygon. Outputs both
data/plot_points.geojson and data/plot_polygons.geojson (consistent: a point is its seed, the
polygon its watershed region).

Seeds come from data/review/confirmed.json when present (the reviewed/added set), else from OCR
(scripts/ocr_plots.py). Confirmed seeds added on the map carry only lon/lat; those are converted
back to pixels with a reverse GCP fit. Reuses ocr_plots for OCR + the forward transform.

Usage: micromamba run -n abbots_langley_map python scripts/extract_polygons.py [sheet ...]
"""
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op  # noqa: E402

CONFIRMED = "data/review/confirmed.json"
MAXFRAC = 0.08
MINPX = 500


def fit_reverse(gcps):
    """Fit mercator(mapX,mapY) -> pixel(sourceX,sourceY); QGIS stores sourceY = -row."""
    src = np.array([(mx, my) for _, _, mx, my in gcps])
    dst = np.array([(sx, sy) for sx, sy, _, _ in gcps])
    poly2 = len(gcps) >= 6

    def terms(x, y):
        return [1, x, y, x * x, x * y, y * y] if poly2 else [1, x, y]

    A = np.array([terms(x, y) for x, y in src])
    rx = np.linalg.lstsq(A, dst[:, 0], rcond=None)[0]
    ry = np.linalg.lstsq(A, dst[:, 1], rcond=None)[0]
    return rx, ry, poly2


def lonlat_to_pixel(rev, lon, lat):
    rx, ry, poly2 = rev
    mx = lon * op.R * math.pi / 180
    my = op.R * math.log(math.tan(math.pi / 4 + lat * math.pi / 360))
    t = np.array([1, mx, my, mx * mx, mx * my, my * my] if poly2 else [1, mx, my])
    return float(t @ rx), -float(t @ ry)  # col, row


def seeds_for(n, scan, rev):
    """number -> (conf, col, row): confirmed seeds for this sheet, else best OCR."""
    if os.path.exists(CONFIRMED):
        out = {}
        for num, v in json.load(open(CONFIRMED)).items():
            if int(v["sheet"]) != int(n):
                continue
            if "col" in v and v["col"] is not None:
                out[num] = (100.0, float(v["col"]), float(v["row"]))
            else:  # map-added: only lon/lat
                col, row = lonlat_to_pixel(rev, v["lon"], v["lat"])
                out[num] = (100.0, col, row)
        if out:
            return out
    best = {}
    for num, c, x, y in op.ocr_detections(scan):
        if num not in best or c > best[num][0]:
            best[num] = (c, x, y)
    return best


def watershed(scan, seeds):
    img = cv2.imread(scan)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ridge = cv2.cvtColor(255 - cv2.GaussianBlur(gray, (0, 0), 1.0), cv2.COLOR_GRAY2BGR)
    markers = np.zeros(gray.shape, np.int32)
    info = {}
    for k, (num, (c, x, y)) in enumerate(seeds.items(), 1):
        cv2.circle(markers, (int(x), int(y)), 4, k, -1)
        info[k] = (num, c, x, y)
    cv2.watershed(ridge, markers)
    return markers, info, gray.shape[0] * gray.shape[1]


def ring_for(markers, label, cx, cy, poly2):
    cnts, _ = cv2.findContours((markers == label).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 0.004 * cv2.arcLength(c, True), True)
    if len(c) < 3:
        return None
    ring = [op.to_lonlat(cx, cy, poly2, float(x), float(y)) for [[x, y]] in c]
    ring.append(ring[0])
    return ring


def main(sheets):
    points, polys = {}, {}  # number -> (conf, lon, lat, sheet) / (conf, ring, sheet)
    for n in sheets:
        scan, pts = op.SCANS % n, op.SCANS % n + ".points"
        if not (os.path.exists(scan) and os.path.exists(pts)):
            continue
        gcps = op.load_gcps(pts)
        cx, cy, poly2 = op.fit_transform(gcps)
        seeds = seeds_for(n, scan, fit_reverse(gcps))
        markers, info, total = watershed(scan, seeds)
        npoly = 0
        for label, (num, conf, x, y) in info.items():
            lon, lat = op.to_lonlat(cx, cy, poly2, x, y)
            if num not in points or conf > points[num][0]:
                points[num] = (conf, lon, lat, int(n))
            area = int((markers == label).sum())
            if MINPX < area <= MAXFRAC * total:
                ring = ring_for(markers, label, cx, cy, poly2)
                if ring and (num not in polys or conf > polys[num][0]):
                    polys[num] = (conf, ring, int(n))
                    npoly += 1
        print(f"sheet {n}: {len(seeds)} seeds -> {npoly} polygons")

    os.makedirs("data", exist_ok=True)
    pf = [{"type": "Feature", "properties": {"number": k, "sheet": s, "conf": round(c, 1)},
           "geometry": {"type": "Point", "coordinates": [lon, lat]}}
          for k, (c, lon, lat, s) in sorted(points.items(), key=lambda kv: op.natkey(kv[0]))]
    json.dump({"type": "FeatureCollection", "features": pf}, open("data/plot_points.geojson", "w"))
    gf = [{"type": "Feature", "properties": {"number": k, "sheet": s},
           "geometry": {"type": "Polygon", "coordinates": [ring]}}
          for k, (c, ring, s) in sorted(polys.items(), key=lambda kv: op.natkey(kv[0]))]
    json.dump({"type": "FeatureCollection", "features": gf}, open("data/plot_polygons.geojson", "w"))
    print(f"\n{len(points)} points, {len(polys)} polygons -> data/")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(i) for i in range(1, 8)])
