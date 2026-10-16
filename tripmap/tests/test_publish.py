"""Tests for publish.py's Access guard. Run: python -m unittest discover tripmap/tests"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
        self.assertEqual(cls.call_args[0][0], "media.job-joseph.com")
        method, path = conn.request.call_args[0][:2]
        headers = conn.request.call_args[1].get("headers", {})
        self.assertEqual((method, path), ("GET", "/bali-2027/trip.json"))
        self.assertNotIn("cookie", {k.lower() for k in headers})


class PublishGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = Path(self.tmp.name) / "_tripmap"
        out.mkdir()
        (out / "trip.json").write_text(json.dumps({"slug": "bali-2027", "title": "Bali 2027", "items": []}))
        self.addCleanup(self.tmp.cleanup)

    def run_main(self, status, *extra):
        argv = ["publish.py", self.tmp.name, *extra]
        rclone = mock.MagicMock(return_value=(1, "", "stop here"))
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(publish.shutil, "which", return_value="rclone"), \
             mock.patch.object(publish, "check_protected", return_value=(status in publish.PROTECTED, status)), \
             mock.patch.object(publish, "rclone", rclone), \
             mock.patch.object(publish, "log"):
            with self.assertRaises(SystemExit) as cm:
                publish.main()
        return str(cm.exception.code), rclone

    def test_unprotected_trip_stops_before_any_upload(self):
        msg, rclone = self.run_main(404)
        rclone.assert_not_called()
        self.assertIn("Create the Access app for bali-2027 first", msg)
        self.assertIn("docs/runbook.md", msg)

    def test_protected_trip_goes_on_to_upload(self):
        msg, rclone = self.run_main(302)
        rclone.assert_called()
        self.assertIn("Upload failed", msg)

    def test_allow_unprotected_skips_the_check(self):
        msg, rclone = self.run_main(200, "--allow-unprotected")
        rclone.assert_called()


if __name__ == "__main__":
    unittest.main()
