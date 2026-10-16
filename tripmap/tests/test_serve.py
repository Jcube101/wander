"""Tests for serve.py: the editor page comes from the repo, not the build-time
copy in _tripmap/. Run: python -m unittest discover tripmap/tests"""
import http.client
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve  # noqa: E402


class ServesRepoViewer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        out = root / "_tripmap"
        (out / "thumbs").mkdir(parents=True)
        (out / "index.html").write_text("<p>STALE COPY</p>")
        (out / "trip.js").write_text("window.TRIP = {};\n")
        (out / "thumbs" / "a.jpg").write_bytes(b"jpg")
        port_ref = [0]
        handler = serve.make_handler(root, out, serve.Build(), port_ref)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(out)))
        port_ref[0] = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.repo_viewer = (serve.HERE / "viewer.html").read_bytes()

    def get(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            conn.request(method, path)
            r = conn.getresponse()
            return r.status, r.getheader("Cache-Control"), r.read()
        finally:
            conn.close()

    def test_index_and_root_serve_repo_viewer(self):
        for path in ("/index.html?edit", "/index.html", "/"):
            with self.subTest(path=path):
                status, cc, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, self.repo_viewer)
                self.assertNotIn(b"STALE COPY", body)
                self.assertEqual(cc, "no-store")

    def test_head_matches_get(self):
        status, cc, body = self.get("/index.html", method="HEAD")
        self.assertEqual((status, cc, body), (200, "no-store", b""))

    def test_trip_js_not_stored(self):
        status, cc, body = self.get("/trip.js")
        self.assertEqual((status, cc), (200, "no-store"))
        self.assertIn(b"window.TRIP", body)

    def test_other_files_still_from_bundle(self):
        status, cc, body = self.get("/thumbs/a.jpg")
        self.assertEqual((status, cc, body), (200, "no-cache", b"jpg"))


if __name__ == "__main__":
    unittest.main()
