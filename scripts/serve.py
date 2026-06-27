#!/usr/bin/env python3
"""Local static server WITH HTTP Range support.

PMTiles fetches tiles by byte-range; stdlib http.server ignores Range and returns the whole
file (200), which breaks the historic layer locally. This adds 206 range responses and silences
the harmless broken-pipe noise from browsers cancelling fetches. Production (Cloudflare Pages)
supports ranges natively, so this is only needed for local testing.

Usage: python3 scripts/serve.py [port]   # default 8000
"""
import http.server
import os
import re
import sys


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    _send_len = None  # bytes still to send for a range response; None = send whole file

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
