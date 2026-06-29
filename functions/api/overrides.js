// Cloudflare Pages Function backing the live edit layer.
//
//   GET  /api/overrides  -> the overrides JSON (public; the viewer merges it over the base data)
//   POST /api/overrides  -> apply one edit (Access-gated; persisted to the OVERRIDES KV namespace)
//
// Overrides shape: { "<plot no>": {lon,lat} | {deleted:true} }. A moved/added plot stores its
// new lon/lat; a removed plot stores {deleted:true}; reverting deletes the key (back to base).
//
// Auth: Cloudflare Access protects /edit.html and this route at the edge. Every request that
// cleared the gate carries a signed Cf-Access-Jwt-Assertion header, so we require it on writes as a
// defence-in-depth backstop (a request without it never came through Access).
//
// Setup (see README): create the KV namespace and bind it as OVERRIDES; add an Access application
// covering /edit.html and /api/overrides for the allowed editor email(s).

const KEY = "overrides";

export async function onRequestGet({ env }) {
  const data = (await env.OVERRIDES.get(KEY)) || "{}";
  return new Response(data, {
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export async function onRequestPost({ request, env }) {
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
  return new Response(JSON.stringify({ ok: true, count: Object.keys(ov).length }), {
    headers: { "content-type": "application/json" },
  });
}
