"""Tests for config.py and the tools that read it: lookup order, validation, and
that publish/access/serve take the media host, remote, names and session lengths
from the config. Run: python -m unittest discover tripmap/tests"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
EXAMPLE = Path(__file__).resolve().parents[2] / "wander.config.example.json"
os.environ["WANDER_CONFIG"] = str(EXAMPLE)
import access  # noqa: E402
import config  # noqa: E402
import publish  # noqa: E402
import serve  # noqa: E402

CUSTOM = {
    "site": {"url": "https://trips.example.org/"},
    "media": {"host": "files.example.org"},
    "storage": {"remote": "cf", "bucket": "my-trips"},
    "access": {"prefix": "Trips", "appSession": "12h", "policySession": "100h"},
    "defaults": {"contact": "me@example.org"},
}


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, data, name="config.json"):
        p = self.dir / name
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return p

    def use(self, path):
        """Point WANDER_CONFIG at path for this test (and reset access.py's loaded copy)."""
        patcher = mock.patch.dict(os.environ, {"WANDER_CONFIG": str(path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        p2 = mock.patch.object(access, "CFG", None)
        p2.start()
        self.addCleanup(p2.stop)


class Load(TempConfig):
    def test_example_is_valid_and_uses_example_com(self):
        cfg = config.load()
        self.assertEqual(cfg.path, EXAMPLE)
        self.assertEqual(cfg.media_host, "media.example.com")
        self.assertEqual(cfg.remote, "r2:trip-media")
        self.assertEqual(cfg.site_url, "https://wander.example.com")
        self.assertEqual((cfg.access_prefix, cfg.app_session, cfg.policy_session), ("Wander", "24h", "730h"))

    def test_custom_values(self):
        self.use(self.write(CUSTOM))
        cfg = config.load()
        self.assertEqual(cfg.remote, "cf:my-trips")
        self.assertEqual(cfg.site_url, "https://trips.example.org")  # trailing slash dropped
        self.assertEqual(cfg.contact, "me@example.org")

    def test_optional_parts_have_defaults(self):
        self.use(self.write({"media": {"host": "m.example.org"}, "storage": {"remote": "r2", "bucket": "abc"}}))
        cfg = config.load()
        self.assertEqual((cfg.site_url, cfg.access_prefix, cfg.app_session, cfg.policy_session, cfg.contact),
                         ("", "Wander", "24h", "730h", ""))

    def test_bad_values_are_all_listed(self):
        bad = {"media": {"host": "https://media.example.com/"}, "storage": {"remote": "r2:", "bucket": "B"},
               "site": {"url": "http://x.example.com"}, "access": {"appSession": "1 day"}}
        self.use(self.write(bad))
        with self.assertRaises(config.ConfigError) as e:
            config.load()
        for key in ("media.host", "storage.remote", "storage.bucket", "site.url", "access.appSession"):
            self.assertIn(key, str(e.exception))

    def test_invalid_json_and_bom(self):
        self.use(self.write("{nope"))
        with self.assertRaises(config.ConfigError):
            config.load()
        self.use(self.write("﻿" + json.dumps(CUSTOM)))
        self.assertEqual(config.load().media_host, "files.example.org")

    def test_env_pointing_nowhere_is_an_error(self):
        self.use(self.dir / "missing.json")
        with self.assertRaises(config.ConfigError) as e:
            config.load(required=False)
        self.assertIn("WANDER_CONFIG", str(e.exception))

    def test_repo_file_wins_over_home_file_and_none_gives_help(self):
        env = {k: v for k, v in os.environ.items() if k != "WANDER_CONFIG"}
        repo, home = self.dir / "repo.json", self.dir / "home.json"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config, "REPO_FILE", repo), mock.patch.object(config, "HOME_FILE", home):
            self.assertIsNone(config.load(required=False))
            with self.assertRaises(config.ConfigError) as e:
                config.load()
            self.assertIn("wander.config.example.json", str(e.exception))
            home.write_text(json.dumps(CUSTOM), encoding="utf-8")
            self.assertEqual(config.load().path, home)
            repo.write_text(json.dumps(dict(CUSTOM, media={"host": "repo.example.org"})), encoding="utf-8")
            self.assertEqual(config.load().media_host, "repo.example.org")


class ToolsUseIt(TempConfig):
    def test_access_names_host_and_sessions_come_from_config(self):
        self.use(self.write(CUSTOM))
        self.assertEqual(access.crew_name("Bali"), "Trips – Bali crew")
        self.assertEqual(access.all_group(), "Trips – All trips")
        self.assertEqual(access.destinations("bali-2027"),
                         ["files.example.org/bali-2027", "files.example.org/auth/bali-2027"])
        self.assertEqual(access.app_settings()["session_duration"], "12h")

    def test_access_without_config_explains(self):
        env = {k: v for k, v in os.environ.items() if k != "WANDER_CONFIG"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config, "REPO_FILE", self.dir / "a.json"), \
                mock.patch.object(config, "HOME_FILE", self.dir / "b.json"), \
                contextlib.redirect_stdout(out):
            code = access.main(["list", "all"])
        self.assertEqual(code, 2)
        self.assertIn("No Wander config found", out.getvalue())

    def test_publish_checks_the_configured_host(self):
        self.use(self.write(CUSTOM))
        conn = mock.MagicMock()
        conn.getresponse.return_value.status = 302
        with mock.patch.object(publish.http.client, "HTTPSConnection", return_value=conn) as cls:
            self.assertEqual(publish.check_protected("bali-2027"), (True, 302))
        self.assertEqual(cls.call_args[0][0], "files.example.org")

    def test_publish_uses_configured_remote_unless_given(self):
        self.use(self.write(CUSTOM))
        trip = self.dir / "trip"
        (trip / "_tripmap").mkdir(parents=True)
        (trip / "_tripmap" / "trip.json").write_text(json.dumps({"slug": "bali-2027", "title": "Bali", "items": []}))
        seen = []

        def fake_rclone(*args, stdin=None, capture=False):
            seen.append(args)
            return 0, "", ""
        for extra, want in (([], "cf:my-trips/bali-2027"), (["--remote", "other:bucket"], "other:bucket/bali-2027")):
            seen.clear()
            with self.subTest(extra=extra), \
                    mock.patch.object(sys, "argv", ["publish.py", str(trip), "--dry-run", *extra]), \
                    mock.patch.object(publish.shutil, "which", return_value="rclone"), \
                    mock.patch.object(publish, "check_protected", return_value=(True, 302)) as chk, \
                    mock.patch.object(publish, "rclone", fake_rclone), \
                    mock.patch.object(publish, "log"):
                publish.main()
                self.assertEqual(chk.call_args[0], ("bali-2027", "files.example.org"))
                self.assertIn(want, seen[0])

    def test_publish_without_config_stops_before_anything(self):
        env = {k: v for k, v in os.environ.items() if k != "WANDER_CONFIG"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config, "REPO_FILE", self.dir / "a.json"), \
                mock.patch.object(config, "HOME_FILE", self.dir / "b.json"), \
                mock.patch.object(sys, "argv", ["publish.py", str(self.dir), "--dry-run"]), \
                mock.patch.object(publish, "rclone") as rc:
            with self.assertRaises(SystemExit) as e:
                publish.main()
        self.assertIn("No Wander config found", str(e.exception.code))
        rc.assert_not_called()

    def test_serve_says_where_publish_goes(self):
        self.use(self.write(CUSTOM))
        self.assertIn("cf:my-trips", serve.publish_target())
        self.assertIn("files.example.org", serve.publish_target())
        self.use(self.write("{nope", "broken.json"))
        self.assertIn("won't work", serve.publish_target())


if __name__ == "__main__":
    unittest.main()
