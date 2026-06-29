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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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
