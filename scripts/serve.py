#!/usr/bin/env python3
"""Local static server WITH HTTP Range support.

PMTiles fetches tiles by byte-range; stdlib http.server ignores Range and returns the whole
file (200), which breaks the historic layer locally. This adds 206 range responses and silences
the harmless broken-pipe noise from browsers cancelling fetches. Production (Cloudflare Pages)
supports ranges natively, so this is only needed for local testing.

Usage: python3 scripts/serve.py [port]   # default 8000
"""
import http.server
import json
import os
import re
import sys

# Local stand-in for the Cloudflare KV-backed /api/overrides Function (functions/api/overrides.js),
# so the editor and viewer work offline in dev. No auth locally; Cloudflare Access guards production.
OVERRIDES = "data/review/overrides.json"


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    _send_len = None  # bytes still to send for a range response; None = send whole file

    def do_GET(self):
        if self.path.split("?")[0] == "/api/overrides":
            body = open(OVERRIDES, "rb").read() if os.path.exists(OVERRIDES) else b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/overrides":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            edit = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_error(400)
            return
        no = str(edit.get("number", "")).strip()
        if not no:
            self.send_error(400)
            return
        ov = json.load(open(OVERRIDES)) if os.path.exists(OVERRIDES) else {}
        if edit.get("deleted"):
            ov[no] = {"deleted": True}
        elif isinstance(edit.get("lat"), (int, float)) and isinstance(edit.get("lon"), (int, float)):
            ov[no] = {"lon": edit["lon"], "lat": edit["lat"]}
        elif edit.get("revert"):
            ov.pop(no, None)
        else:
            self.send_error(400)
            return
        os.makedirs(os.path.dirname(OVERRIDES), exist_ok=True)
        json.dump(ov, open(OVERRIDES, "w"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "count": len(ov)}).encode())

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return None
        size = os.fstat(f.fileno()).st_size
        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        if not m:
            f.close()
            self.send_error(400)
            return None
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            f.close()
            self.send_error(416)
            return None
        self._send_len = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._send_len))
        self.end_headers()
        f.seek(start)
        return f

    def copyfile(self, source, outputfile):
        try:
            if self._send_len is None:
                return super().copyfile(source, outputfile)
            remaining = self._send_len
            while remaining > 0:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser cancelled the fetch; normal for tile/range requests


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    http.server.ThreadingHTTPServer(("", port), RangeHandler).serve_forever()
