#!/usr/bin/env bash
# Crop each georeferenced sheet to its map content using a cutline layer, to remove the white
# paper margins that cause seams where sheets overlap. Output is RGBA: both the area outside the
# cutline AND the original black (0,0,0) georeferencing collar become transparent (alpha 0), so the
# sheets composite cleanly in build_tiles.sh with no grey/black borders.
#
# Prereqs: a polygon layer (e.g. cutlines.gpkg) with an integer field `sheet` (1..7), one polygon
# per sheet tracing just inside its map border / neatline. CRS must match the sheets (EPSG:3857).
#
# Usage:  micromamba run -n abbots_langley_map scripts/crop_sheets.sh cutlines.gpkg
# Then:   micromamba run -n abbots_langley_map scripts/build_tiles.sh source_images/sheet*_crop.tif
set -euo pipefail

CUT="${1:?usage: crop_sheets.sh <cutlines.gpkg>}"

for t in source_images/IR30-15-1_*_modified.tif; do
  n=$(basename "$t" | sed -E 's/IR30-15-1_([0-9]).*/\1/')
  out="source_images/sheet${n}_crop.tif"
  echo "cropping sheet $n -> $out"
  gdalwarp -q -overwrite -cutline "$CUT" -cwhere "sheet=$n" -crop_to_cutline \
    -srcnodata "0 0 0" -dstalpha "$t" "$out"
done

echo "done. build with: scripts/build_tiles.sh source_images/sheet*_crop.tif"
