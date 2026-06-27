// Abbots Langley tithe map viewer. Vanilla Leaflet, no build step.

const ABBOTS_LANGLEY = [51.7045, -0.4146];
const TITHE_PMTILES = "tithe.pmtiles"; // produced by the georeferencing workflow (see README)

const map = L.map("map", { center: ABBOTS_LANGLEY, zoom: 14, minZoom: 11, maxZoom: 19 });

// Bottom layer: historic tithe map (self-hosted, georeferenced). Added only if present.
const titheAttr =
  'Tithe map &copy; <a href="https://www.allhs.org.uk/">Abbots Langley Local History Society</a>';
try {
  const archive = new pmtiles.PMTiles(TITHE_PMTILES);
  const tithe = pmtiles.leafletRasterLayer(archive, { attribution: titheAttr, maxNativeZoom: 19 });
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

function acreage(p) {
  // Statute measure: acres-roods-perches.
  return `${p.acres || 0}a ${p.roods || 0}r ${p.perches || 0}p`;
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
    li.innerHTML =
      `<span class="no">${no}</span> <span class="name">${p.name}</span>` +
      `<div class="meta">${acreage(p)} &middot; ${p.use || "?"}</div>` +
      `<div class="meta">Owner: ${p.owner || "?"}<br>Occupier: ${p.occupier || "?"}</div>` +
      (p.remarks ? `<div class="meta rem">${p.remarks}</div>` : "");
    frag.appendChild(li);
  }
  results.replaceChildren(frag);
  countEl.textContent = shown;
}

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

document.getElementById("search").addEventListener("input", (e) => render(e.target.value));
