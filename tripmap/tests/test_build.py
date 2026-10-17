"""Tests for build.py: archive handling and the chosen cover. Run: python -m unittest discover tripmap/tests

Builds a tiny fixture trip (real 32x24 JPEGs, exiftool stubbed) with made-up
coordinates, so no ffmpeg or exiftool is needed (video previews are faked).
"""
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
import build  # noqa: E402

# name, local time (tz +00:00), (lat, lon) or None. Coordinates are fake.
SHOTS = [
    ("p1.jpg", "2027:03:01 08:00:00", (10.0, 20.0)),
    ("p2.jpg", "2027:03:01 09:00:00", (10.1, 20.1)),
    ("p3.jpg", "2027:03:02 08:00:00", (11.0, 21.0)),
    ("p4.jpg", "2027:03:02 08:05:00", None),          # borrows p3's location
    ("p5.jpg", "2027:03:02 12:00:00", (11.2, 21.2)),
    ("p6.jpg", "2027:03:03 08:00:00", (12.0, 22.0)),
]


def _jpg(path):
    from PIL import Image
    Image.new("RGB", (32, 24), (200, 90, 90)).save(path, "JPEG")


def fake_video_thumb(src, proxy, thumb, *rest):
    """Stands in for ffmpeg: video previews are just a JPEG thumbnail."""
    _jpg(thumb)


def fake_card(real):
    def make_card(kind, src, proxy, preview, card, dur):
        return _jpg(card) if kind == "video" else real(kind, src, proxy, preview, card, dur)
    return make_card


class TripFixture(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = []
        for name, when, ll in SHOTS:
            Image.new("RGB", (32, 24), (90, 140, 200)).save(self.root / name, "JPEG")
            row = {"SourceFile": str(self.root / name), "FileName": name,
                   "DateTimeOriginal": when, "OffsetTimeOriginal": "+00:00"}
            if ll:
                row.update(GPSLatitude=ll[0], GPSLongitude=ll[1])
            self.rows.append(row)

    def build(self, archived=(), extra=None, settings=None):
        ov = {name: {"archived": True} for name in archived}
        for k, v in (extra or {}).items():
            ov.setdefault(k, {}).update(v)
        wrapper = {"version": 2, "overrides": ov}
        if settings is not None:
            wrapper["settings"] = settings
        (self.root / "overrides.json").write_text(json.dumps(wrapper))
        argv = ["build.py", str(self.root), "--name", "Test Trip", "--tz", "+00:00",
                "--quick", "--photo-workers", "1"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(build, "run_exiftool", return_value=[dict(r) for r in self.rows]), \
             mock.patch.object(build, "need"), \
             mock.patch.object(build, "make_video", fake_video_thumb), \
             mock.patch.object(build, "make_card", fake_card(build.make_card)), \
             mock.patch.object(build, "log") as logs:
            build.main()
        self.logs = "\n".join(str(c.args[0]) for c in logs.call_args_list)
        out = self.root / "_tripmap"
        public = json.loads((out / "trip.json").read_text(encoding="utf-8"))
        local = json.loads((out / "trip.js").read_text(encoding="utf-8")[len("window.TRIP = "):].rstrip().rstrip(";"))
        return public, local

    @staticmethod
    def by_orig(data):
        return {x["orig"]: x for x in data["items"]}


class ArchiveBuild(TripFixture):
    def test_archived_items_left_out_of_trip_json_only(self):
        public, local = self.build(archived=["p2.jpg", "p5.jpg"])
        self.assertEqual(sorted(self.by_orig(public)), ["p1.jpg", "p3.jpg", "p4.jpg", "p6.jpg"])
        self.assertNotIn("archived", json.dumps(public))
        loc = self.by_orig(local)
        self.assertEqual(len(loc), 6)
        self.assertTrue(loc["p2.jpg"]["archived"])
        self.assertNotIn("archived", loc["p1.jpg"])

    def test_counts_exclude_archived(self):
        public, _ = self.build(archived=["p2.jpg", "p5.jpg"])
        self.assertEqual(public["counts"], {"items": 4, "photos": 4, "videos": 0, "onMap": 4})
        self.assertEqual({d["key"]: d["count"] for d in public["days"]},
                         {"2027-03-01": 1, "2027-03-02": 2, "2027-03-03": 1})

    def test_fully_archived_day_dropped_without_renumbering(self):
        public, _ = self.build(archived=["p1.jpg", "p2.jpg"])
        self.assertEqual(public["start"], "2027-03-01")
        self.assertEqual(public["end"], "2027-03-03")
        self.assertEqual([(d["key"], d["n"]) for d in public["days"]], [("2027-03-02", 2), ("2027-03-03", 3)])
        self.assertEqual({x["dayN"] for x in public["items"]}, {2, 3})

    def test_archived_gps_shot_still_anchors_others(self):
        public, _ = self.build(archived=["p3.jpg"])
        p4 = self.by_orig(public)["p4.jpg"]
        self.assertEqual((p4["lat"], p4["lon"], p4["loc"], p4["conf"]), (11.0, 21.0, "matched", "high"))

    def test_cover_falls_back_to_next_eligible_shot(self):
        public, local = self.build()
        ids = {x["orig"]: x["id"] for x in local["items"]}
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")  # middle of 6
        public, _ = self.build(archived=["p4.jpg"])
        self.assertEqual(public["cover"], f"cards/{ids['p5.jpg']}.jpg")
        public, _ = self.build(archived=["p6.jpg"])  # cover itself not archived: unchanged
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")

    def test_archived_combines_with_manual_fixes(self):
        _, local = self.build(archived=["p4.jpg"], extra={"p4.jpg": {"lat": 15.0, "lon": 25.0}})
        p4 = self.by_orig(local)["p4.jpg"]
        self.assertEqual((p4["lat"], p4["loc"], p4["archived"]), (15.0, "manual", True))

    def test_local_previews_kept_for_archived(self):
        _, local = self.build(archived=["p2.jpg"])
        p2 = self.by_orig(local)["p2.jpg"]
        self.assertTrue((self.root / "_tripmap" / p2["thumb"]).exists())
        self.assertTrue((self.root / "_tripmap" / p2["card"]).exists())


class CoverChoice(TripFixture):
    """settings.cover in overrides.json: the chosen photo, or the automatic pick."""

    def ids(self):
        _, local = self.build()
        return {x["orig"]: x["id"] for x in local["items"]}

    def test_no_choice_is_todays_automatic_pick(self):
        public, local = self.build()
        ids = {x["orig"]: x["id"] for x in local["items"]}
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")
        self.assertIsNone(local["coverRel"])
        self.assertEqual(local["autoCover"], ids["p4.jpg"])
        self.assertEqual(self.build(settings={})[0]["cover"], public["cover"])
        self.assertNotIn("chosen cover", self.logs)

    def test_chosen_photo_is_the_cover(self):
        ids = self.ids()
        public, local = self.build(settings={"cover": "p1.jpg"})
        self.assertEqual(public["cover"], f"cards/{ids['p1.jpg']}.jpg")
        self.assertEqual(local["coverRel"], "p1.jpg")
        self.assertNotIn("WARNING", self.logs)
        self.assertEqual(set(public), {"version", "title", "slug", "generated", "tzOffsetMin", "start", "end",
                                       "cover", "counts", "days", "items"})  # trip.json shape unchanged

    def test_archived_choice_falls_back_and_restore_brings_it_back(self):
        ids = self.ids()
        public, _ = self.build(archived=["p1.jpg"], settings={"cover": "p1.jpg"})
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")
        self.assertIn("WARNING: the chosen cover p1.jpg is archived; using the automatic pick.", self.logs)
        public, _ = self.build(settings={"cover": "p1.jpg"})  # restored, setting untouched
        self.assertEqual(public["cover"], f"cards/{ids['p1.jpg']}.jpg")

    def test_missing_choice_falls_back(self):
        ids = self.ids()
        public, _ = self.build(settings={"cover": "gone/p9.jpg"})
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")
        self.assertIn("chosen cover gone/p9.jpg is missing", self.logs)

    def test_video_choice_falls_back(self):
        (self.root / "v1.mp4").write_bytes(b"not really a video")
        self.rows.append({"SourceFile": str(self.root / "v1.mp4"), "FileName": "v1.mp4",
                          "CreateDate": "2027:03:02 10:00:00", "Duration": 5})
        ids = self.ids()
        public, _ = self.build(settings={"cover": "v1.mp4"})
        self.assertIn("v1.mp4", [x["orig"] for x in public["items"]])
        self.assertEqual(public["cover"], f"cards/{ids['p4.jpg']}.jpg")
        self.assertIn("chosen cover v1.mp4 is a video", self.logs)


if __name__ == "__main__":
    unittest.main()
