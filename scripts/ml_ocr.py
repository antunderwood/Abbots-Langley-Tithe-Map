#!/usr/bin/env python3
"""Learn this map's digit style from confirmed plots, then re-OCR to recover missing numbers.

Idea: the 686 confirmed labels are labelled training data in the map's own engraved typeface. Train
a small digit classifier (OpenCV KNN) on their glyphs, then run a thorough multi-rotation Tesseract
sweep to PROPOSE digit regions, and for each proposal classify the glyphs ourselves and accept it
only if it matches a still-missing plot number (closed vocabulary, with edit-distance-1 snapping).

Honest scope: training glyphs come from readable labels, so recall on the genuinely faint/obscured
missing numbers is limited. Detections are not auto-placed; they go to the review queue for you to
confirm, because a wrong read of a valid missing number would land a plot in the wrong spot.

Usage:
  micromamba run -n abbots_langley_map python scripts/ml_ocr.py train   # train + report accuracy
  micromamba run -n abbots_langley_map python scripts/ml_ocr.py         # full: train + detect -> queue
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op  # noqa: E402

PLOTS = json.load(open("data/plots.json"))
OUT = "data/review"
SZ = 20            # normalised glyph size
RAWMIN = 20        # keep weak Tesseract proposals; closed-vocab + review filter the junk
EXCL = 45          # px: ignore proposals this close to an already-confirmed label
CROP = 130         # half-size of the review thumbnail
HOLDOUT = 0.15


# --- glyph handling --------------------------------------------------------
def deskew(g):
    """Shear-correct a glyph using image moments (standard OpenCV digit trick)."""
    m = cv2.moments(g)
    if abs(m["mu02"]) < 1e-2:
        return g.copy()
    skew = m["mu11"] / m["mu02"]
    M = np.array([[1, skew, -0.5 * SZ * skew], [0, 1, 0]], np.float32)
    return cv2.warpAffine(g, M, (SZ, SZ), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR)


def norm_glyph(bw, x, y, w, h):
    """Crop one component to a square, resize to SZ, deskew -> uint8 SZxSZ (ink=white)."""
    pad = max(w, h)
    cy, cx = y + h // 2, x + w // 2
    half = pad // 2 + 2
    sub = bw[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    if sub.size == 0:
        return None
    sq = cv2.copyMakeBorder(sub, 0, max(0, sub.shape[1] - sub.shape[0]),
                            0, max(0, sub.shape[0] - sub.shape[1]), cv2.BORDER_CONSTANT, value=0)
    return deskew(cv2.resize(sq, (SZ, SZ), interpolation=cv2.INTER_AREA))


def segment(gray):
    """Split a grayscale label crop into left-to-right digit glyphs. Returns [(cx, glyph)]."""
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]  # ink=white
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    H, W = gray.shape
    comps = [tuple(stats[i]) for i in range(1, n)]                       # (x,y,w,h,area)
    comps = [c for c in comps if c[4] >= 15 and c[3] >= 8 and c[3] < 0.9 * H and c[2] < 0.6 * W]
    if not comps:
        return []
    med = np.median([c[3] for c in comps])                              # typical glyph height
    band = [c for c in comps if 0.55 * med <= c[3] <= 1.7 * med]
    cyc = H / 2
    band = [c for c in band if abs((c[1] + c[3] / 2) - cyc) < 0.9 * med]  # same text line as centre
    out = []
    for x, y, w, h, _ in sorted(band, key=lambda c: c[0]):
        g = norm_glyph(bw, x, y, w, h)
        if g is not None:
            out.append((x, g))
    return out


# --- training --------------------------------------------------------------
def training_set(confirmed):
    """Glyphs from confirmed labels whose component count matches the known digit string."""
    X, Y, used = [], [], 0
    by_sheet = {}
    for num, v in confirmed.items():
        if not num.isdigit() or "col" not in v or "row" not in v:
            continue  # need a pixel location and a clean digit string
        by_sheet.setdefault(str(v["sheet"]), []).append((num, int(v["col"]), int(v["row"])))
    for n, items in by_sheet.items():
        scan = op.SCANS % n
        if not os.path.exists(scan):
            continue
        gray = cv2.cvtColor(cv2.imread(scan), cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        for num, cx, cy in items:
            crop = gray[max(0, cy - 70):min(H, cy + 70), max(0, cx - 70):min(W, cx + 70)]
            glyphs = segment(crop)
            if len(glyphs) != len(num):
                continue  # ambiguous segmentation; skip (plenty of clean labels remain)
            for (_, g), d in zip(glyphs, num):
                X.append(g.flatten())
                Y.append(int(d))
            used += 1
    return np.array(X, np.float32), np.array(Y, np.int32), used


def train_knn(X, Y, report=False):
    idx = np.arange(len(X))
    np.random.seed(0)
    np.random.shuffle(idx)
    cut = int(len(idx) * (1 - HOLDOUT))
    tr, te = idx[:cut], idx[cut:]
    knn = cv2.ml.KNearest_create()
    knn.train(X[tr], cv2.ml.ROW_SAMPLE, Y[tr])
    if report and len(te):
        _, pred, _, _ = knn.findNearest(X[te], k=5)
        acc = float((pred.ravel() == Y[te]).mean())
        print(f"held-out digit accuracy: {acc:.3f} on {len(te)} glyphs ({len(tr)} train)")
    # retrain on everything for use
    knn = cv2.ml.KNearest_create()
    knn.train(X, cv2.ml.ROW_SAMPLE, Y)
    return knn


def classify(knn, gray):
    """Read a label crop with the trained model: returns (string, min_agreement_0to1)."""
    glyphs = segment(gray)
    if not glyphs:
        return "", 0.0
    feats = np.array([g.flatten() for _, g in glyphs], np.float32)
    _, res, nbr, _ = knn.findNearest(feats, k=5)
    s, agree = "", 1.0
    for i in range(len(glyphs)):
        d = int(res[i][0])
        s += str(d)
        agree = min(agree, (nbr[i] == d).mean())  # fraction of neighbours backing this digit
    return s, agree


# --- closed-vocabulary matching --------------------------------------------
def lev(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def matcher(missing):
    digit_missing = sorted(m for m in missing if m.isdigit())

    def match(s):
        if not s:
            return None, 0
        if s in missing:
            return s, 2                                   # exact
        near = [m for m in digit_missing if lev(s, m) <= 1]
        if len(near) == 1:
            return near[0], 1                             # unique edit-distance-1 snap
        return None, 0
    return match


# --- thorough multi-rotation Tesseract proposals ---------------------------
def _tess(img, scale, Minv, angle, psms):
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        cv2.imwrite(f.name, img)
        for psm in psms:
            out = subprocess.run(
                ["tesseract", f.name, "stdout", "--psm", str(psm),
                 "-c", "tessedit_char_whitelist=0123456789", "tsv"],
                capture_output=True, text=True).stdout
            for r in csv.DictReader(io.StringIO(out), delimiter="\t"):
                t = (r.get("text") or "").strip()
                if not t.isdigit():
                    continue
                try:
                    conf = float(r.get("conf", -1))
                except ValueError:
                    continue
                if conf < RAWMIN:
                    continue
                col = int(r["left"]) + int(r["width"]) / 2
                row = int(r["top"]) + int(r["height"]) / 2
                if Minv is not None:
                    col, row = (Minv @ np.array([col, row, 1.0]))[:2]
                yield t, conf, col / scale, row / scale, angle


def proposals(scan):
    gray = cv2.cvtColor(cv2.imread(scan), cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    out = list(_tess(gray, 1, None, 0, (11, 12))) + list(_tess(otsu, 2, None, 0, (11, 12)))
    h, w = gray.shape
    for a in op.ANGLES:
        if a == 0:
            continue
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        rot = cv2.warpAffine(gray, M, (w, h), borderValue=255)
        out += list(_tess(rot, 1, cv2.invertAffineTransform(M), a, (11,)))
    return out


def detect(knn, confirmed, missing):
    match = matcher(set(missing))
    best = {}  # number -> dict(score, agree, conf, sheet, col, row)
    for n in [str(i) for i in range(1, 8)]:
        scan, pts = op.SCANS % n, op.SCANS % n + ".points"
        if not (os.path.exists(scan) and os.path.exists(pts)):
            continue
        gray = cv2.cvtColor(cv2.imread(scan), cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        taken = [(int(v["col"]), int(v["row"])) for v in confirmed.values()
                 if str(v["sheet"]) == n and "col" in v]
        found = 0
        for t, conf, cx, cy, a in proposals(scan):
            if any((cx - x) ** 2 + (cy - y) ** 2 < EXCL ** 2 for x, y in taken):
                continue  # already have a confirmed label here
            # rotate the crop to the angle that read it, then classify in our own model
            crop = gray[max(0, int(cy) - 70):min(H, int(cy) + 70),
                        max(0, int(cx) - 70):min(W, int(cx) + 70)]
            if crop.size == 0:
                continue
            if a:
                ch, cw = crop.shape
                Rm = cv2.getRotationMatrix2D((cw / 2, ch / 2), a, 1.0)
                crop = cv2.warpAffine(crop, Rm, (cw, ch), borderValue=255)
            ours, agree = classify(knn, crop)
            # two votes: our classifier and Tesseract. closed-vocab decides which (if any) lands.
            cands = []
            for s, w_extra in ((ours, agree), (t, conf / 100.0)):
                num, w = match(s)
                if num:
                    cands.append((w + (1 if ours == t else 0) + w_extra, num, agree, conf))
            if not cands:
                continue
            score, num, ag, cf = max(cands)
            if num not in best or score > best[num]["score"]:
                best[num] = {"score": score, "agree": round(ag, 2), "conf": round(cf, 1),
                             "sheet": n, "col": round(cx, 1), "row": round(cy, 1)}
                found += 1
        print(f"sheet {n}: {found} candidate missing numbers proposed")
    return best


def write_queue(best):
    os.makedirs(OUT + "/crops", exist_ok=True)
    tf = {}
    cands = []
    bysheet = {}
    for num, b in best.items():
        n = b["sheet"]
        if n not in tf:
            tf[n] = op.fit_transform(op.load_gcps(op.SCANS % n + ".points"))
        cx, cy, poly2 = tf[n]
        lon, lat = op.to_lonlat(cx, cy, poly2, b["col"], b["row"])
        rec = PLOTS.get(num)
        cands.append({
            "id": f"ml_{n}_{num}", "number": num, "sheet": n,
            "col": b["col"], "row": b["row"], "lon": lon, "lat": lat,
            "conf": b["conf"], "crop": f"crops/ml_{n}_{num}.png", "source": "ml",
            "record": {k: rec.get(k, "") for k in ("name", "owner", "occupier", "use")} if rec else None,
        })
        bysheet.setdefault(n, []).append((num, int(b["col"]), int(b["row"])))
    for n, items in bysheet.items():
        img = cv2.imread(op.SCANS % n)
        h, w = img.shape[:2]
        for num, x, y in items:
            cv2.imwrite(f"{OUT}/crops/ml_{n}_{num}.png",
                        img[max(0, y - CROP):min(h, y + CROP), max(0, x - CROP):min(w, x + CROP)])
    cands.sort(key=lambda c: op.natkey(c["number"]))
    json.dump(cands, open(OUT + "/candidates.json", "w"))
    print(f"\n{len(cands)} ML candidates -> {OUT}/candidates.json (review, then extract_polygons.py)")


def selftest():
    assert lev("313", "313") == 0 and lev("313", "318") == 1 and lev("31", "318") == 1
    assert deskew(np.zeros((SZ, SZ), np.uint8)).shape == (SZ, SZ)
    m = matcher({"313", "999"})
    assert m("313") == ("313", 2) and m("318")[0] == "313" and m("777")[0] is None
    print("selftest ok")


def main():
    confirmed = json.load(open(OUT + "/confirmed.json"))
    missing = sorted(set(PLOTS) - set(confirmed), key=op.natkey)
    print(f"{len(confirmed)} confirmed, {len(missing)} missing to hunt for")
    X, Y, used = training_set(confirmed)
    print(f"trained on {used} clean labels -> {len(X)} digit glyphs")
    knn = train_knn(X, Y, report=True)
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        return
    best = detect(knn, confirmed, missing)
    write_queue(best)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        main()
