#!/usr/bin/env python3
"""Eyeball a georeferenced sheet's alignment: OSM and the warped historic raster side by side.

Both panels share the sheet's own extent and pixel grid, so a feature should land at the same
spot in each. Trace a feature that exists on both maps (the canal, a main road) to judge the fit.

Usage:
  micromamba run -n abbots_langley_map python scripts/align_check.py sheet3_modified.tif [out.jpg] [zoom]

Output defaults to <tif>_check.jpg next to the input.
"""
import math
import os
import subprocess
import sys
import urllib.request

from osgeo import gdal, osr
from PIL import Image

gdal.UseExceptions()  # future-proof default; also silences the GDAL 4.0 warning

WORLD = 20037508.342789244
UA = "AbbotsLangleyTitheMap/1.0 alignment-check"


def bounds_lonlat(tif):
    ds = gdal.Open(tif)
    gt = ds.GetGeoTransform()
    nx, ny = ds.RasterXSize, ds.RasterYSize
    xs = [gt[0], gt[0] + gt[1] * nx]
    ys = [gt[3], gt[3] + gt[5] * ny]
    src = osr.SpatialReference(); src.ImportFromWkt(ds.GetProjection())
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    corners = [ct.TransformPoint(x, y)[:2] for x in xs for y in ys]
    lons = [c[0] for c in corners]; lats = [c[1] for c in corners]
    return min(lons), min(lats), max(lons), max(lats)


def deg2tile(lon, lat, z):
    n = 2 ** z
    return (int((lon + 180) / 360 * n),
            int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))


def auto_zoom(w, e):
    # pick z so the bbox is ~8 OSM tiles wide (keeps it readable and gentle on the tile server)
    for z in range(18, 8, -1):
        if (deg2tile(e, 0, z)[0] - deg2tile(w, 0, z)[0] + 1) <= 8:
            return z
    return 14


def main(tif, out, zoom):
    W, S, E, N = bounds_lonlat(tif)
    Z = zoom or auto_zoom(W, E)
    x0, y0 = deg2tile(W, N, Z)
    x1, y1 = deg2tile(E, S, Z)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    print(f"bounds lon[{W:.4f},{E:.4f}] lat[{S:.4f},{N:.4f}]  z{Z}  {nx}x{ny} tiles")

    cache = os.path.join(os.path.dirname(os.path.abspath(out)) or ".", "osm_tiles")
    os.makedirs(cache, exist_ok=True)
    osm = Image.new("RGB", (256 * nx, 256 * ny))
    for ix in range(nx):
        for iy in range(ny):
            xt, yt = x0 + ix, y0 + iy
            p = f"{cache}/{Z}_{xt}_{yt}.png"
            if not os.path.exists(p):
                req = urllib.request.Request(
                    f"https://tile.openstreetmap.org/{Z}/{xt}/{yt}.png", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r, open(p, "wb") as f:
                    f.write(r.read())
            osm.paste(Image.open(p).convert("RGB"), (256 * ix, 256 * iy))

    tilem = 2 * WORLD / 2 ** Z
    te = [-WORLD + x0 * tilem, WORLD - (y1 + 1) * tilem, -WORLD + (x1 + 1) * tilem, WORLD - y0 * tilem]
    warp = out + ".warp.tif"
    subprocess.run(["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857",
                    "-te", *map(str, te), "-ts", str(256 * nx), str(256 * ny),
                    "-dstalpha", "-r", "bilinear", tif, warp], check=True, capture_output=True)
    hist = Image.open(warp).convert("RGB")
    os.remove(warp)

    pair = Image.new("RGB", (osm.width * 2 + 10, osm.height), "white")
    pair.paste(osm, (0, 0)); pair.paste(hist, (osm.width + 10, 0))
    pair.save(out, quality=85)
    print(f"wrote {out}  (left=OSM, right=historic, same extent)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    tif = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(tif)[0] + "_check.jpg"
    zoom = int(sys.argv[3]) if len(sys.argv) > 3 else None
    main(tif, out, zoom)
