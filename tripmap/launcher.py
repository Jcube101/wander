#!/usr/bin/env python3
"""
Put the editor launcher in a trip folder, pointing at this copy of the repo.

    python launcher.py "<trip folder>"            # .bat on Windows, .sh elsewhere
    python launcher.py "<trip folder>" --sh       # or --bat, to choose
    python launcher.py "<trip folder>" --force    # replace an existing launcher

Double-click the launcher (or run the .sh) to open the editor for that trip.
The code always runs from this repo; the trip folder only holds the launcher.
"""
import argparse
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KINDS = {
    # template, line to replace (the "find serve.py next to me" default), how to set it
    "bat": ("Open Wander Editor.bat", 'set "WANDER=%~dp0."', lambda p: f'set "WANDER={p}"'),
    "sh": ("open-wander-editor.sh", 'WANDER="$HERE"', lambda p: "WANDER='" + p.replace("'", "'\\''") + "'"),
}


def render(kind, wander_dir):
    """The launcher text for `kind` with WANDER set to wander_dir (the tripmap folder)."""
    name, line, setter = KINDS[kind]
    text = (HERE / name).read_text(encoding="utf-8")
    if text.count(line) != 1:
        raise RuntimeError(f"{name}: expected one line {line!r} to fill in")
    path = str(wander_dir)
    if kind == "bat" and any(c in path for c in '"%'):
        raise ValueError(f"the repo path can't contain \" or % for a .bat launcher: {path}")
    return text.replace(line, setter(path))


def install(trip, kind=None, force=False, wander_dir=HERE):
    """Write the launcher into trip; returns (path, what happened)."""
    kind = kind or ("bat" if os.name == "nt" else "sh")
    trip = Path(trip).resolve()
    if not trip.is_dir():
        raise ValueError(f"not a folder: {trip}")
    target = trip / KINDS[kind][0]
    text = render(kind, wander_dir)
    newline = "\r\n" if kind == "bat" else "\n"
    if target.exists():
        if target.read_text(encoding="utf-8").replace("\r\n", "\n") == text.replace("\r\n", "\n"):
            return target, "already up to date"
        if not force:
            return target, "exists (use --force to replace it)"
    target.write_text(text, encoding="utf-8", newline=newline)
    if kind == "sh":
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target, "written"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Put the Wander editor launcher in a trip folder.")
    ap.add_argument("trip", help="Trip folder (where the photos and videos are)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bat", dest="kind", action="store_const", const="bat", help="Windows launcher")
    g.add_argument("--sh", dest="kind", action="store_const", const="sh", help="mac/Linux launcher")
    ap.add_argument("--force", action="store_true", help="Replace an existing launcher")
    args = ap.parse_args(argv)
    try:
        path, what = install(args.trip, args.kind, args.force)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"{path}: {what}")
    return 0 if what != "exists (use --force to replace it)" else 1


if __name__ == "__main__":
    sys.exit(main())
