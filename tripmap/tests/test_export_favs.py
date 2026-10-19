"""Tests for export_favs.py. Run: python -m unittest discover tripmap/tests

A temp trip folder with made-up originals, rclone mocked (it only ever runs `cat`),
the salt in a temp file. Checks the file name matches the Worker's, the names
match the site's downloads, and nothing outside the export folder changes.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[2]
os.environ["WANDER_CONFIG"] = str(REPO / "wander.config.example.json")
import export_favs  # noqa: E402

SALT = "test-salt-not-a-secret"
T = 1746196200  # 2025-05-02 14:30 UTC = 15:30 in the trip's zone (+01:00)
ITEMS = [  # id, rel, t, archived
    ("aaaaaaaaaaa1", "phone/IMG_0001.HEIC", T, False),
    ("bbbbbbbbbbb2", "dji/DJI_0002.MP4", T + 3600, False),          # has a .LRF proxy next to it
    ("ccccccccccc3", "phone/IMG_0003.jpg", T + 7200, True),          # archived
    ("ddddddddddd4", "phone/gone.jpg", T + 7300, False),             # original missing
    ("eeeeeeeeeee5", "a/IMG_9.JPG", T + 60, False),                  # same name, same minute ...
    ("fffffffffff6", "b/IMG_9.jpg", T + 90, False),                  # ... in another folder
    ("00000000000a", "phone/IMG_0010.jpg", T + 9000, False),         # not a favourite
    ("00000000000b", "dji/DJI_0002.LRF", T + 3600, False),           # a proxy: never exported
]
FAVS = ["bbbbbbbbbbb2", "aaaaaaaaaaa1", "ccccccccccc3", "ddddddddddd4", "eeeeeeeeeee5", "fffffffffff6",
        "999999999999", "aaaaaaaaaaa1", "00000000000b"]  # an id the trip doesn't have, a repeat, a proxy


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.out = base / "Lisbon trip", base / "exports"
        self.out.mkdir()
        self.originals = {}
        for i, rel, t, archived in ITEMS:
            if rel == "phone/gone.jpg":
                continue
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(rel.encode() * 100)
            self.originals[p] = p.read_bytes()
        (self.root / "dji" / "DJI_0002.LRF").write_bytes(b"proxy")
        self.originals[self.root / "dji" / "DJI_0002.LRF"] = b"proxy"
        items = [{"id": i, "type": "video" if rel.endswith(".MP4") else "photo", "orig": rel.split("/")[-1],
                  "rel": rel, "t": t, **({"archived": True} if a else {})} for i, rel, t, a in ITEMS]
        (self.root / "_tripmap").mkdir()
        trip = {"title": "Lisbon 2025", "slug": "lisbon-2025", "tzOffsetMin": 60, "items": items}
        (self.root / "_tripmap" / "trip.js").write_text("window.TRIP = " + json.dumps(trip) + ";\n", encoding="utf-8")
        self.mtimes = {p: p.stat().st_mtime_ns for p in self.originals}

        salt = base / "favs-salt"
        salt.write_text(SALT + "\n", encoding="utf-8")
        self.patch(export_favs, "SALT_FILE", salt)
        self.patch(export_favs.shutil, "which", lambda name: "/usr/bin/" + name)
        self.calls = []
        self.remote = {f"r2:trip-media/{export_favs.favs_key('lisbon-2025', SALT, 'alex@example.com')}":
                       json.dumps({"version": 1, "ids": FAVS, "updated": "2025-06-01T00:00:00Z"})}
        self.patch(export_favs.subprocess, "run", self.rclone)

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def rclone(self, cmd, **kw):
        self.calls.append(cmd)
        target = cmd[2]
        if target in self.remote:
            return subprocess.CompletedProcess(cmd, 0, self.remote[target], "")
        return subprocess.CompletedProcess(cmd, 3, "", "ERROR : : error listing: directory not found")

    def run_export(self, *args, answer="y", email="alex@example.com"):
        argv = [str(self.root), "--out", str(self.out), *args] + (["--email", email] if email else [])
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=lambda prompt: (out.write(prompt), answer)[1]), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = export_favs.main(argv)
            except SystemExit as e:
                code = e.code
        self.output = out.getvalue()
        self.assertNotIn(SALT, self.output)  # never printed, whatever happens
        return code

    @property
    def dest(self):
        return self.out / "lisbon-2025-favourites-alex"

    def assert_originals_untouched(self):
        for p, data in self.originals.items():
            self.assertEqual(p.read_bytes(), data, p)
            self.assertEqual(p.stat().st_mtime_ns, self.mtimes[p], p)

    def test_favourites_file_name_matches_the_workers(self):
        # The same value is asserted in worker/test/worker.test.mjs for the same salt and email.
        self.assertEqual(export_favs.favs_key("lisbon-2025", SALT, " Alex@Example.com "),
                         "favs/lisbon-2025/e2175ea18419e4d926b9ca8e1269105e9011a010ad02e1bc3264ccb8ced827f5.json")
        self.assertEqual(export_favs.favs_key("lisbon-2025", SALT, "alex@example.com"),
                         f"favs/lisbon-2025/{hashlib.sha256((SALT + 'alex@example.com').encode()).hexdigest()}.json")

    def test_names_match_the_worker_and_the_site(self):
        cases = json.loads((REPO / "worker" / "test" / "download-names.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 10)
        for c in cases:
            self.assertEqual(export_favs.download_name(c["orig"], c["t"], c["tzOffsetMin"], c["id"], c["ext"]),
                             c["name"], c["why"])
        used = set()
        self.assertEqual([export_favs.unique_name(n, used) for n in ("a.jpg", "a.jpg", "A.JPG", "a_2.jpg", "b")],
                         ["a.jpg", "a_2.jpg", "A_3.JPG", "a_2_2.jpg", "b"])

    def test_dry_run_lists_and_copies_nothing(self):
        self.assertEqual(self.run_export("--dry-run"), 0)
        self.assertFalse(self.dest.exists())
        self.assertIn("4 originals", self.output)
        self.assertIn("2025-05-02_1630_DJI_0002.mp4", self.output)
        self.assertIn("Dry run: nothing copied.", self.output)
        self.assertNotIn("[y/N]", self.output)
        self.assert_originals_untouched()

    def test_copies_originals_with_time_prefixed_names(self):
        self.assertEqual(self.run_export(), 0)
        self.assertIn("[y/N]", self.output)
        got = sorted(p.name for p in self.dest.iterdir())
        self.assertEqual(got, ["2025-05-02_1530_IMG_0001.heic", "2025-05-02_1531_IMG_9.jpg",
                               "2025-05-02_1531_IMG_9_2.jpg", "2025-05-02_1630_DJI_0002.mp4"])
        self.assertEqual((self.dest / "2025-05-02_1630_DJI_0002.mp4").read_bytes(),
                         self.originals[self.root / "dji" / "DJI_0002.MP4"])  # the full clip, not the proxy
        self.assertEqual((self.dest / "2025-05-02_1531_IMG_9.jpg").read_bytes(), self.originals[self.root / "a" / "IMG_9.JPG"])
        self.assertIn("1 favourite(s) aren't in this trip's local data", self.output)
        self.assertIn("Skipped 1 archived shot(s)", self.output)
        self.assertIn("original missing, skipped: phone/gone.jpg", self.output)
        self.assertIn("skipped: dji/DJI_0002.LRF", self.output)
        self.assert_originals_untouched()
        # Read-only on R2: one `rclone cat` of the person's file, nothing else.
        key = export_favs.favs_key("lisbon-2025", SALT, "alex@example.com")
        self.assertEqual(self.calls, [["rclone", "cat", f"r2:trip-media/{key}", "--s3-no-check-bucket"]])

    def test_run_again_skips_what_is_there(self):
        self.run_export()
        before = {p.name: p.stat().st_mtime_ns for p in self.dest.iterdir()}
        (self.dest / "2025-05-02_1530_IMG_0001.heic").unlink()
        self.assertEqual(self.run_export(), 0)
        self.assertIn("1 copied, 3 already there", self.output)
        self.assertEqual({p.name for p in self.dest.iterdir()}, set(before))
        self.assertFalse(list(self.dest.glob("*.part")))

    def test_no_means_nothing_copied(self):
        self.assertEqual(self.run_export(answer="n"), 0)
        self.assertFalse(self.dest.exists())
        self.assertIn("Nothing copied.", self.output)

    def test_default_person_is_the_owner_in_the_config(self):
        cfg = Path(self.tmp.name) / "config.json"
        data = json.loads((REPO / "wander.config.example.json").read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, {"WANDER_CONFIG": str(cfg)}):
            cfg.write_text(json.dumps({**data, "owner_email": "Alex@Example.com"}), encoding="utf-8")
            self.assertEqual(self.run_export(email=None), 0)
            # Emails ignore case, so the folder does too (exact name: some file systems don't ignore case).
            self.assertEqual([p.name for p in self.out.iterdir()], ["lisbon-2025-favourites-alex"])
            cfg.write_text(json.dumps(data), encoding="utf-8")  # still the example's you@example.com
            self.assertEqual(self.run_export(email=None), "ERROR: owner_email in "
                             f"{cfg} is still the example (you@example.com). Put the email you sign in with there, or pass --email.")
            cfg.write_text(json.dumps({**data, "owner_email": ""}), encoding="utf-8")
            self.assertIn("whose favourites?", self.run_export(email=None))

    def test_no_favourites_file(self):
        self.assertEqual(self.run_export(email="nobody@example.com"), 0)
        self.assertIn("nobody@example.com has no favourites in this trip", self.output)
        self.assertFalse(self.dest.exists())
        self.assertFalse((self.out / "lisbon-2025-favourites-nobody").exists())

    def test_refuses_to_export_into_the_trip_or_the_repo(self):
        for out in (self.root, self.root / "phone", REPO):
            argv_out = str(out)
            with mock.patch.object(self, "out", Path(argv_out)):
                code = self.run_export()
            self.assertIsInstance(code, str)
            self.assertIn("Pick another --out", code)
        self.assertEqual(self.calls, [])
        self.assert_originals_untouched()

    def test_missing_salt_stops(self):
        self.patch(export_favs, "SALT_FILE", Path(self.tmp.name) / "nope")
        code = self.run_export()
        self.assertIn("no favourites salt", code)
        self.assertEqual(self.calls, [])

    def test_rclone_error_stops(self):
        self.remote.clear()
        self.patch(export_favs.subprocess, "run",
                   lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "ERROR : Failed to cat: AccessDenied"))
        self.assertIn("couldn't read the favourites from R2", self.run_export())
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
