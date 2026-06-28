# Abbots Langley Tithe Map Overlay

A static website that overlays a modern map on the c.1839 tithe map of Abbots Langley
(Hertfordshire), with a layer toggle and an opacity slider so the modern map can be faded
to reveal the historic one. A searchable side panel lists the 1,075 tithe-award plot records.

- Modern basemap: OpenStreetMap
- Historic layer: a self-hosted, georeferenced copy of the tithe map as a single `tithe.pmtiles`
- Plot data: `data/plots.json`, generated from the ALLHS tithe-award spreadsheet

## Permissions (do before publishing)

The map scans and the spreadsheet are © **Abbots Langley Local History Society** (ALLHS).
Get their permission/licence before hosting publicly. Ask them too for high-resolution
source scans: it makes both georeferencing and any future plot digitisation far easier.

## Run locally

```sh
python3 scripts/serve.py 8000   # then open http://localhost:8000
```

Use `scripts/serve.py`, not `python3 -m http.server`: PMTiles fetches tiles by HTTP byte-range,
which the stdlib server doesn't support (the historic layer fails and the console floods with
broken-pipe errors). Cloudflare Pages supports ranges natively in production.

The viewer works without `tithe.pmtiles` (you just see OSM); add the historic layer once you
have georeferenced the scans.

## Setup (Python tooling)

The scripts run in the `abbots_langley_map` micromamba env (needs `pillow`, `xlrd`, `opencv`):

```sh
micromamba create -n abbots_langley_map -c conda-forge python pillow xlrd opencv
```

Prefix script commands with `micromamba run -n abbots_langley_map`.

## Regenerate plot data

```sh
micromamba run -n abbots_langley_map python scripts/xls_to_json.py \
  AbbotsLangleyTitheAward_corrected_20260622.xls data/plots.json
```

Running `xls_to_json.py` with no args runs a self-check (expects `award.xls` at repo root).

## Build the historic layer (georeferencing)

The scans live on eforms.org.uk as 7 Zoomify tilesets (`IR30-15-1_1..7_Abbotts_Langley_Herts`),
in pixel space. The map is one rotated 1839 parish plan scanned in 7 non-overlapping sheets;
each sheet is warped to real-world coordinates separately (per-sheet is most accurate, and the
sheets don't overlap so they can't be auto-mosaicked).

1. **Get the images (done by the downloader):**
   ```sh
   micromamba run -n abbots_langley_map python scripts/zoomify_download.py
   ```
   Downloads + stitches all 7 areas to `source_images/IR30-15-1_<n>_Abbotts_Langley_Herts.jpg`.
   Pass area numbers to limit (e.g. `... zoomify_download.py 1 2 3 4`).
2. **Georeference each populated sheet** in [QGIS Georeferencer](https://docs.qgis.org/latest/en/docs/user_manual/working_with_raster/georeferencer.html):
   place control points against an OSM/aerial basemap (church, canal locks, road junctions are
   good anchors), warp to **EPSG:3857**, export GeoTIFF.
   - The populated parish is in sheets **1, 2, 3, 4 and the lower part of 5**. Sheets **6 and 7**
     are mostly blank margin (title cartouche, parish-boundary edge) so are low priority.
   - Tip: give each GeoTIFF an alpha/nodata band (or crop the white paper margins) so a sheet's
     blank border doesn't paint over its neighbour in the mosaic.
   - **Check each sheet's alignment** before moving on (OSM vs your warped sheet, same extent):
     ```sh
     micromamba run -n abbots_langley_map python scripts/align_check.py source_images/<sheet>_modified.tif
     ```
     Opens as `<sheet>_check.jpg`. Trace the canal or a main road across both panels; if it
     tracks, the fit is good. If a corner drifts, add a control point there and re-export.
3. **Pack to PMTiles** (lists the GeoTIFFs you produced; later files win in any overlap).
   Run inside the env so GDAL is on PATH (`pmtiles` comes from `brew install pmtiles`):
   ```sh
   micromamba run -n abbots_langley_map scripts/build_tiles.sh sheet1.tif ... sheetN.tif
   ```
   Produces `tithe.pmtiles`. Drop it next to `index.html`.

### Alternative: Allmaps (no tile hosting)

If you serve the scans as IIIF, [Allmaps](https://allmaps.org/) georeferences in-browser and
renders warped tiles from a tiny annotation, so you host no tiles at all. Trade-off: needs a
IIIF source (the current source is Zoomify), and the viewer would use the Allmaps plugin
instead of PMTiles. Kept as a fallback.

## Deploy (free, moderate traffic)

**Cloudflare Pages** is the recommended host: unlimited static bandwidth, and the single
`tithe.pmtiles` (served via HTTP range requests) avoids per-file limits.

1. Push this repo to GitHub.
2. Cloudflare Pages -> Create project -> connect the repo. Build command: none. Output dir: `/`.
3. Confirm the deployed site serves `tithe.pmtiles` with HTTP range support (Cloudflare does).

GitHub Pages works too, but watch the 1 GB repo soft-limit if `tithe.pmtiles` is large.

## Plot locations (search highlight)

Searching a plot can pan to it and drop a highlight, for plots whose number we've located on the
map. Locations live in `data/plot_points.geojson` (point per plot, WGS84). The viewer loads it if
present; absent, search still works without map pins.

### Generate locations by OCR

```sh
micromamba run -n abbots_langley_map python scripts/ocr_plots.py        # all sheets
```

Runs digit OCR (several preprocessing passes) on each original scan, keeps only reads that match a
known plot number, and converts pixel positions to lon/lat via each sheet's `.points` GCPs. Writes
`data/plot_points.geojson` and `data/plots_missing.txt` (numbers not auto-located). Coverage is
partial (faint/tiny numbers are missed); a few pins may be misplaced where a digit was misread.

### Fill the gaps by hand in QGIS

1. Load `data/plot_points.geojson` and your georeferenced sheets in QGIS.
2. Open `data/plots_missing.txt` for the list of numbers still needing a point.
3. Toggle editing on the geojson layer, use **Add Point Feature**, click each missing number on
   the historic map, and type its value in the `number` field.
4. Save edits. The viewer reads the same file, so just redeploy.

(Tip: to also correct a misplaced pin, use the Vertex Tool to drag it onto the right plot.)

## Roadmap

- **Phase 1 (done):** viewer + overlay + opacity + searchable records.
- **Phase 2 (done):** clickable/searchable point per plot via OCR + manual fill (above).
- **Phase 3 (R&D):** automatic polygonisation of plot boundaries, spatial-joined to the points.
  Semi-automatic with manual cleanup; not turnkey.
