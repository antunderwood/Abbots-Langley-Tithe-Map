// Abbots Langley tithe map viewer. Vanilla Leaflet, no build step.

const ABBOTS_LANGLEY = [51.7045, -0.4146];
const TITHE_PMTILES = "tithe.pmtiles"; // produced by the georeferencing workflow (see README)

const map = L.map("map", { center: ABBOTS_LANGLEY, zoom: 14, minZoom: 11, maxZoom: 19,
  zoomControl: false });
L.control.zoom({ position: "bottomright" }).addTo(map);

// Base layer: modern OpenStreetMap (always on).
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);

// Top layer: historic tithe map (self-hosted, georeferenced), opacity-controlled. Added if present.
const titheAttr =
  'Tithe map &copy; <a href="https://www.allhs.org.uk/">Abbots Langley Local History Society</a>';
const opacity = document.getElementById("opacity");
let tithe = null;
try {
  const archive = new pmtiles.PMTiles(TITHE_PMTILES);
  // maxNativeZoom matches the pmtiles' own max zoom; Leaflet upscales beyond it.
  tithe = pmtiles.leafletRasterLayer(archive, {
    attribution: titheAttr, maxNativeZoom: 17, opacity: opacity.value / 100,
  });
  tithe.on("tileerror", () => {}); // tiles outside the parish bbox are expected to 404
  tithe.addTo(map);
} catch (e) {
  console.warn("Historic layer not loaded (tithe.pmtiles missing?):", e);
}

// --- Controls --------------------------------------------------------------
// Blend slider drives the 1839 layer's opacity (0 = today, 100 = 1839).
opacity.addEventListener("input", () => tithe && tithe.setOpacity(opacity.value / 100));

const toggle = document.getElementById("toggleTithe");
toggle.addEventListener("change", () => {
  if (!tithe) return;
  if (toggle.checked) tithe.addTo(map);
  else tithe.remove();
});

// Mobile: floating button opens/closes the drawer.
const menuBtn = document.getElementById("menuBtn");
const closeDrawer = () => { document.body.classList.remove("drawer-open"); menuBtn.setAttribute("aria-expanded", "false"); };
menuBtn.addEventListener("click", () => {
  const open = document.body.classList.toggle("drawer-open");
  menuBtn.setAttribute("aria-expanded", String(open));
});
document.getElementById("scrim").addEventListener("click", closeDrawer);

// Dismissible preview notice, remembered so reviewers aren't nagged on every visit.
const previewNote = document.getElementById("preview-note");
if (previewNote) {
  try { if (localStorage.getItem("previewDismissed")) previewNote.classList.add("hidden"); } catch (e) {}
  document.getElementById("preview-close").addEventListener("click", () => {
    previewNote.classList.add("hidden");
    try { localStorage.setItem("previewDismissed", "1"); } catch (e) {}
  });
}

// --- Plot records ----------------------------------------------------------
const results = document.getElementById("results");
const countEl = document.getElementById("count");
let plots = {};
let locations = {}; // plot number -> [lat, lng], from data/plot_points.geojson (partial coverage)
let polygons = {};  // plot number -> GeoJSON ring [[lon,lat],...], from data/plot_polygons.geojson
let highlight = null; // the single moving point highlight
let highlightPoly = null; // the single field-fill highlight

function acreage(p) {
  // Statute measure: acres-roods-perches (see help.html: 1 acre = 4 roods, 1 rood = 40 perches).
  return `${p.acres || 0}a ${p.roods || 0}r ${p.perches || 0}p`;
}

// Expand the tithe award's land-use abbreviations for display; pass through anything unknown.
const USE_LABELS = { Ara: "Arable", Mea: "Meadow", Mead: "Meadow", Past: "Pasture", Wood: "Wood",
  Water: "Water", Road: "Road", Garden: "Garden", Arable: "Arable", Plantation: "Plantation" };
function landUse(u) { return u ? (USE_LABELS[u] || u) : ""; }

// Tithe rent-charge is recorded per holding (a group of plots), so we label it as such and hide a
// payee whose amount is zero. See help.html. rent = { v:[£,s,d], i:[£,s,d], n: plots-in-holding }.
function rentText(p) {
  const r = p.rent;
  if (!r) return "";
  const fmt = (a) => `&pound;${a[0]} ${a[1]}s ${a[2]}d`;
  const nz = (a) => !(a[0] === "0" && a[1] === "0" && a[2] === "0");
  const parts = [];
  if (nz(r.v)) parts.push(`vicar ${fmt(r.v)}`);
  if (nz(r.i)) parts.push(`impropriators ${fmt(r.i)}`);
  if (!parts.length) return "";
  const head = r.n > 1 ? `Rent-charge (holding of ${r.n} plots)` : "Rent-charge";
  return `${head}: ${parts.join("; ")}`;
}

function popupHtml(no, p) {
  const use = landUse(p.use);
  const rent = rentText(p);
  return `<b>Plot ${no}</b> &mdash; ${p.name || "?"}<br>` +
    `Landowner: ${p.owner || "?"}<br>Occupier: ${p.occupier || "?"}<br>` +
    (use ? `Land use: ${use} &middot; ` : "") + `Area: ${acreage(p)}` +
    (rent ? `<br>${rent}` : "") +
    (p.remarks ? `<br><i>${p.remarks}</i>` : "");
}

// Pan to a plot and highlight it: fill the field polygon if we have one, else a point marker.
function locate(no) {
  if (highlightPoly) { highlightPoly.remove(); highlightPoly = null; }
  if (highlight) { highlight.remove(); highlight = null; }

  const ring = polygons[no];
  if (ring) {
    const latlngs = ring.map(([lon, lat]) => [lat, lon]);
    highlightPoly = L.polygon(latlngs, { color: "#d62828", weight: 2, fillColor: "#d62828", fillOpacity: 0.3 });
    highlightPoly.addTo(map).bindPopup(popupHtml(no, plots[no]), { autoPan: false });
    map.fitBounds(highlightPoly.getBounds(), { maxZoom: 18, padding: [40, 40] });
    highlightPoly.openPopup();
    return;
  }
  const ll = locations[no];
  if (!ll) return;
  map.setView(ll, 17);
  highlight = L.circleMarker(ll, { radius: 12, color: "#d62828", weight: 3, fillOpacity: 0.15 });
  highlight.addTo(map).bindPopup(popupHtml(no, plots[no]), { autoPan: false, offset: [0, -6] }).openPopup();
}

function render(filter) {
  const f = filter.trim().toLowerCase();
  const frag = document.createDocumentFragment();
  let shown = 0;
  for (const [no, p] of Object.entries(plots)) {
    const use = landUse(p.use);
    const hay = `${no} ${p.owner} ${p.occupier} ${p.name} ${p.use} ${use}`.toLowerCase();
    if (f && !hay.includes(f)) continue;
    shown++;
    const li = document.createElement("li");
    const hasLoc = locations[no] || polygons[no];
    const here = hasLoc ? ' <span class="pin" title="Show on map">&#128205;</span>' : "";
    if (hasLoc) {
      li.className = "locatable";
      li.dataset.no = no;
    }
    li.innerHTML =
      `<span class="no">${no}</span> <span class="name">${p.name || "?"}</span>${here}` +
      `<div class="meta">${use ? `${use} &middot; ` : ""}${acreage(p)}</div>` +
      `<div class="meta">Landowner: ${p.owner || "?"}<br>Occupier: ${p.occupier || "?"}</div>` +
      (rentText(p) ? `<div class="meta">${rentText(p)}</div>` : "") +
      (p.remarks ? `<div class="meta rem">${p.remarks}</div>` : "");
    frag.appendChild(li);
  }
  results.replaceChildren(frag);
  countEl.textContent = shown;
}

// Click a locatable result to jump to it on the map.
results.addEventListener("click", (e) => {
  const li = e.target.closest("li.locatable");
  if (li) { locate(li.dataset.no); li.scrollIntoView({ block: "start", behavior: "smooth" }); closeDrawer(); }
});

const dotLayer = L.layerGroup();

// Rebuild the coverage-dot layer from the current `locations` (so it reflects live edits too).
function rebuildDots() {
  dotLayer.clearLayers();
  for (const [no, ll] of Object.entries(locations)) {
    L.circleMarker(ll, { radius: 3, color: "#37496b", weight: 1, fillOpacity: 0.7 })
      .bindTooltip(no).addTo(dotLayer);
  }
}

// Apply the live edit layer (/api/overrides) over the baked-in data: a moved/added plot takes the
// override's lon/lat (and drops its stale polygon until the next offline rebuild); a deleted plot
// is removed. This is what the password-protected editor writes; see edit.html + functions/.
function applyOverrides(overrides) {
  for (const [no, o] of Object.entries(overrides || {})) {
    if (o && o.deleted) { delete locations[no]; delete polygons[no]; }
    else if (o && typeof o.lat === "number") { locations[no] = [o.lat, o.lon]; delete polygons[no]; }
  }
}

// Load everything together so overrides merge cleanly, then render once. Points are absent until the
// OCR step has run; overrides are empty until someone edits. Polygons are intentionally not loaded
// for now: the viewer shows located points only (re-add the plot_polygons fetch to bring them back).
Promise.all([
  fetch("data/plots.json").then((r) => r.json()),
  fetch("data/plot_points.geojson").then((r) => (r.ok ? r.json() : { features: [] })).catch(() => ({ features: [] })),
  fetch("/api/overrides").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
])
  .then(([plotData, pts, overrides]) => {
    plots = plotData;
    for (const ft of pts.features) {
      const [lon, lat] = ft.geometry.coordinates;
      locations[ft.properties.number] = [lat, lon];
    }
    applyOverrides(overrides);
    rebuildDots();
    render(document.getElementById("search").value || "");
  })
  .catch((e) => {
    results.innerHTML = "<li>Could not load plot data.</li>";
    console.error(e);
  });

// Toggle: show every located plot as a dot, so coverage (and gaps) are visible at a glance.
document.getElementById("toggleDots").addEventListener("change", (e) => {
  if (e.target.checked) dotLayer.addTo(map);
  else dotLayer.remove();
});

document.getElementById("search").addEventListener("input", (e) => render(e.target.value));
