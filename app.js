// Abbots Langley tithe map viewer. Vanilla Leaflet, no build step.

const ABBOTS_LANGLEY = [51.7045, -0.4146];
const TITHE_PMTILES = "tithe.pmtiles"; // produced by the georeferencing workflow (see README)

const map = L.map("map", { center: ABBOTS_LANGLEY, zoom: 14, minZoom: 11, maxZoom: 19 });

// Bottom layer: historic tithe map (self-hosted, georeferenced). Added only if present.
const titheAttr =
  'Tithe map &copy; <a href="https://www.allhs.org.uk/">Abbots Langley Local History Society</a>';
try {
  const archive = new pmtiles.PMTiles(TITHE_PMTILES);
  // maxNativeZoom matches the pmtiles' own max zoom (see `pmtiles show tithe.pmtiles`);
  // Leaflet upscales beyond it instead of requesting tiles that don't exist.
  const tithe = pmtiles.leafletRasterLayer(archive, { attribution: titheAttr, maxNativeZoom: 17 });
  tithe.on("tileerror", () => {}); // tiles outside the parish bbox are expected to 404
  tithe.addTo(map);
} catch (e) {
  console.warn("Historic layer not loaded (tithe.pmtiles missing?):", e);
}

// Top layer: modern OpenStreetMap, opacity-controlled.
const modern = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
  opacity: 0.6,
}).addTo(map);

// --- Controls --------------------------------------------------------------
const opacity = document.getElementById("opacity");
opacity.addEventListener("input", () => modern.setOpacity(opacity.value / 100));

const toggle = document.getElementById("toggleModern");
toggle.addEventListener("change", () => {
  if (toggle.checked) modern.addTo(map);
  else modern.remove();
});

document.getElementById("panelToggle").addEventListener("click", () =>
  document.body.classList.toggle("panel-hidden")
);

// --- Plot records ----------------------------------------------------------
const results = document.getElementById("results");
const countEl = document.getElementById("count");
let plots = {};
let locations = {}; // plot number -> [lat, lng], from data/plot_points.geojson (partial coverage)
let highlight = null; // the single moving highlight marker

function acreage(p) {
  // Statute measure: acres-roods-perches.
  return `${p.acres || 0}a ${p.roods || 0}r ${p.perches || 0}p`;
}

function popupHtml(no, p) {
  return `<b>Plot ${no}</b> &mdash; ${p.name}<br>${acreage(p)} &middot; ${p.use || "?"}<br>` +
    `Owner: ${p.owner || "?"}<br>Occupier: ${p.occupier || "?"}` +
    (p.remarks ? `<br><i>${p.remarks}</i>` : "");
}

// Pan to a plot and drop a highlight, if we have a location for it.
function locate(no) {
  const ll = locations[no];
  if (!ll) return;
  map.setView(ll, 17);
  if (!highlight) {
    highlight = L.circleMarker(ll, { radius: 12, color: "#d62828", weight: 3, fillOpacity: 0.15 });
    highlight.addTo(map);
  } else {
    highlight.setLatLng(ll);
  }
  highlight.bindPopup(popupHtml(no, plots[no])).openPopup();
}

function render(filter) {
  const f = filter.trim().toLowerCase();
  const frag = document.createDocumentFragment();
  let shown = 0;
  for (const [no, p] of Object.entries(plots)) {
    const hay = `${no} ${p.owner} ${p.occupier} ${p.name} ${p.use}`.toLowerCase();
    if (f && !hay.includes(f)) continue;
    shown++;
    const li = document.createElement("li");
    const here = locations[no] ? ' <span class="pin" title="Show on map">&#128205;</span>' : "";
    if (locations[no]) {
      li.className = "locatable";
      li.dataset.no = no;
    }
    li.innerHTML =
      `<span class="no">${no}</span> <span class="name">${p.name}</span>${here}` +
      `<div class="meta">${acreage(p)} &middot; ${p.use || "?"}</div>` +
      `<div class="meta">Owner: ${p.owner || "?"}<br>Occupier: ${p.occupier || "?"}</div>` +
      (p.remarks ? `<div class="meta rem">${p.remarks}</div>` : "");
    frag.appendChild(li);
  }
  results.replaceChildren(frag);
  countEl.textContent = shown;
}

// Click a locatable result to jump to it on the map.
results.addEventListener("click", (e) => {
  const li = e.target.closest("li.locatable");
  if (li) locate(li.dataset.no);
});

fetch("data/plots.json")
  .then((r) => r.json())
  .then((data) => {
    plots = data;
    render("");
  })
  .catch((e) => {
    results.innerHTML = "<li>Could not load plot data.</li>";
    console.error(e);
  });

// Optional layer: located plot numbers (partial). Absent until the OCR step has run.
fetch("data/plot_points.geojson")
  .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
  .then((geo) => {
    for (const ft of geo.features) {
      const [lon, lat] = ft.geometry.coordinates;
      locations[ft.properties.number] = [lat, lon];
    }
    render(document.getElementById("search").value); // re-render so items become locatable
  })
  .catch(() => console.info("No plot_points.geojson yet; run scripts/ocr_plots.py"));

document.getElementById("search").addEventListener("input", (e) => render(e.target.value));
