#!/usr/bin/env python3
"""Local server for the plot-review app: static files (with HTTP range, for PMTiles) + a save endpoint.

Serves the repo so review.html can load data/review/*.json and tithe.pmtiles, and accepts
POST /review/save with the full confirmed-seeds object, which it writes to data/review/confirmed.json.
Client-driven: the page holds the working set and saves the whole thing after each decision.

Usage: python3 scripts/review_server.py [port]   # default 8001, open http://localhost:8001/review.html
Then rebuild: micromamba run -n abbots_langley_map python scripts/extract_polygons.py
"""
import json
import os
import re
import sys

import http.server

CONFIRMED = "data/review/confirmed.json"


class Handler(http.server.SimpleHTTPRequestHandler):
    _send_len = None

    def do_POST(self):
        if self.path != "/review/save":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_error(400)
            return
        os.makedirs(os.path.dirname(CONFIRMED), exist_ok=True)
        with open(CONFIRMED, "w") as f:
            json.dump(data, f)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    # --- range support so the PMTiles overlay works in the add-on-map view ---
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
            return super().send_head()
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
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
            left = self._send_len
            while left > 0:
                chunk = source.read(min(65536, left))
                if not chunk:
                    break
                outputfile.write(chunk)
                left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    http.server.ThreadingHTTPServer(("", port), Handler).serve_forever()
