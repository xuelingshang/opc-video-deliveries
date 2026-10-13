#!/usr/bin/env python3
"""Local stand-in for the three GitHub endpoints the friend tool uses (for offline tests only).

  /api/repos/OWNER/REPO/releases?per_page=&page=   release list (releases.json)
  /web/OWNER/REPO/releases/download/TAG/ASSET      302 redirect, like github.com
  /cdn/TAG/ASSET                                   file body with HTTP Range support

Control files in the served directory:
  api_down        present -> the API answers 403 (rate limit), forcing the tool's fallback
  throttle        contains bytes/second for /cdn responses
"""
import http.server, json, os, re, sys, time, urllib.parse

ROOT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else ".")


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        with open(os.path.join(ROOT, "access.log"), "a") as f:
            f.write("%s %s\n" % (self.command, self.path) + ("  range=%s\n" % self.headers.get("Range") if self.headers.get("Range") else ""))

    def send(self, code, body=b"", ctype="application/json", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        m = re.match(r"^/api/repos/[^/]+/[^/]+/releases$", u.path)
        if m:
            if os.path.exists(os.path.join(ROOT, "api_down")):
                return self.send(403, b'{"message":"API rate limit exceeded"}')
            rel = json.load(open(os.path.join(ROOT, "releases.json")))
            per, page = int(q.get("per_page", ["30"])[0]), int(q.get("page", ["1"])[0])
            return self.send(200, json.dumps(rel[(page - 1) * per: page * per]).encode())
        m = re.match(r"^/web/[^/]+/[^/]+/releases/download/([^/]+)/([^/]+)$", u.path)
        if m:
            tag, asset = m.groups()
            rel = json.load(open(os.path.join(ROOT, "releases.json")))
            pub = any(r["tag_name"] == tag and not r["draft"] for r in rel)
            if pub and os.path.exists(os.path.join(ROOT, "assets", tag, asset)):
                return self.send(302, b"", extra=[("Location", f"/cdn/{tag}/{asset}")])
            return self.send(404, b"Not Found", "text/plain")
        m = re.match(r"^/cdn/([^/]+)/([^/]+)$", u.path)
        if m:
            path = os.path.join(ROOT, "assets", *m.groups())
            size = os.path.getsize(path)
            start, code = 0, 200
            rng = self.headers.get("Range")
            if rng:
                start = int(re.match(r"bytes=(\d+)-", rng).group(1))
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size - start))
            self.send_header("Accept-Ranges", "bytes")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
            self.end_headers()
            tp = os.path.join(ROOT, "throttle")
            rate = int(open(tp).read()) if os.path.exists(tp) else 0
            with open(path, "rb") as f:
                f.seek(start)
                chunk = 65536
                for b in iter(lambda: f.read(chunk), b""):
                    try:
                        self.wfile.write(b)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    if rate:
                        time.sleep(len(b) / rate)
            return
        self.send(404, b"Not Found", "text/plain")


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
