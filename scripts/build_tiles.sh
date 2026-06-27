#!/usr/bin/env bash
# Turn georeferenced GeoTIFF(s) into a single tithe.pmtiles for the viewer.
# Prereqs: GDAL (gdalbuildvrt, gdal_translate, gdaladdo) and pmtiles CLI
#   (https://github.com/protomaps/go-pmtiles).
# Run AFTER georeferencing each sheet to EPSG:3857 (see README).
#
# Usage: scripts/build_tiles.sh sheet1.tif sheet2.tif ... sheet7.tif
set -euo pipefail

MAXZOOM=19          # cap to keep size sane; raise only if the scans support it
OUT=tithe.pmtiles
WORK=$(mktemp -d)

echo "Merging $# sheet(s) into a mosaic..."
gdalbuildvrt "$WORK/mosaic.vrt" "$@"

echo "Building MBTiles (z up to $MAXZOOM)..."
gdal_translate -of MBTILES -co MAXZOOM=$MAXZOOM "$WORK/mosaic.vrt" "$WORK/tithe.mbtiles"
gdaladdo "$WORK/tithe.mbtiles" 2 4 8 16 32
pmtiles convert "$WORK/tithe.mbtiles" "$OUT"

rm -rf "$WORK"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)). Drop it next to index.html and redeploy."
