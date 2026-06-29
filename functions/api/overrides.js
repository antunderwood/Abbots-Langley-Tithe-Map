// Cloudflare Pages Function: /api/overrides
// Backed by the OVERRIDES KV namespace (bind it in Pages > Settings > Functions > KV bindings).
// Reads return the full overrides object; writes merge a single plot edit.
// EDIT_KEY env var (Pages > Settings > Environment variables) gates writes when set.

const KEY = "overrides";

function json(body, status = 200) {
  return new Response(body, {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export async function onRequest({ request, env }) {
  if (request.method === "GET") {
    return json((await env.OVERRIDES.get(KEY)) || "{}");
  }

  if (request.method === "POST") {
    if (env.EDIT_KEY && request.headers.get("X-Edit-Key") !== env.EDIT_KEY) {
      return json(JSON.stringify({ error: "Unauthorized" }), 401);
    }
    let edit;
    try {
      edit = await request.json();
    } catch {
      return json(JSON.stringify({ error: "Bad JSON" }), 400);
    }
    const no = String(edit.number || "").trim();
    if (!no) return json(JSON.stringify({ error: "Missing plot number" }), 400);

    const ov = JSON.parse((await env.OVERRIDES.get(KEY)) || "{}");
    if (edit.deleted) {
      ov[no] = { deleted: true };
    } else if (typeof edit.lat === "number" && typeof edit.lon === "number") {
      ov[no] = { lon: edit.lon, lat: edit.lat };
    } else if (edit.revert) {
      delete ov[no];
    } else {
      return json(JSON.stringify({ error: "Edit must set lon/lat, deleted, or revert" }), 400);
    }
    await env.OVERRIDES.put(KEY, JSON.stringify(ov));
    return json(JSON.stringify({ ok: true, count: Object.keys(ov).length }));
  }

  return json(JSON.stringify({ error: "Method not allowed" }), 405);
}
