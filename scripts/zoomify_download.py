#!/usr/bin/env python3
"""Download the Abbots Langley tithe-map Zoomify tilesets and stitch each to a full-res image.

The 7 source areas live on eforms.org.uk as Zoomify pyramids (pixel space). This pulls every
tile of the highest-resolution tier and reassembles it into one image per area, ready to
georeference in QGIS/MapWarper.

Notes:
  - That server's TLS cert is expired, so HTTPS verification is disabled and we stay on HTTP.
  - Tiles are cached on disk; re-runs skip what's already downloaded. Be polite: throttled + retries.
  - Output is for YOUR georeferencing. Re-hosting the scans needs ALLHS permission.

Usage:
  python3 scripts/zoomify_download.py                # all 7 areas
  python3 scripts/zoomify_download.py 3 5            # only areas 3 and 5
  python3 scripts/zoomify_download.py --selfcheck    # verify tile math, no network
"""
import math
import os
import ssl
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image  # pip install pillow

BASE = "http://eforms.org.uk/allhstithemap"
IMAGE = "IR30-15-1_%d_Abbotts_Langley_Herts"
OUTDIR = os.path.join(os.path.dirname(__file__), "..", "source_images")
TILESIZE = 256
THROTTLE = 0.05  # seconds between tile requests; gentle on a small society's server
RETRIES = 4
UA = "AbbotsLangleyTitheMap/1.0 (local georeferencing; contact via allhs.org.uk)"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE  # ponytail: cert is expired; HTTP only, no secrets in transit


def _get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
                return r.read() if binary else r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"failed after {RETRIES} tries: {url}: {last}")


def levels(width, height, tilesize=TILESIZE):
    """Zoomify tiers, smallest tier first. Each entry: (level_width, level_height)."""
    dims = []
    w, h = width, height
    while True:
        dims.append((w, h))
        if w <= tilesize and h <= tilesize:
            break
        w, h = (w + 1) // 2, (h + 1) // 2
    dims.reverse()
    return dims


def tile_plan(width, height, tilesize=TILESIZE):
    """Ordered list of full tile records with their Zoomify TileGroup.

    Tiles are globally indexed across all tiers (smallest tier first), row-major within a
    tier; TileGroup = index // 256. Returns only the highest-resolution tier (the one we stitch),
    each as (group, level, col, row, px, py)."""
    dims = levels(width, height, tilesize)
    top = len(dims) - 1
    index = 0
    top_tiles = []
    for level, (lw, lh) in enumerate(dims):
        cols = math.ceil(lw / tilesize)
        rows = math.ceil(lh / tilesize)
        for row in range(rows):
            for col in range(cols):
                if level == top:
                    top_tiles.append((index // 256, level, col, row, col * tilesize, row * tilesize))
                index += 1
    return top_tiles, index  # index == total tile count (matches NUMTILES)


def get_props(image):
    xml = _get(f"{BASE}/{image}/ImageProperties.xml")
    a = ET.fromstring(xml).attrib
    return int(a["WIDTH"]), int(a["HEIGHT"]), int(a.get("TILESIZE", TILESIZE))


def fetch_area(n):
    image = IMAGE % n
    width, height, ts = get_props(image)
    plan, total = tile_plan(width, height, ts)
    print(f"area {n}: {width}x{height}, {total} tiles, {len(plan)} at full res")

    cache = os.path.join(OUTDIR, image, "tiles")
    os.makedirs(cache, exist_ok=True)
    canvas = Image.new("RGB", (width, height), "white")

    for i, (group, level, col, row, px, py) in enumerate(plan):
        name = f"{level}-{col}-{row}.jpg"
        path = os.path.join(cache, name)
        if not os.path.exists(path):
            data = _get(f"{BASE}/{image}/TileGroup{group}/{name}", binary=True)
            with open(path, "wb") as f:
                f.write(data)
            time.sleep(THROTTLE)
        with Image.open(path) as t:
            canvas.paste(t, (px, py))
        if (i + 1) % 50 == 0 or i + 1 == len(plan):
            print(f"  {i + 1}/{len(plan)} tiles", end="\r", flush=True)

    out = os.path.join(OUTDIR, f"{image}.jpg")
    canvas.save(out, quality=92)
    print(f"\n  wrote {out}")
    return out


def _selfcheck():
    # Area 3 is known to have 5460x3744 and NUMTILES=451 (from its ImageProperties.xml).
    _, total = tile_plan(5460, 3744)
    assert total == 451, f"expected 451 tiles, computed {total}"
    # Sanity: top tier of a 5460x3744 image is 22x15 tiles = 330.
    plan, _ = tile_plan(5460, 3744)
    assert len(plan) == 330, len(plan)
    print("selfcheck OK: tile math matches NUMTILES=451")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selfcheck"]:
        _selfcheck()
    else:
        os.makedirs(OUTDIR, exist_ok=True)
        areas = [int(a) for a in args] if args else list(range(1, 8))
        for n in areas:
            fetch_area(n)
