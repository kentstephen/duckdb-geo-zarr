# Static server with CORS + HTTP Range support (duckdb-wasm httpfs does range GETs).
import os, re, sys, urllib.request, urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
# /arco/<key> proxies to the public ARCO ERA5 bucket, which sends no CORS headers.
ARCO = "https://storage.googleapis.com/gcp-public-data-arco-era5/"
class H(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")
        self.send_header("Accept-Ranges", "bytes")
        # Proxied chunks are immutable; let the browser cache them so a second pass over a
        # window is local. Local files (the extension, pages) stay uncached.
        self.send_header("Cache-Control", "public, max-age=86400" if self.path.startswith("/arco/") else "no-store")
        super().end_headers()
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS"); self.end_headers()
    def proxy(self, upstream):
        req = urllib.request.Request(upstream)
        rng = self.headers.get("Range")
        if rng: req.add_header("Range", rng)
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            resp = e
        body = resp.read()
        self.send_response(resp.status)
        for h in ("Content-Type", "Content-Range", "Content-Length", "Last-Modified", "ETag"):
            v = resp.headers.get(h)
            if v: self.send_header(h, v)
        if not resp.headers.get("Content-Length"): self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_HEAD(self):
        if self.path.startswith("/arco/"):
            return self.proxy(ARCO + self.path[len("/arco/"):])
        return super().do_HEAD()
    def do_GET(self):
        if self.path.startswith("/arco/"):
            return self.proxy(ARCO + self.path[len("/arco/"):])
        path = self.translate_path(self.path)
        rng = self.headers.get("Range")
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        a = int(m.group(1)) if m.group(1) else None
        b = int(m.group(2)) if m.group(2) else None
        if a is None: a, b = max(0, size - b), size - 1
        elif b is None or b >= size: b = size - 1
        if a > b or a >= size:
            self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Content-Length", str(b - a + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(a); self.wfile.write(f.read(b - a + 1))
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path)); sys.stderr.flush()
if __name__ == "__main__":
    os.chdir(sys.argv[1]); ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
