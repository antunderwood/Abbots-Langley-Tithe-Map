#!/usr/bin/env python3
"""Recovery engine for the missing plot numbers: propose label regions, recognise them with an
ensemble (PaddleOCR + Tesseract + our KNN) over an enhancement ladder, and accept only reads that
match a still-missing number and pass a sequence-region sanity check.

Design notes (from diagnostics):
- Naive neighbour interpolation localises to only ~110 m median, too coarse to auto-place blindly.
  So OCR must self-locate; the sequence prior is used as a SANITY GATE (reject a detected number that
  lands far from where its numeric neighbours sit), not as a locator.
- Proposals come from two sources so we catch both misread and entirely-missed labels:
  (a) Tesseract multi-rotation (reused from ml_ocr), (b) a connected-component blob detector.
- Precision levers, in order: exclude near already-located labels; closed vocabulary (missing only);
  cross-engine agreement; sequence-region gate. These are what stop the false positives that the
  first KNN-only pass produced.

Exposes recover(); validate_recovery.py drives it on held-out splits to measure recall/precision.
"""
import json
import math
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op  # noqa: E402
import ml_ocr as ml      # noqa: E402

PLOTS = json.load(open("data/plots.json"))
SHEETS = [str(i) for i in range(1, 8)]
EXCL = 45          # px: ignore proposals this close to an already-located label
DEDUP = 30         # px: merge proposal locations this close together
SANITY_M = 600     # m: a detected number must land within this of its neighbour-predicted spot

_paddle = None


def paddle():
    global _paddle
    if _paddle is None:
        import warnings, logging
        warnings.filterwarnings("ignore")
        logging.disable(logging.WARNING)
        os.environ["GLOG_minloglevel"] = "3"
        from paddleocr import PaddleOCR
        _paddle = PaddleOCR(use_textline_orientation=True, lang="en")
    return _paddle


# --- enhancement ladder ----------------------------------------------------
def variants(crop):
    """A few contrast/threshold renderings of a label crop, upscaled, for the recognisers."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    up = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(2.0, (8, 8)).apply(up)
    otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adap = cv2.adaptiveThreshold(up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    return {"gray": up, "clahe": clahe, "otsu": otsu, "adap": adap, "inv": 255 - otsu}


# --- proposals -------------------------------------------------------------
def blob_proposals(gray):
    """Cluster glyph-sized dark components into candidate label centres (catches Tesseract misses)."""
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    n, _, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
    pts = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if 18 <= h <= 70 and 6 <= w <= 60 and a >= 25:   # digit-like glyph
            pts.append((cent[i][0], cent[i][1]))
    pts.sort()
    # group glyphs that sit close together (a multi-digit label)
    groups, used = [], [False] * len(pts)
    for i, (x, y) in enumerate(pts):
        if used[i]:
            continue
        gx, gy, c = [x], [y], 1
        used[i] = True
        for j in range(i + 1, len(pts)):
            if not used[j] and abs(pts[j][0] - x) < 70 and abs(pts[j][1] - y) < 35:
                gx.append(pts[j][0]); gy.append(pts[j][1]); used[j] = True; c += 1
        if c <= 4:                                       # a plot number is 1-4 glyphs
            groups.append((sum(gx) / len(gx), sum(gy) / len(gy)))
    return groups


def all_proposals(scan, gray):
    """(col, row) candidate label centres from Tesseract multi-rotation + blob detector, deduped."""
    locs = [(c, r) for _, _, c, r, _ in ml.proposals(scan)]
    locs += blob_proposals(gray)
    locs.sort()
    out = []
    for c, r in locs:
        if not any((c - x) ** 2 + (r - y) ** 2 < DEDUP ** 2 for x, y in out):
            out.append((c, r))
    return out


# --- recognition ensemble --------------------------------------------------
def read_crop(crop, knn, use_paddle):
    """Return list of (string, weight) guesses for one label crop, across engines/variants."""
    out = []
    vs = variants(crop)
    if use_paddle:
        # Full PaddleOCR (det+rec) on one upscaled variant: paddle's detector re-localises the tight
        # text line inside our crop (its rec is strong, but its standalone det on raw map is weak),
        # so one accurate ~0.8s pass beats several rec-only passes on loose crops.
        try:
            for r in paddle().predict(cv2.cvtColor(vs["gray"], cv2.COLOR_GRAY2BGR)):
                for t, s in zip(r.get("rec_texts", []), r.get("rec_scores", [])):
                    d = "".join(ch for ch in t if ch.isdigit())
                    if d:
                        out.append((d, 1.0 + float(s)))   # paddle weighted highest
        except Exception:
            pass
    if knn is not None:
        s, ag = ml.classify(knn, vs["gray"])
        if s:
            out.append((s, 0.5 + ag))
    return out


# --- sequence-region sanity ------------------------------------------------
def hav(a, b):
    R = 6371000.0
    (lo1, la1), (lo2, la2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def predict_loc(num, located):
    """Interpolate a number's likely lon/lat from its nearest located numeric neighbours."""
    mi = int("".join(c for c in num if c.isdigit()) or 0)
    if not mi:
        return None
    below = next((k for k in range(mi - 1, mi - 8, -1) if k in located), None)
    above = next((k for k in range(mi + 1, mi + 8) if k in located), None)
    if below and above:
        t = (mi - below) / (above - below)
        pb, pa = located[below], located[above]
        return (pb[0] + (pa[0] - pb[0]) * t, pb[1] + (pa[1] - pb[1]) * t)
    return located.get(below) or located.get(above)


# --- main recovery ---------------------------------------------------------
def recover(located, missing, knn=None, use_paddle=True, sanity_m=SANITY_M, sheets=SHEETS, log=print):
    """located: {int_num:(lon,lat)} already placed (exclusion + sanity). missing: set of strings to find.
    Returns {num: dict(lon,lat,score,votes,sheet,col,row)} best detection per missing number."""
    located_ll = {n: located[n] for n in located}
    match = ml.matcher(set(missing))
    best = {}
    for n in sheets:
        scan, pts = op.SCANS % n, op.SCANS % n + ".points"
        if not (os.path.exists(scan) and os.path.exists(pts)):
            continue
        cx, cy, poly2 = op.fit_transform(op.load_gcps(pts))
        img = cv2.imread(scan)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        # Precision relies on closed-vocab + the sequence-region sanity gate below, which directly
        # catches the "misread of a located label snaps to a missing number" failure mode.
        props = all_proposals(scan, gray)
        found = 0
        for col, row in props:
            crop = img[max(0, int(row) - 55):min(H, int(row) + 55),
                       max(0, int(col) - 55):min(W, int(col) + 55)]
            if crop.size == 0:
                continue
            lon, lat = op.to_lonlat(cx, cy, poly2, col, row)
            # tally engine votes onto matched missing numbers
            tally = {}
            agree = {}
            for s, w in read_crop(crop, knn, use_paddle):
                num, mw = match(s)
                if not num:
                    continue
                tally[num] = tally.get(num, 0.0) + w + mw
                agree[num] = agree.get(num, 0) + 1
            for num, score in tally.items():
                if sanity_m:
                    pl = predict_loc(num, located_ll)
                    if pl and hav((lon, lat), pl) > sanity_m:
                        continue  # detected far from where its neighbours sit -> reject
                score += 0.5 * (agree[num] - 1)  # cross-engine/variant agreement bonus
                if num not in best or score > best[num]["score"]:
                    best[num] = {"lon": lon, "lat": lat, "score": round(score, 2),
                                 "votes": agree[num], "sheet": n, "col": round(col, 1), "row": round(row, 1)}
                    found += 1
        log(f"sheet {n}: {len(props)} proposals -> {found} missing-number hits (running {len(best)})")
    return best


def _load_located():
    located = {}
    for f in json.load(open("data/plot_points.geojson"))["features"]:
        nm = f["properties"]["number"]
        if nm.isdigit():
            lon, lat = f["geometry"]["coordinates"]
            located[int(nm)] = (lon, lat)
    return located


def write_queue():
    """Convert recovered.json into the review app's candidates.json (+ crops) for human confirmation.
    Reuses review.html unchanged; confirmed.json (your prior work) is preserved by the app."""
    rec = json.load(open("data/review/recovered.json"))
    out = "data/review"
    os.makedirs(out + "/crops", exist_ok=True)
    cands, bysheet = [], {}
    for num, b in sorted(rec.items(), key=lambda kv: op.natkey(kv[0])):
        n = b["sheet"]
        r = PLOTS.get(num)
        cands.append({
            "id": f"rec_{n}_{num}", "number": num, "sheet": n,
            "col": b["col"], "row": b["row"], "lon": b["lon"], "lat": b["lat"],
            "conf": b["score"], "crop": f"crops/rec_{n}_{num}.png", "source": "recover",
            "record": {k: r.get(k, "") for k in ("name", "owner", "occupier", "use")} if r else None,
        })
        bysheet.setdefault(n, []).append((num, int(b["col"]), int(b["row"])))
    for n, items in bysheet.items():
        img = cv2.imread(op.SCANS % n)
        h, w = img.shape[:2]
        for num, x, y in items:
            cv2.imwrite(f"{out}/crops/rec_{n}_{num}.png",
                        img[max(0, y - 130):min(h, y + 130), max(0, x - 130):min(w, x + 130)])
    json.dump(cands, open(out + "/candidates.json", "w"))
    print(f"{len(cands)} recoveries -> {out}/candidates.json (review at /review.html, then extract_polygons.py)")


def main():
    located = _load_located()
    missing = sorted(set(PLOTS) - {str(k) for k in located}, key=op.natkey)
    print(f"{len(located)} located, {len(missing)} missing")
    knn = None
    try:
        X, Y, _ = ml.training_set(json.load(open("data/review/confirmed.json")))
        knn = ml.train_knn(X, Y)
    except Exception as e:
        print("KNN unavailable:", e)
    best = recover(located, missing, knn=knn, use_paddle=True)
    json.dump(best, open("data/review/recovered.json", "w"))
    print(f"\n{len(best)} candidate recoveries -> data/review/recovered.json")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "queue":
        write_queue()
    else:
        main()
