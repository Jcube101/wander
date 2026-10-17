"""Characterization tests for build.py's time and location rules: they lock in
current behaviour. Run: python -m unittest discover tripmap/tests

Each test feeds made-up exiftool rows (exiftool stubbed) to a --data-only build,
so no media files, ffmpeg or trip drive are needed. Dates and coordinates are fake.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests always use the committed example config, never the machine's own.
os.environ["WANDER_CONFIG"] = str(Path(__file__).resolve().parents[2] / "wander.config.example.json")
import build  # noqa: E402


def ep(local, off="+07:00"):
    """'2027-03-01 08:00:00' at a UTC offset -> epoch seconds."""
    sign = -1 if off[0] == "-" else 1
    h, m = off[1:].split(":")
    tz = timezone(sign * timedelta(hours=int(h), minutes=int(m)))
    return int(datetime.strptime(local, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).timestamp())


def photo(name, local=None, off="+07:00", gps=None, **extra):
    """exiftool row for a phone photo; local = 'YYYY-MM-DD HH:MM:SS' or None."""
    row = {"FileName": name, **extra}
    if local:
        row["DateTimeOriginal"] = local.replace("-", ":")
        if off:
            row["OffsetTimeOriginal"] = off
    if gps:
        row.update(GPSLatitude=gps[0], GPSLongitude=gps[1])
    return row


ANCHOR = (10.0, 20.0)


class BuildCase(unittest.TestCase):
    """Runs build.py on fake exiftool rows; helpers only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_build(self, rows, *extra, csv=None, overrides=None, tz="+07:00"):
        if csv is not None:
            (self.root / "clip_locations.csv").write_text(csv, encoding="utf-8")
        if overrides is not None:
            (self.root / "overrides.json").write_text(json.dumps({"version": 2, "overrides": overrides}))
        rows = [dict(r, SourceFile=str(self.root / r["FileName"])) for r in rows]
        argv = ["build.py", str(self.root), "--name", "Rules", "--tz", tz, "--data-only", *extra]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(build, "run_exiftool", return_value=rows), \
             mock.patch.object(build, "need"), \
             mock.patch.object(build, "log") as logs:
            build.main()
        self.logs = "\n".join(str(c.args[0]) for c in logs.call_args_list)
        js = (self.root / "_tripmap" / "trip.js").read_text(encoding="utf-8")
        self.trip = json.loads(js[len("window.TRIP = "):].rstrip().rstrip(";"))
        return {x["orig"]: x for x in self.trip["items"]}

    def assertTime(self, item, t, tsrc):
        self.assertEqual((item["t"], item["tsrc"]), (t, tsrc))


class Rules(BuildCase):
    # ------------------------------------------------------------ time

    def test_dji_clip_time_from_filename_at_camera_offset(self):
        items = self.run_build([
            {"FileName": "DJI_20270301120000_0001_D.MP4", "Make": "DJI", "CreateDate": "2027:03:01 01:00:00"},
            {"FileName": "DJI_20270301130000_0002_D.MP4", "CreateDate": "2027:03:01 01:00:00"},  # name alone
            photo("DJI_20270301140000_0003_D.JPG", "2027-03-01 14:00:00", "+07:00", Make="DJI"),
        ], "--camera-offset", "+07:45")
        # Filename beats QuickTime CreateDate, read at --camera-offset
        self.assertTime(items["DJI_20270301120000_0001_D.MP4"], ep("2027-03-01 12:00:00", "+07:45"), "dji-filename")
        self.assertTime(items["DJI_20270301130000_0002_D.MP4"], ep("2027-03-01 13:00:00", "+07:45"), "dji-filename")
        # Only videos: a DJI photo uses its EXIF time
        self.assertTime(items["DJI_20270301140000_0003_D.JPG"], ep("2027-03-01 14:00:00"), "exif+offset")

    def test_photo_time_order(self):
        rows = [
            # EXIF + its own offset wins, even over GPS time
            photo("a.jpg", "2027-03-01 10:00:00", "+02:00", GPSDateTime="2027:03:01 01:00:00Z"),
            # no offset -> GPS time (UTC)
            photo("b.jpg", "2027-03-01 10:00:00", None, GPSDateTime="2027:03:01 05:00:00Z"),
            # neither -> EXIF at --assume-tz (default --tz)
            photo("c.jpg", "2027-03-01 10:00:00", None),
        ]
        items = self.run_build(rows)
        self.assertTime(items["a.jpg"], ep("2027-03-01 10:00:00", "+02:00"), "exif+offset")
        self.assertTime(items["b.jpg"], ep("2027-03-01 05:00:00", "+00:00"), "gps-time")
        self.assertTime(items["c.jpg"], ep("2027-03-01 10:00:00", "+07:00"), "exif-assumed-tz")
        items = self.run_build(rows, "--assume-tz", "+03:00")
        self.assertTime(items["c.jpg"], ep("2027-03-01 10:00:00", "+03:00"), "exif-assumed-tz")

    def test_video_quicktime_createdate_is_utc(self):
        items = self.run_build([{"FileName": "clip.mp4", "CreateDate": "2027:03:01 05:00:00"}])
        self.assertTime(items["clip.mp4"], ep("2027-03-01 05:00:00", "+00:00"), "quicktime-utc")

    def test_filename_time_when_no_metadata(self):
        items = self.run_build([photo("PXL_20270301_093000123.jpg"),
                                {"FileName": "VID_20270301_101500.mp4"}])
        self.assertTime(items["PXL_20270301_093000123.jpg"], ep("2027-03-01 09:30:00"), "filename")
        self.assertTime(items["VID_20270301_101500.mp4"], ep("2027-03-01 10:15:00"), "filename")

    def test_whatsapp_date_from_name_plus_file_time(self):
        items = self.run_build([
            photo("p1.jpg", "2027-03-01 08:00:00", gps=ANCHOR),
            photo("p2.jpg", "2027-03-03 08:00:00", gps=ANCHOR),
            # file saved on the named day: its time is used
            photo("IMG-20270302-WA0001.jpg", FileModifyDate="2027:03:02 15:00:00+07:00"),
            # saved on another day (e.g. copied later): noon of the named day
            photo("IMG-20270302-WA0002.jpg", FileModifyDate="2027:03:09 10:00:00+07:00"),
        ])
        self.assertTime(items["IMG-20270302-WA0001.jpg"], ep("2027-03-02 15:00:00"), "date+filetime")
        self.assertTime(items["IMG-20270302-WA0002.jpg"], ep("2027-03-02 12:00:00"), "date-only")

    def test_date_only_files_outside_the_trip_are_dropped(self):
        items = self.run_build([
            photo("p1.jpg", "2027-03-01 08:00:00", gps=ANCHOR),
            photo("p2.jpg", "2027-03-03 08:00:00", gps=ANCHOR),
            # within a day of the first/last firm time: kept
            photo("IMG-20270228-WA0001.jpg", FileModifyDate="2027:02:28 10:00:00+07:00"),
            # further out: dropped
            photo("IMG-20270220-WA0002.jpg", FileModifyDate="2027:02:20 10:00:00+07:00"),
            photo("IMG-20270227-WA0004.jpg"),  # noon 27 Feb: just over a day before 1 Mar 08:00
            photo("IMG-20270305-WA0003.jpg"),
            # not WhatsApp-only: any date-only name is subject to the same rule
            photo("Scan_20270220.jpg"),
        ])
        self.assertEqual(sorted(items), ["IMG-20270228-WA0001.jpg", "p1.jpg", "p2.jpg"])
        self.assertIn("left out 4 date-only files outside the trip dates", self.logs)

    # ------------------------------------------------------------ location

    def test_whatsapp_never_auto_located(self):
        items = self.run_build([
            photo("p1.jpg", "2027-03-02 15:00:00", gps=ANCHOR),
            photo("IMG-20270302-WA0001.jpg", FileModifyDate="2027:03:02 15:02:00+07:00"),
        ])
        wa = items["IMG-20270302-WA0001.jpg"]
        self.assertNotIn("lat", wa)
        self.assertNotIn("loc", wa)

    def test_location_order_gps_then_csv_then_manual(self):
        csv = ("filename,lat,lon,utc_time,confidence\n"
               "a.jpg,30.0,40.0,,\n"
               "b.mp4,31.0,41.0,2027-03-01 02:00:00,medium\n"
               "c.jpg,32.0,42.0,,\n")
        items = self.run_build([
            photo("a.jpg", "2027-03-01 08:00:00", gps=ANCHOR),
            {"FileName": "b.mp4", "CreateDate": "2027:03:01 01:00:00"},
            photo("c.jpg", "2027-03-01 08:10:00", gps=ANCHOR),
        ], csv=csv, overrides={"c.jpg": {"lat": 50.0, "lon": 60.0}})
        a, b, c = items["a.jpg"], items["b.mp4"], items["c.jpg"]
        self.assertEqual((a["lat"], a["lon"], a["loc"]), (30.0, 40.0, "csv"))  # CSV beats GPS
        self.assertEqual((b["lat"], b["loc"], b["conf"]), (31.0, "csv", "medium"))
        self.assertTime(b, ep("2027-03-01 02:00:00", "+00:00"), "csv")  # CSV time beats metadata
        self.assertEqual((c["lat"], c["lon"], c["loc"]), (50.0, 60.0, "manual"))  # manual beats CSV

    def test_csv_row_without_location_is_never_matched(self):
        items = self.run_build([
            photo("p1.jpg", "2027-03-01 08:00:00", gps=ANCHOR),
            {"FileName": "clip.mp4", "CreateDate": "2027:03:01 01:05:00"},  # 08:05 local
        ], csv="filename,lat,lon\nclip.mp4,,\n")
        self.assertNotIn("lat", items["clip.mp4"])

    def test_match_window_and_confidence(self):
        mins = [5, 10, 11, 20, 30, 31, 120, 121]
        rows = [photo("anchor.jpg", "2027-03-01 08:00:00", gps=ANCHOR)]
        rows += [photo(f"m{m}.jpg", (datetime(2027, 3, 1, 8) + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S"))
                 for m in mins]
        expected = {5: "high", 10: "high", 11: "medium", 20: "medium", 30: "medium", 31: "low", 120: "low", 121: None}
        items = self.run_build(rows)
        for m, conf in expected.items():
            with self.subTest(minutes=m):
                x = items[f"m{m}.jpg"]
                if conf:
                    self.assertEqual((x["lat"], x["lon"], x["loc"], x["conf"]), (*ANCHOR, "matched", conf))
                else:  # beyond the window; m120 (matched) is not an anchor for it
                    self.assertNotIn("lat", x)
        items = self.run_build(rows, "--match-window", "30")
        self.assertEqual(items["m30.jpg"]["conf"], "medium")
        self.assertNotIn("lat", items["m31.jpg"])
        items = self.run_build(rows, "--match-window", "0")
        self.assertNotIn("lat", items["m5.jpg"])

    def test_only_gps_and_manual_shots_are_anchors(self):
        items = self.run_build([
            photo("manual.jpg", "2027-03-01 12:00:00"),
            photo("near-manual.jpg", "2027-03-01 12:05:00"),
            photo("csv.jpg", "2027-03-01 18:00:00"),
            photo("near-csv.jpg", "2027-03-01 18:05:00"),
        ], csv="filename,lat,lon\ncsv.jpg,30.0,40.0\n", overrides={"manual.jpg": {"lat": 50.0, "lon": 60.0}})
        x = items["near-manual.jpg"]
        self.assertEqual((x["lat"], x["lon"], x["loc"], x["conf"]), (50.0, 60.0, "matched", "high"))
        self.assertNotIn("lat", items["near-csv.jpg"])

    def test_manual_overrides_beat_everything(self):
        items = self.run_build([
            photo("anchor.jpg", "2027-03-01 08:00:00", gps=ANCHOR),
            photo("gps-cleared.jpg", "2027-03-01 08:01:00", gps=(11.0, 21.0)),
            photo("near-cleared.jpg", "2027-03-01 08:02:00"),
            photo("retimed.jpg", "2027-03-01 08:03:00"),
            {"FileName": "DJI_20270301090000_0001_D.MP4", "Make": "DJI"},
            photo("IMG-20270220-WA0001.jpg"),  # would be dropped as outside the trip
        ], overrides={
            "gps-cleared.jpg": {"noloc": True},
            "near-cleared.jpg": None,  # null = deliberately no location
            "retimed.jpg": {"t": ep("2027-03-02 15:00:00")},
            "DJI_20270301090000_0001_D.MP4": {"t": ep("2027-03-01 09:30:00")},
            "IMG-20270220-WA0001.jpg": {"t": ep("2027-03-01 20:00:00")},
        })
        for name in ("gps-cleared.jpg", "near-cleared.jpg"):
            with self.subTest(name=name):
                self.assertNotIn("lat", items[name])  # not GPS, not matched
                self.assertEqual(items[name]["loc"], "cleared")
        r = items["retimed.jpg"]
        self.assertTime(r, ep("2027-03-02 15:00:00"), "manual")
        self.assertEqual(r["day"], "2027-03-02")
        self.assertNotIn("lat", r)  # matched at its new time: nothing near
        self.assertTime(items["DJI_20270301090000_0001_D.MP4"], ep("2027-03-01 09:30:00"), "manual")
        self.assertTime(items["IMG-20270220-WA0001.jpg"], ep("2027-03-01 20:00:00"), "manual")  # kept

    # ------------------------------------------------------------ days

    def test_days_follow_the_trip_timezone_around_midnight(self):
        rows = [
            photo("late.jpg", "2027-03-01 23:30:00", "+07:00"),
            photo("early.jpg", "2027-03-02 00:30:00", "+07:00"),
            # phone still on +05:30: 22:45 there is 00:15 next day at +07:00
            photo("other-zone.jpg", "2027-03-01 22:45:00", "+05:30"),
        ]
        items = self.run_build(rows)
        self.assertEqual({k: v["day"] for k, v in items.items()},
                         {"late.jpg": "2027-03-01", "early.jpg": "2027-03-02", "other-zone.jpg": "2027-03-02"})
        self.assertEqual([(d["key"], d["n"], d["count"]) for d in self.trip["days"]],
                         [("2027-03-01", 1, 1), ("2027-03-02", 2, 2)])
        items = self.run_build(rows, tz="+00:00")  # same instants, UTC days
        self.assertEqual(items["other-zone.jpg"]["day"], "2027-03-01")
        self.assertEqual(items["early.jpg"]["day"], "2027-03-01")


class Defaults(BuildCase):
    """No built-in timezone or camera offset: --tz is required, the camera offset
    defaults to 0, and both end up in build_args.json so re-runs never shift."""

    def test_tz_is_required(self):
        with mock.patch.object(sys, "argv", ["build.py", str(self.root), "--name", "X"]),              mock.patch("sys.stderr"), self.assertRaises(SystemExit) as e:
            build.main()
        self.assertEqual(e.exception.code, 2)  # argparse: missing required option

    def test_bad_offset_stops_before_anything_is_written(self):
        with mock.patch.object(sys, "argv", ["build.py", str(self.root), "--tz", "+7h"]),              self.assertRaises(SystemExit) as e:
            build.main()
        self.assertIn("Bad UTC offset", str(e.exception.code))
        self.assertFalse((self.root / "_tripmap").exists())

    def test_camera_offset_defaults_to_utc(self):
        items = self.run_build([
            {"FileName": "DJI_20270301120000_0001_D.MP4", "Make": "DJI"},
        ])
        self.assertTime(items["DJI_20270301120000_0001_D.MP4"], ep("2027-03-01 12:00:00", "+00:00"), "dji-filename")

    def test_negative_offsets_work_without_an_equals_sign(self):
        items = self.run_build([
            photo("a.jpg", "2027-03-01 10:00:00", off=None),
            {"FileName": "DJI_20270301120000_0001_D.MP4", "Make": "DJI"},
        ], "--camera-offset", "-04:00", tz="-05:00")
        self.assertTime(items["a.jpg"], ep("2027-03-01 10:00:00", "-05:00"), "exif-assumed-tz")
        self.assertTime(items["DJI_20270301120000_0001_D.MP4"], ep("2027-03-01 12:00:00", "-04:00"), "dji-filename")
        self.assertEqual(self.trip["tzOffsetMin"], -300)

    def test_build_args_record_tz_and_camera_offset(self):
        self.run_build([photo("a.jpg", "2027-03-01 10:00:00")], tz="+05:30")
        saved = json.loads((self.root / "_tripmap" / "build_args.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[saved.index("--tz") + 1], "+05:30")
        self.assertEqual(saved[saved.index("--camera-offset") + 1], "+00:00")
        self.assertNotIn("--data-only", saved)
        self.run_build([photo("a.jpg", "2027-03-01 10:00:00")], "--camera-offset", "+07:45", tz="-03:00")
        saved = json.loads((self.root / "_tripmap" / "build_args.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.count("--camera-offset"), 1)
        self.assertIn("--tz=-03:00", saved)

    def test_csv_time_without_zone_defaults_to_tz(self):
        items = self.run_build([photo("clip.jpg", "2027-03-01 10:00:00")],
                               csv="filename,lat,lon,local_time\nclip.jpg,1.0,2.0,2027-03-01 09:00:00\n", tz="+03:00")
        self.assertTime(items["clip.jpg"], ep("2027-03-01 09:00:00", "+03:00"), "csv")


if __name__ == "__main__":
    unittest.main()
