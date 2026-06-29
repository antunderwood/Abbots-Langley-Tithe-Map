#!/usr/bin/env python3
"""Measure the recovery engine honestly before trusting it.

Hold out a fraction of the ALREADY-located numbers, hide them, and ask targeted_ocr.recover() to
re-find them. We have ground-truth pixel/lon-lat for the held-out set, so we can report real recall
(found at the right place) and precision (of the held-out detections, how many landed correctly).

This is the gate: do not enable auto-accept until precision is high (>=95%) on the held-out set.

Usage:
  micromamba run -n abbots_langley_map python scripts/validate_recovery.py [sheet ...]   # default 4 7
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_plots as op       # noqa: E402
import ml_ocr as ml          # noqa: E402
import targeted_ocr as T     # noqa: E402

HOLD = 0.30
TOL_M = 60   # a recovery counts as correct if within this of the true location


def hav(a, b):
    return T.hav(a, b)


def main(sheets):
    # located with both lon/lat and pixel ground truth, restricted to the chosen sheets
    conf = json.load(open("data/review/confirmed.json"))
    pts = {f["properties"]["number"]: f["geometry"]["coordinates"]
           for f in json.load(open("data/plot_points.geojson"))["features"]}
    truth = {}  # num(str) -> (lon,lat)
    for n, v in conf.items():
        if n.isdigit() and str(v["sheet"]) in sheets and n in pts:
            truth[n] = tuple(pts[n])

    nums = sorted(truth, key=op.natkey)
    # deterministic held-out split (every Nth) so reruns are comparable without Date/random surprises
    step = max(1, round(1 / HOLD))
    held = set(nums[::step])
    keep = [n for n in nums if n not in held]
    print(f"{len(nums)} located on sheets {sheets}; holding out {len(held)}")

    located = {int(n): truth[n] for n in keep}           # what the engine is allowed to see
    plots = set(json.load(open("data/plots.json")))
    all_located = {n for n in conf if n.isdigit()}       # everything placed anywhere on the map
    # search vocabulary: held-out (gradable) plus the genuinely-missing (realistic FP surface)
    vocab = held | (plots - all_located)

    knn = None
    try:
        X, Y, _ = ml.training_set(conf)
        knn = ml.train_knn(X, Y)
    except Exception as e:
        print("KNN off:", e)

    best = T.recover(located, vocab, knn=knn, use_paddle=True, sheets=sheets)

    # grade: for each held-out number, did we recover it within TOL_M of truth?
    found = wrong = 0
    held_detected = 0
    for n in held:
        if n in best:
            held_detected += 1
            d = hav((best[n]["lon"], best[n]["lat"]), truth[n])
            if d <= TOL_M:
                found += 1
            else:
                wrong += 1
                print(f"  held {n}: detected but {d:.0f} m off")
    recall = found / max(1, len(held))
    prec_held = found / max(1, held_detected)
    print(f"\nHELD-OUT: recall {found}/{len(held)} = {recall:.0%}; "
          f"of {held_detected} held-out detections, {found} correct (precision {prec_held:.0%}, {wrong} mislocated)")
    print(f"(total detections incl. real-missing: {len(best)}; those aren't gradable here)")


if __name__ == "__main__":
    main(sys.argv[1:] or ["4", "7"])
