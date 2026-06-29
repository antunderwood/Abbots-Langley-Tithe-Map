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

### Review and correct (confirmation app)

OCR mislocates short (1-2 digit) numbers, so reads are split into auto-accepted and to-review:

```sh
micromamba run -n abbots_langley_map python scripts/prepare_review.py   # classify + crop
python3 scripts/review_server.py 8001                                   # then open http://localhost:8001/review.html
```

`prepare_review.py` auto-accepts confident 3+ digit matches and queues the rest (short, low
confidence) with a cropped thumbnail. The review app has two tabs:
- **Review queue:** each uncertain label shows its crop, the OCR guess (editable), and its record.
  Enter confirms, edit-then-Enter corrects, Esc skips a non-plot. Saves to `confirmed.json` as you go.
- **Add on map:** click a field that has no seed and type its number, to recover plots OCR missed.

Then rebuild points + polygons from the confirmed seeds:

```sh
micromamba run -n abbots_langley_map python scripts/extract_polygons.py
```

### Fill the gaps by hand in QGIS

1. Load `data/plot_points.geojson` and your georeferenced sheets in QGIS.
2. Open `data/plots_missing.txt` for the list of numbers still needing a point.
3. Toggle editing on the geojson layer, use **Add Point Feature**, click each missing number on
   the historic map, and type its value in the `number` field.
4. Save edits. The viewer reads the same file, so just redeploy.

(Tip: to also correct a misplaced pin, use the Vertex Tool to drag it onto the right plot.)

## Plot field polygons (search fills the field)

Each plot number sits inside its field, so `extract_polygons.py` seeds a **watershed** with the
located points: it grows one bounded region per seed, which splits adjacent fields (e.g. 62 vs 69)
and gives every seed a polygon. It writes **both** `plot_points.geojson` and `plot_polygons.geojson`
from the same seeds, using `data/review/confirmed.json` when present (post-review) or OCR otherwise.

```sh
micromamba run -n abbots_langley_map python scripts/extract_polygons.py    # all sheets
```

A wrong seed still gives a wrong field, so the review app above is what fixes mislocated numbers.
Oversized regions (sparse seeds) are skipped as polygons. Tidy shapes by hand in QGIS if needed,
both files are editable GeoJSON with a `number` field; the viewer reads them directly.

## Editing plot positions (password-protected, live)

Misplaced plots can be corrected on the deployed site through a gated editor, without redeploying.

- **`edit.html`** is the editor: click a plot to select it, drag the marker to the right spot, Save.
  It can also Add, Delete, and Revert plots. Each change is saved instantly.
- **`worker.js`** is a Cloudflare Worker (Static Assets model): it serves the site and handles
  `GET /api/overrides` (returns the edit layer; the viewer merges it over the baked-in data on load)
  and `POST /api/overrides` (applies one edit, persisted to the **OVERRIDES** KV namespace).
- The viewer (`app.js`) merges overrides live: a moved/added plot uses the new position (its polygon
  drops until the next offline rebuild), a deleted plot disappears.

### Cloudflare setup (one-time)

1. Create the KV namespace and paste its id into `wrangler.toml`:
   `npx wrangler kv namespace create OVERRIDES` (or create it in the dashboard).
2. Deploy via git: connect the repo as a Worker (Deploy command `npx wrangler deploy`), or run
   `npx wrangler deploy` locally.
3. Disable the public `*.workers.dev` route (Worker -> Settings -> Domains & Routes), attach your
   subdomain, and add a **Cloudflare Access** application over the whole site (or just `/edit.html`
   + `/api/overrides` if the map is meant to be public). Access is the password protection; the
   Worker also rejects any write that did not arrive through Access.

### Local editing (no Cloudflare)

`scripts/serve.py` implements the same `/api/overrides` endpoint against
`data/review/overrides.json` (no auth locally). Run it and open `http://localhost:8000/edit.html`.

### Folding edits back into the polygons

Live edits move points only. To refresh polygons from accumulated edits:

```sh
npx wrangler kv key get --binding=OVERRIDES overrides > data/review/overrides.json   # prod only
micromamba run -n abbots_langley_map python scripts/apply_overrides.py               # bake into confirmed.json
micromamba run -n abbots_langley_map python scripts/extract_polygons.py              # rebuild polygons
```

## Roadmap

- **Phase 1 (done):** viewer + overlay + opacity + searchable records.
- **Phase 2 (done):** clickable/searchable point per plot via OCR + manual fill.
- **Phase 3 (done, partial):** reconstructed field polygons via boundary extraction + seed join;
  search fills the field. Manual cleanup in QGIS for merged/missed fields.
- **Editing (done):** password-protected live editor (Cloudflare Access + Pages Function + KV).
