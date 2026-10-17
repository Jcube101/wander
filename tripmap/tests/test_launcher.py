"""Tests for launcher.py and the launcher templates: no machine-specific paths in
the repo, the trip copy points at the repo, and both launchers really start
serve.py on the right folder (the .sh where `sh` exists, the .bat on Windows).
Run: python -m unittest discover tripmap/tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher  # noqa: E402

FAKE_SERVE = """import sys, pathlib
pathlib.Path(__file__).with_name("ran.txt").write_text(sys.argv[1], encoding="utf-8")
"""


class Templates(unittest.TestCase):
    def test_no_machine_specific_paths(self):
        for name, _, _ in launcher.KINDS.values():
            text = (launcher.HERE / name).read_text(encoding="utf-8")
            for bad in ("C:\\Users", "/Users/", "/home/", "D:\\"):
                self.assertNotIn(bad, text, name)

    def test_render_changes_only_the_wander_line(self):
        for kind, (name, line, _) in launcher.KINDS.items():
            with self.subTest(kind=kind):
                before = (launcher.HERE / name).read_text(encoding="utf-8").splitlines()
                after = launcher.render(kind, "/opt/wan'der/tripmap").splitlines()
                changed = [(a, b) for a, b in zip(before, after) if a != b]
                self.assertEqual(len(before), len(after))
                self.assertEqual(len(changed), 1)
                self.assertEqual(changed[0][0], line)
        self.assertIn("WANDER='/opt/wan'\\''der/tripmap'", launcher.render("sh", "/opt/wan'der/tripmap"))

    def test_bat_refuses_awkward_paths(self):
        with self.assertRaises(ValueError):
            launcher.render("bat", 'C:\\100%\\tripmap')


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trip = Path(self.tmp.name) / "My Trip"
        self.trip.mkdir()
        # A stand-in for the repo's tripmap folder: just a serve.py that records its argument.
        self.wander = Path(self.tmp.name) / "repo" / "tripmap"
        self.wander.mkdir(parents=True)
        (self.wander / "serve.py").write_text(FAKE_SERVE, encoding="utf-8")

    def test_writes_once_then_needs_force(self):
        path, what = launcher.install(self.trip, "bat", wander_dir=self.wander)
        self.assertEqual((path.name, what), ("Open Wander Editor.bat", "written"))
        self.assertIn(b"\r\n", path.read_bytes())
        self.assertIn(f'set "WANDER={self.wander}"', path.read_text(encoding="utf-8"))
        self.assertEqual(launcher.install(self.trip, "bat", wander_dir=self.wander)[1], "already up to date")
        other = Path(self.tmp.name) / "elsewhere"
        self.assertIn("--force", launcher.install(self.trip, "bat", wander_dir=other)[1])
        self.assertEqual(launcher.install(self.trip, "bat", force=True, wander_dir=other)[1], "written")

    def test_not_a_folder(self):
        with self.assertRaises(ValueError):
            launcher.install(self.trip / "nope", "sh")

    @unittest.skipUnless(shutil.which("sh") and os.name != "nt", "needs a POSIX sh")
    def test_sh_launcher_starts_serve_on_its_folder(self):
        path, _ = launcher.install(self.trip, "sh", wander_dir=self.wander)
        self.assertTrue(os.access(path, os.X_OK))
        subprocess.run([str(path)], check=True, timeout=30)
        ran = (self.wander / "ran.txt").read_text(encoding="utf-8")
        self.assertEqual(Path(ran).resolve(), self.trip.resolve())

    @unittest.skipUnless(shutil.which("sh") and os.name != "nt", "needs a POSIX sh")
    def test_sh_template_run_from_the_repo_takes_a_folder(self):
        shutil.copy(launcher.HERE / "open-wander-editor.sh", self.wander / "open-wander-editor.sh")
        subprocess.run(["sh", str(self.wander / "open-wander-editor.sh"), str(self.trip)], check=True, timeout=30)
        self.assertEqual(Path((self.wander / "ran.txt").read_text(encoding="utf-8")).resolve(), self.trip.resolve())

    @unittest.skipUnless(os.name == "nt" and shutil.which("python"), "needs Windows and python on PATH")
    def test_bat_launcher_starts_serve_on_its_folder(self):
        path, _ = launcher.install(self.trip, "bat", wander_dir=self.wander)
        subprocess.run(["cmd", "/c", str(path)], check=True, timeout=60, stdin=subprocess.DEVNULL,
                       capture_output=True)
        ran = (self.wander / "ran.txt").read_text(encoding="utf-8")
        self.assertEqual(Path(ran).resolve(), self.trip.resolve())


if __name__ == "__main__":
    unittest.main()
