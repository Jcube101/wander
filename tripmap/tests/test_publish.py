"""Tests for publish.py: Access guard, upload/delete plan, step order, safety
switches. rclone and HTTP are mocked. Run: python -m unittest discover tripmap/tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests always use the committed example config, never the machine's own.
os.environ["WANDER_CONFIG"] = str(Path(__file__).resolve().parents[2] / "wander.config.example.json")
import publish  # noqa: E402


def fake_conn(status=None, error=None):
    conn = mock.MagicMock()
    if error:
        conn.request.side_effect = error
    else:
        conn.getresponse.return_value.status = status
    return conn


class CheckProtected(unittest.TestCase):
    def check(self, **kw):
        conn = fake_conn(**kw)
        with mock.patch.object(publish.http.client, "HTTPSConnection", return_value=conn) as cls:
            result = publish.check_protected("bali-2027")
        return result, conn, cls

    def test_access_answers_count_as_protected(self):
        for status in (302, 401, 403):
            with self.subTest(status=status):
                (ok, got), _, _ = self.check(status=status)
                self.assertTrue(ok)
                self.assertEqual(got, status)

    def test_open_or_missing_trip_is_not_protected(self):
        for status in (200, 404):
            with self.subTest(status=status):
                (ok, got), _, _ = self.check(status=status)
                self.assertFalse(ok)
                self.assertEqual(got, status)

    def test_network_error_is_not_protected(self):
        (ok, got), conn, _ = self.check(error=OSError("no route"))
        self.assertFalse(ok)
        self.assertIn("no route", got)
        conn.close.assert_called_once()

    def test_asks_like_a_stranger(self):
        _, conn, cls = self.check(status=302)
        self.assertEqual(cls.call_args[0][0], "media.example.com")
        method, path = conn.request.call_args[0][:2]
        headers = conn.request.call_args[1].get("headers", {})
        self.assertEqual((method, path), ("GET", "/bali-2027/trip.json"))
        self.assertNotIn("cookie", {k.lower() for k in headers})


class FakeRclone:
    """Records calls by step name; serves a fake remote listing (1 byte per
    file unless `remote` is a {path: bytes} dict) and bucket size."""

    def __init__(self, remote=(), fail=(), bucket=0):
        self.remote = dict(remote) if isinstance(remote, dict) else {p: 1 for p in remote}
        self.fail, self.bucket = set(fail), bucket
        self.steps, self.lists, self.calls, self.stdin = [], {}, [], {}

    def __call__(self, *args, stdin=None, capture=False):
        args = list(args)
        cmd = args[0]
        if cmd == "copy":
            cmd = "copy-previews" if "--files-from" in args else "copy-data"
        if "--files-from" in args:
            self.lists[cmd] = Path(args[args.index("--files-from") + 1]).read_text(encoding="utf-8").split()
        self.steps.append(cmd)
        self.calls.append(args)
        if stdin is not None:
            self.stdin[cmd] = stdin
        if cmd in self.fail:
            return 1, "", "boom"
        if cmd == "lsf":
            return 0, "".join(f"{n};{p}\n" for p, n in self.remote.items()), ""
        if cmd == "size":
            return 0, json.dumps({"count": len(self.remote), "bytes": self.bucket}), ""
        if cmd == "cat":
            return 1, "", "not found"
        return 0, "", ""


class Publish(unittest.TestCase):
    N = 10  # shots in the fixture; 3 preview files each

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "_tripmap"
        for d in ("thumbs", "cards", "media"):
            (self.out / d).mkdir(parents=True)
        items = []
        for i in range(self.N):
            x = {"id": f"i{i}", "type": "photo", "thumb": f"thumbs/i{i}.jpg",
                 "card": f"cards/i{i}.jpg", "media": f"media/i{i}.jpg"}
            for k in ("thumb", "card", "media"):
                (self.out / x[k]).write_bytes(x[k].encode())  # unique bytes per file
            items.append(x)
        trip = {"slug": "bali-2027", "title": "Bali 2027", "cover": "cards/i0.jpg",
                "items": items, "days": [], "counts": {"items": self.N}}
        (self.out / "trip.json").write_text(json.dumps(trip))
        # Local-only files that must never be uploaded
        (self.out / "trip.js").write_text("x")
        (self.out / "thumbs" / "archived.jpg").write_bytes(b"x")
        self.refs = sorted(f"{d}/i{i}.jpg" for i in range(self.N) for d in ("thumbs", "cards", "media"))

    def run_main(self, rc, *extra, protected=True):
        argv = ["publish.py", self.tmp.name, *extra]
        logs = mock.MagicMock()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(publish.shutil, "which", return_value="rclone"), \
             mock.patch.object(publish, "check_protected", return_value=(protected, 302 if protected else 404)), \
             mock.patch.object(publish, "rclone", rc), \
             mock.patch.object(publish, "log", logs):
            try:
                publish.main()
                code = None
            except SystemExit as e:
                code = str(e.code)
        return code, "\n".join(str(c.args[0]) for c in logs.call_args_list)

    # --- Access guard
    def test_unprotected_trip_stops_before_anything(self):
        rc = FakeRclone()
        code, _ = self.run_main(rc, protected=False)
        self.assertEqual(rc.steps, [])
        self.assertIn("Create the Access app for bali-2027 first", code)
        self.assertIn("RUNBOOK.md", code)

    def test_allow_unprotected_skips_the_check(self):
        rc = FakeRclone()
        code, _ = self.run_main(rc, "--allow-unprotected", protected=False)
        self.assertIsNone(code)
        self.assertIn("copy-previews", rc.steps)

    # --- plan and order
    def test_uploads_only_referenced_files(self):
        rc = FakeRclone()
        self.run_main(rc)
        self.assertEqual(rc.lists["copy-previews"], self.refs)

    def test_deletes_remote_files_not_referenced(self):
        stale = ["media/old.mp4", "thumbs/archived.jpg"]
        rc = FakeRclone(remote=self.refs + stale + ["trip.json"])
        code, out = self.run_main(rc)
        self.assertIsNone(code)
        self.assertEqual(rc.lists["delete"], stale)
        self.assertIn("removed 2 files", out)

    def test_step_order_trip_json_before_deletes(self):
        rc = FakeRclone(remote=self.refs + ["thumbs/archived.jpg"])
        self.run_main(rc)
        self.assertEqual(rc.steps[:5], ["lsf", "size", "copy-previews", "copy-data", "delete"])
        self.assertEqual(rc.steps[-1], "rcat")

    def test_verbose_lists_removed_names(self):
        rc = FakeRclone(remote=self.refs + ["thumbs/archived.jpg"])
        _, quiet = self.run_main(rc)
        _, loud = self.run_main(FakeRclone(remote=self.refs + ["thumbs/archived.jpg"]), "--verbose")
        self.assertNotIn("thumbs/archived.jpg", quiet)
        self.assertIn("thumbs/archived.jpg", loud)

    def test_no_delete_unless_uploads_succeeded(self):
        for failing in ("copy-previews", "copy-data"):
            with self.subTest(failing=failing):
                rc = FakeRclone(remote=self.refs + ["thumbs/archived.jpg"], fail=[failing])
                code, _ = self.run_main(rc)
                self.assertIn("failed", code)
                self.assertNotIn("delete", rc.steps)

    def test_failed_delete_still_updates_landing_but_reports(self):
        rc = FakeRclone(remote=self.refs + ["thumbs/archived.jpg"], fail=["delete"])
        code, _ = self.run_main(rc)
        self.assertIn("rcat", rc.steps)
        self.assertIn("couldn't remove 1 unused files", code)

    # --- mass-delete guard
    def test_mass_delete_stops_before_any_change(self):
        stale = [f"thumbs/old{i}.jpg" for i in range(8)]  # 8 of 38 = 21%
        rc = FakeRclone(remote=self.refs + stale)
        code, _ = self.run_main(rc)
        self.assertEqual(rc.steps, ["lsf", "size"])
        self.assertIn("would remove 8 of 38", code)
        self.assertIn("Nothing was changed", code)

    def test_mass_delete_under_threshold_goes_ahead(self):
        stale = [f"thumbs/old{i}.jpg" for i in range(7)]  # 7 of 37 = 19%
        rc = FakeRclone(remote=self.refs + stale)
        code, _ = self.run_main(rc)
        self.assertIsNone(code)
        self.assertEqual(len(rc.lists["delete"]), 7)

    def test_allow_mass_delete_bypasses_guard(self):
        stale = [f"thumbs/old{i}.jpg" for i in range(20)]
        rc = FakeRclone(remote=self.refs + stale)
        code, _ = self.run_main(rc, "--allow-mass-delete")
        self.assertIsNone(code)
        self.assertEqual(rc.lists["delete"], sorted(stale))

    def test_new_trip_with_no_remote_files(self):
        self.assertFalse(publish.too_many_deletes([], []))
        rc = FakeRclone(remote=[])
        code, out = self.run_main(rc)
        self.assertIsNone(code)
        self.assertNotIn("delete", rc.steps)
        self.assertIn("nothing to remove", out)

    # --- restore and missing files
    def test_restored_shot_is_uploaded_again(self):
        # i3 was archived on the last publish, so its previews aren't on R2
        remote = [r for r in self.refs if "/i3." not in r]
        rc = FakeRclone(remote=remote)
        code, _ = self.run_main(rc)
        self.assertIsNone(code)
        self.assertIn("media/i3.jpg", rc.lists["copy-previews"])
        self.assertNotIn("delete", rc.steps)

    def test_missing_local_file_warns_and_is_not_uploaded_or_deleted(self):
        (self.out / "media" / "i5.jpg").unlink()
        rc = FakeRclone(remote=self.refs)
        code, out = self.run_main(rc)
        self.assertIsNone(code)
        self.assertIn("WARNING: 1 file(s) trip.json references are missing", out)
        self.assertIn("media/i5.jpg", out)
        self.assertNotIn("media/i5.jpg", rc.lists["copy-previews"])
        self.assertNotIn("delete", rc.steps)

    # --- dry run
    def test_dry_run_changes_nothing_and_prints_plan(self):
        rc = FakeRclone(remote=self.refs + ["thumbs/archived.jpg"])
        code, out = self.run_main(rc, "--dry-run")
        self.assertIsNone(code)
        self.assertEqual(rc.steps, ["lsf", "size"])
        self.assertIn(f"upload: {len(self.refs)} referenced files", out)
        self.assertIn("remove: 1 of 31", out)
        self.assertIn("thumbs/archived.jpg", out)

    def test_dry_run_reports_mass_delete_stop(self):
        rc = FakeRclone(remote=self.refs + [f"thumbs/old{i}.jpg" for i in range(10)])
        code, out = self.run_main(rc, "--dry-run")
        self.assertIsNone(code)
        self.assertEqual(rc.steps, ["lsf", "size"])
        self.assertIn("would STOP", out)

    # --- cover
    def set_cover(self, card):
        tj = self.out / "trip.json"
        trip = json.loads(tj.read_text())
        trip["cover"] = card
        tj.write_text(json.dumps(trip))

    def landing(self, rc):
        entry = json.loads(rc.stdin["rcat"])["trips"][0]
        uploads = {c[2].split("/", 1)[1]: Path(c[1]).relative_to(self.out.resolve()).as_posix()
                   for c in rc.calls if c[0] == "copyto"}
        return entry, uploads

    def test_cover_files_come_from_the_chosen_shot(self):
        self.set_cover("cards/i3.jpg")
        rc = FakeRclone(remote=self.refs)
        self.assertIsNone(self.run_main(rc)[0])
        entry, uploads = self.landing(rc)
        self.assertEqual(uploads, {"public/covers/bali-2027-card.jpg": "cards/i3.jpg",
                                   "public/covers/bali-2027.jpg": "media/i3.jpg"})
        v_card = publish.version(self.out / "cards/i3.jpg")
        v_big = publish.version(self.out / "media/i3.jpg")
        self.assertEqual(entry["cover"], f"public/covers/bali-2027-card.jpg?v={v_card}")
        self.assertEqual(entry["coverImage"], f"public/covers/bali-2027.jpg?v={v_big}")
        self.assertRegex(v_card, r"^[0-9a-f]{10}$")

    def test_cover_version_changes_only_with_the_cover(self):
        def publish_with(card):
            self.set_cover(card)
            rc = FakeRclone(remote=self.refs)
            self.run_main(rc)
            return self.landing(rc)[0]
        a, again, b = publish_with("cards/i3.jpg"), publish_with("cards/i3.jpg"), publish_with("cards/i7.jpg")
        self.assertEqual((a["cover"], a["coverImage"]), (again["cover"], again["coverImage"]))
        self.assertNotEqual(a["cover"], b["cover"])
        self.assertNotEqual(a["coverImage"], b["coverImage"])
        self.assertEqual(a["cover"].split("?")[0], b["cover"].split("?")[0])  # same R2 key

    def test_cover_without_big_image_uses_card_for_both(self):
        (self.out / "media" / "i0.jpg").unlink()
        rc = FakeRclone(remote=self.refs)
        self.run_main(rc)
        entry, uploads = self.landing(rc)
        self.assertEqual(list(uploads), ["public/covers/bali-2027-card.jpg"])
        self.assertEqual(entry["cover"], entry["coverImage"])

    # --- R2 storage check
    def test_storage_line_in_dry_run(self):
        rc = FakeRclone(remote=self.refs, bucket=3_000_000_000)
        code, out = self.run_main(rc, "--dry-run")
        self.assertIsNone(code)
        self.assertEqual(rc.steps, ["lsf", "size"])
        self.assertIn("R2 storage: 3.00 GB now → 3.00 GB after publish (free tier 10 GB)", out)
        self.assertNotIn("WARNING: R2", out)

    def test_storage_projection_counts_new_uploads_and_deletes(self):
        # i0's previews (2 bytes each locally) aren't on R2 yet; a 0.5 GB stale file goes
        for d in ("thumbs", "cards", "media"):
            (self.out / d / "i0.jpg").write_bytes(b"xx")
        remote = {r: 1 for r in self.refs if "/i0." not in r}
        remote["media/old.mp4"] = 500_000_000
        rc = FakeRclone(remote=remote, bucket=2_000_000_000)
        with mock.patch.object(publish, "storage_report", wraps=publish.storage_report) as sr:
            code, out = self.run_main(rc, "--dry-run")
        self.assertIsNone(code)
        sr.assert_called_once_with(2_000_000_000, 6, 500_000_000)  # files already on R2 count 0
        self.assertIn("2.00 GB now → 1.50 GB after publish", out)

    def test_storage_thresholds(self):
        gb = publish.GB
        self.assertIsNone(publish.storage_report(7 * gb, int(gb), 0)[1])  # exactly 8: no warning
        near = publish.storage_report(7 * gb, int(1.5 * gb), 0)[1]
        self.assertIn("close to the 10 GB free tier", near)
        self.assertIn("--crf 30", near)
        self.assertIn("--video-height 540", near)
        over = publish.storage_report(9.5 * gb, int(gb), 0)[1]
        self.assertIn("start costing money", over)
        self.assertNotIn("close to", over)
        self.assertIsNone(publish.storage_report(11 * gb, 0, int(4 * gb))[1])  # deletes bring it under

    def test_storage_warning_repeated_after_publish(self):
        rc = FakeRclone(remote=self.refs, bucket=int(9 * publish.GB))
        code, out = self.run_main(rc)
        self.assertIsNone(code)
        tail = out.split("Published.", 1)[1]
        self.assertIn("R2 storage: 9.00 GB now", tail)
        self.assertIn("WARNING: R2 storage is getting close", tail)

    def test_failed_size_check_does_not_block(self):
        rc = FakeRclone(remote=self.refs, fail=["size"])
        code, out = self.run_main(rc)
        self.assertIsNone(code)
        self.assertIn("WARNING: couldn't check R2 storage (boom)", out)
        self.assertIn("rcat", rc.steps)
        self.assertNotIn("R2 storage:", out)

    def test_dry_run_still_runs_access_guard(self):
        rc = FakeRclone()
        code, _ = self.run_main(rc, "--dry-run", protected=False)
        self.assertIn("isn't protected", code)
        self.assertEqual(rc.steps, [])


class RemoteListing(unittest.TestCase):
    def test_new_trip_directory_not_found_is_empty(self):
        with mock.patch.object(publish, "rclone", return_value=(3, "", "error listing: directory not found")):
            self.assertEqual(publish.remote_previews("r2:trip-media/new"), {})

    def test_other_listing_errors_stop(self):
        with mock.patch.object(publish, "rclone", return_value=(1, "", "AccessDenied")):
            with self.assertRaises(SystemExit):
                publish.remote_previews("r2:trip-media/x")

    def test_only_preview_folders_count(self):
        listing = "5;trip.json\n10;thumbs/a.jpg\n20;cards/a.jpg\n300;media/a.mp4\n7;index.html\n"
        with mock.patch.object(publish, "rclone", return_value=(0, listing, "")):
            self.assertEqual(publish.remote_previews("r2:trip-media/x"),
                             {"cards/a.jpg": 20, "media/a.mp4": 300, "thumbs/a.jpg": 10})

    def test_bucket_size_bad_output_is_none(self):
        for rv in ((1, "", "AccessDenied"), (0, "not json", ""), (0, "{}", "")):
            with self.subTest(rv=rv), mock.patch.object(publish, "rclone", return_value=rv):
                self.assertIsNone(publish.bucket_size("r2:trip-media")[0])


if __name__ == "__main__":
    unittest.main()
