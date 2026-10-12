#!/usr/bin/env python3
"""
TripMap helper: serves your trip map on this computer only (http://127.0.0.1)
and lets the map's edit mode save fixes and re-run the builder with buttons.

Start it by double-clicking "Open TripMap.bat", or:
    python serve.py "D:\\2026_ Thailand Trip"

Close the window to stop it. Nothing is reachable from other devices.
"""
import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_NAME = "_tripmap"
for ext, typ in {".js": "text/javascript", ".mp4": "video/mp4", ".json": "application/json",
                 ".jpg": "image/jpeg", ".html": "text/html", ".css": "text/css"}.items():
    mimetypes.add_type(typ, ext)


class Build:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.mode = None
        self.exit = None
        self.log = deque(maxlen=200)
        self.remote = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, root, out, mode):
        with self.lock:
            if self.running:
                return False
            args_file = out / "build_args.json"
            try:
                saved = json.loads(args_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = [str(root), "--name", root.name]
            if mode == "publish":
                cmd = [sys.executable, "-u", str(HERE / "publish.py"), str(root)]
                if self.remote:
                    cmd += ["--remote", self.remote]
            else:
                cmd = [sys.executable, "-u", str(HERE / "build.py"), *saved]
                if mode == "data":
                    cmd.append("--data-only")
            self.log.clear()
            self.log.append({"data": "$ apply fixes", "full": "$ scan for new files", "publish": "$ publish"}[mode])
            self.mode, self.exit = mode, None
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
            threading.Thread(target=self._pump, daemon=True).start()
            return True

    def _pump(self):
        p = self.proc
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.log.append(line)
                print("  [build]", line, flush=True)
        self.exit = p.wait()


def make_handler(root: Path, out: Path, build: Build, port_ref):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "TripMap"

        def log_message(self, fmt, *a):  # keep the console readable
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Accept-Ranges", "bytes")
            super().end_headers()

        # ---------- helpers
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _text(self, msg, code):
            body = msg.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _trusted(self):
            # Custom header forces a CORS preflight, which we never approve, so other
            # websites can't drive this API. Also reject foreign Origins outright.
            if self.headers.get("X-TripMap") != "1":
                return False
            origin = self.headers.get("Origin")
            ok = {f"http://127.0.0.1:{port_ref[0]}", f"http://localhost:{port_ref[0]}"}
            return origin is None or origin in ok

        # ---------- routes
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/"):
                if not self._trusted():
                    return self._text("forbidden", 403)
                if path == "/api/status":
                    return self._json({"ok": True, "building": build.running, "mode": build.mode,
                                       "exit": build.exit, "log": list(build.log)[-15:]})
                if path == "/api/overrides":
                    f = root / "overrides.json"
                    try:
                        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"overrides": {}}
                    except ValueError:
                        data = {"overrides": {}, "error": "overrides.json is not valid JSON"}
                    return self._json(data)
                return self._text("not found", 404)
            if "Range" in self.headers:
                return self._range()
            return super().do_GET()

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not self._trusted():
                return self._text("forbidden", 403)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._text("bad json", 400)
            if path == "/api/overrides":
                ov = body.get("overrides")
                if not isinstance(ov, dict):
                    return self._text("expected {overrides: {...}}", 400)
                f = root / "overrides.json"
                if f.exists():
                    try:
                        (root / "overrides.bak.json").write_bytes(f.read_bytes())
                    except OSError:
                        pass
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps({"version": 2, "trip": body.get("trip"),
                                           "saved": time.strftime("%Y-%m-%dT%H:%M:%S"), "overrides": ov},
                                          indent=1), encoding="utf-8")
                os.replace(tmp, f)
                return self._json({"ok": True, "count": len(ov)})
            if path == "/api/build":
                mode = body.get("mode")
                if mode not in ("data", "full", "publish"):
                    return self._text("mode must be data, full or publish", 400)
                if not build.start(root, out, mode):
                    return self._text("a build is already running", 409)
                return self._json({"ok": True})
            return self._text("not found", 404)

        # Video seeking needs HTTP Range support, which the stock server lacks.
        def _range(self):
            fpath = self.translate_path(self.path)
            if not os.path.isfile(fpath):
                return super().do_GET()
            size = os.path.getsize(fpath)
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if not m:
                return super().do_GET()
            a, b = m.groups()
            if a == "":
                start, end = max(0, size - int(b or 0)), size - 1
            else:
                start, end = int(a), int(b) if b else size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(fpath))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                with open(fpath, "rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = fh.read(min(256 * 1024, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Serve the trip map locally with edit tools.")
    ap.add_argument("trip", nargs="?", default=None, help="Trip folder (default: the folder containing TripMap)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--remote", default=None, help="rclone remote for Publish (default r2:trip-media)")
    args = ap.parse_args()

    root = Path(args.trip).resolve() if args.trip else HERE.parent
    out = root / OUT_NAME
    if not (out / "index.html").exists():
        sys.exit(f"No map found in {out}. Build it first:\n"
                 f'  python "{HERE / "build.py"}" "{root}" --name "My Trip"')

    build = Build()
    build.remote = args.remote
    port_ref = [args.port]
    server = None
    for port in range(args.port, args.port + 20):
        try:
            port_ref[0] = port
            server = ThreadingHTTPServer(("127.0.0.1", port),
                                         partial(make_handler(root, out, build, port_ref), directory=str(out)))
            break
        except OSError:
            continue
    if not server:
        sys.exit("Couldn't find a free port.")
    url = f"http://127.0.0.1:{port_ref[0]}/index.html?edit"
    print(f"TripMap is running for: {root}")
    print(f"  Edit mode: {url}")
    print(f"  Friends' view (preview): http://127.0.0.1:{port_ref[0]}/")
    print("Keep this window open while you edit. Close it (or Ctrl+C) to stop.\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
