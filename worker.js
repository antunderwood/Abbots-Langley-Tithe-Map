// Cloudflare Worker entry (Workers Static Assets model).
//
// Serves the static site through the ASSETS binding and handles the live edit API at
// /api/overrides, backed by the OVERRIDES KV namespace. Cloudflare Access gates the whole site;
// we still require the Access JWT on writes as a defence-in-depth backstop (a request without it
// never came through Access).
//
// Overrides shape: { "<plot no>": {lon,lat} | {deleted:true} }. The viewer (app.js) merges this
// over the baked-in data; edit.html writes to it. scripts/apply_overrides.py bakes it back into
// confirmed.json for the offline polygon rebuild.

const KEY = "overrides";

function json(body) {
  return new Response(body, {
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

// Workers Static Assets returns 200 (the whole file) for a Range request, but PMTiles needs real
// 206 partial responses to read tithe.pmtiles. So we serve .pmtiles ourselves: fetch the full asset
// once per isolate and slice the requested byte range. 12 MB in memory is well within limits.
const _assetCache = {};
async function fullAsset(env, url) {
  if (!_assetCache[url.pathname]) {
    const r = await env.ASSETS.fetch(new Request(url.origin + url.pathname));
    _assetCache[url.pathname] = await r.arrayBuffer();
  }
  return _assetCache[url.pathname];
}

async function servePmtiles(request, env, url) {
  const buf = await fullAsset(env, url);
  const size = buf.byteLength;
  const base = { "content-type": "application/octet-stream", "accept-ranges": "bytes",
                 "cache-control": "public, max-age=86400" };
  const range = request.headers.get("Range");
  const m = range && /bytes=(\d+)-(\d*)/.exec(range);
  if (!m) {
    return new Response(buf, { headers: { ...base, "content-length": String(size) } });
  }
  const start = Number(m[1]);
  const end = m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
  if (start > end || start >= size) {
    return new Response("Range Not Satisfiable", { status: 416, headers: { "content-range": `bytes */${size}` } });
  }
  const slice = buf.slice(start, end + 1);
  return new Response(slice, {
    status: 206,
    headers: { ...base, "content-range": `bytes ${start}-${end}/${size}`, "content-length": String(slice.byteLength) },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.endsWith(".pmtiles")) {
      return servePmtiles(request, env, url);
    }
    if (url.pathname !== "/api/overrides") {
      return env.ASSETS.fetch(request); // static site
    }

    if (request.method === "GET") {
      return json((await env.OVERRIDES.get(KEY)) || "{}");
    }
    if (request.method === "POST") {
      if (!request.headers.get("Cf-Access-Jwt-Assertion")) {
        return new Response("Unauthorized (must go through Cloudflare Access)", { status: 401 });
      }
      let edit;
      try {
        edit = await request.json();
      } catch {
        return new Response("Bad JSON", { status: 400 });
      }
      const no = String(edit.number || "").trim();
      if (!no) return new Response("Missing plot number", { status: 400 });

      const ov = JSON.parse((await env.OVERRIDES.get(KEY)) || "{}");
      if (edit.deleted) {
        ov[no] = { deleted: true };
      } else if (typeof edit.lat === "number" && typeof edit.lon === "number") {
        ov[no] = { lon: edit.lon, lat: edit.lat };
      } else if (edit.revert) {
        delete ov[no];
      } else {
        return new Response("Edit must set lon/lat, deleted, or revert", { status: 400 });
      }
      await env.OVERRIDES.put(KEY, JSON.stringify(ov));
      return json(JSON.stringify({ ok: true, count: Object.keys(ov).length }));
    }
    return new Response("Method not allowed", { status: 405 });
  },
};
