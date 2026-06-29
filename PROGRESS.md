# Progress / pick-up-later notes

_Last updated: 2026-06-28_

## Where things stand

Phase 1 (viewer) and most of Phase 2/3 (OCR points + watershed polygons) are built and working
locally. The site is NOT yet deployed and the source assets are NOT yet cleared for public hosting.

- **Viewer**: `index.html` + `app.js` + `style.css`. Material redesign done: OSM is the base layer
  (always on), tithe map is the top overlay, the blend slider controls **tithe** opacity (default 85),
  switches for "Show 1839 map" and "Show located plots", searchable plot list.
- **Tithe tiles**: `tithe.pmtiles` (~12 MB, WebP, z17 cap so it stays under Cloudflare's 25 MB/file
  limit). Built from 7 QGIS-georeferenced sheets. Grey/black collar problem is fixed (transparency
  moved into the crop step).
- **Plot data**: `data/plots.json` (1075 plots from the tithe award `.xls`).
- **OCR (Phase 2)**: `scripts/ocr_plots.py` now does multi-rotation OCR (angles 0, +/-3, +/-6, +/-10)
  which recovered more field-angled numbers. Writes `data/plot_points.geojson`.
- **Polygons (Phase 3)**: `scripts/extract_polygons.py` (seed-controlled watershed) writes both
  `data/plot_points.geojson` and `data/plot_polygons.geojson`.

## Review app state (the active task)

A human-in-the-loop review app confirms/corrects uncertain OCR guesses and lets you add missed plots
on the map. Run it with:

```sh
micromamba run -n abbots_langley_map python scripts/review_server.py   # serves on :8001
# then open http://localhost:8001/review.html
```

Current counts in `data/review/`:
- `confirmed.json`: **654** auto-accepted + reviewed seeds (your prior review is preserved)
- `candidates.json`: **83** uncertain candidates still queued for a second review pass

### Next action when you pick this up
1. Open the review app (above), work through the **83** queued candidates
   (Enter = confirm, edit number then Enter = correct, Esc = not a plot, Skip = defer).
2. On the **Add on map** tab, drop in genuine misses that OCR never found (e.g. **313, 314** are
   confirmed-missing; 315 was recovered).
3. Rebuild points + polygons from the confirmed seeds:
   ```sh
   micromamba run -n abbots_langley_map python scripts/extract_polygons.py
   ```
4. Reload the main viewer to see the improvement.

## Still outstanding (deferred, need your go-ahead)

- **Commit** everything. Currently uncommitted (see `git status`): the Phase 3 scripts
  (`extract_polygons.py`, `prepare_review.py`, `review_server.py`), `review.html`, the rotation
  change to `ocr_plots.py`, the Material redesign (`index.html`/`app.js`/`style.css`),
  `data/review/confirmed.json`, and the regenerated geojson.
  - Commit `confirmed.json` (your work); git-ignore the regenerable bits:
    `data/review/{candidates.json,sheets.json,crops/,confirmed.backup.json}` and
    `scripts/__pycache__/`.
- **Cloudflare Pages deploy** (repeatedly deferred). Single `tithe.pmtiles` file sidesteps file-count
  limits; needs a range-capable host (Cloudflare Pages is fine).
- **ALLHS copyright permission** before any public launch. Map scans + spreadsheet are
  (c) Abbots Langley Local History Society. This is a hard blocker for going public; ask them first
  (they may even provide higher-res source scans).

## Notes / gotchas

- PMTiles needs HTTP range requests. The stdlib `http.server` does NOT support them; use
  `scripts/serve.py` (viewer, :8000) and `scripts/review_server.py` (review, :8001), both range-capable.
- `prepare_review.py` preserves existing `confirmed.json`, so re-running it with better OCR will not
  wipe your reviews. Still safe to keep `data/review/confirmed.backup.json` around.
- `tithe.pmtiles` zoom is pinned via `gdalwarp -tr` (z17 mercator resolution) in `build_tiles.sh`;
  the `MAXZOOM` co only sets metadata, so don't rely on it alone or the file balloons past 25 MB.
