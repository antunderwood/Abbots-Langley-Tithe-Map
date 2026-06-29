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
let highlight = null; // the single moving point highlight
let lastLocated = null; // plot number most recently clicked, for restoring scroll on search clear

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

// Pan to a plot and highlight it with a point marker.
function locate(no, zoom = 17) {
  if (highlight) { highlight.remove(); highlight = null; }
  const ll = locations[no];
  if (!ll) return;
  map.setView(ll, zoom);
  highlight = L.circleMarker(ll, { radius: 12, color: "#d62828", weight: 3, fillOpacity: 0.15 });
  highlight.addTo(map).bindPopup(popupHtml(no, plots[no]), { autoPan: false, offset: [0, -6] }).openPopup();
}

function naturalKey(k) { return k.replace(/(\d+)/g, (n) => n.padStart(8, "0")); }

function render(filter) {
  const f = filter.trim().toLowerCase();
  const frag = document.createDocumentFragment();
  let shown = 0;
  const sorted = Object.entries(plots).sort((a, b) => naturalKey(a[0]).localeCompare(naturalKey(b[0])));
  for (const [no, p] of sorted) {
    const use = landUse(p.use);
    const hay = `${no} ${p.owner} ${p.occupier} ${p.name} ${p.use} ${use}`.toLowerCase();
    if (f && !hay.includes(f)) continue;
    shown++;
    const li = document.createElement("li");
    const hasLoc = !!locations[no];
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
  if (li) { lastLocated = li.dataset.no; locate(li.dataset.no); li.scrollIntoView({ block: "start", behavior: "smooth" }); closeDrawer(); }
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
    if (o && o.deleted) { delete locations[no]; }
    else if (o && typeof o.lat === "number") { locations[no] = [o.lat, o.lon]; }
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

// Re-fetch overrides when returning to this tab, so edits made in edit.html appear without a
// full page reload (important for newly added suffix plots that only exist in overrides).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  fetch("/api/overrides").then((r) => r.ok ? r.json() : {}).catch(() => ({})).then((overrides) => {
    applyOverrides(overrides);
    rebuildDots();
    render(document.getElementById("search").value || "");
  });
});

// Toggle: show every located plot as a dot, so coverage (and gaps) are visible at a glance.
document.getElementById("toggleDots").addEventListener("change", (e) => {
  if (e.target.checked) dotLayer.addTo(map);
  else dotLayer.remove();
});

// Click the map to highlight the nearest located plot within 20 px.
map.on("click", (e) => {
  const click = map.latLngToContainerPoint(e.latlng);
  let best = null, bestDist = 20;
  for (const [no, ll] of Object.entries(locations)) {
    const pt = map.latLngToContainerPoint(ll);
    const d = Math.hypot(click.x - pt.x, click.y - pt.y);
    if (d < bestDist) { bestDist = d; best = no; }
  }
  if (best) locate(best, map.getZoom());
});

document.getElementById("search").addEventListener("input", (e) => {
  render(e.target.value);
  if (e.target.value === "" && lastLocated) {
    const el = document.querySelector(`#results li[data-no="${lastLocated}"]`);
    if (el) el.scrollIntoView({ block: "start" });
  }
});
