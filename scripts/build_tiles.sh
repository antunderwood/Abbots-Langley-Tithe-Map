#!/usr/bin/env bash
# Turn georeferenced sheet(s) into a single tithe.pmtiles for the viewer.
# Expects the RGBA cropped sheets from crop_sheets.sh (collar + outside-cutline already
# transparent). Prereqs: GDAL (gdalwarp, gdal_translate, gdaladdo) and pmtiles CLI
#   (https://github.com/protomaps/go-pmtiles).
#
# Usage: scripts/build_tiles.sh sheet1_crop.tif ... sheetN_crop.tif
set -euo pipefail

MAXZOOM=17          # ~the scans' real detail; z18 just bloats size without adding clarity
OUT=tithe.pmtiles
WORK=$(mktemp -d)

echo "Compositing $# sheet(s) into a mosaic..."
# gdalwarp respects each sheet's alpha, so transparent collars let neighbours show through (no
# grey/black borders, no holes at overlaps). Inputs without alpha mosaic fine too (just opaque).
# -tr pins the output to MAXZOOM's web-mercator resolution so the MBTiles base zoom = MAXZOOM
# (otherwise GDAL derives a finer native zoom from the scans and the pyramid bloats).
RES=$(awk "BEGIN{print 156543.03392804097/(2^$MAXZOOM)}")  # mercator metres/pixel at MAXZOOM
gdalwarp -q -overwrite -r lanczos -tr "$RES" "$RES" "$@" "$WORK/mosaic.tif"

echo "Building MBTiles (z up to $MAXZOOM)..."
# WebP keeps the alpha band (transparent collars) and compresses scanned maps far smaller than
# PNG, keeping tithe.pmtiles under static-host file-size limits (Cloudflare Pages 25 MB/file).
gdal_translate -of MBTILES -co MAXZOOM=$MAXZOOM -co TILE_FORMAT=WEBP -co QUALITY=95 \
  "$WORK/mosaic.tif" "$WORK/tithe.mbtiles"
gdaladdo -r lanczos "$WORK/tithe.mbtiles" 2 4 8 16 32
pmtiles convert "$WORK/tithe.mbtiles" "$OUT"

rm -rf "$WORK"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)). Drop it next to index.html and redeploy."
