#!/usr/bin/env python3
"""
Publish a built trip to Cloudflare R2 (or any rclone remote).

    python publish.py "D:\\2026_ Thailand Trip"            # uses r2:trip-media
    python publish.py "D:\\2026_ Thailand Trip" --remote r2:trip-media

Uploads <trip>/_tripmap to <remote>/<slug>/ and updates <remote>/trips.json,
the list of trips the Wander site shows on its home page.

Order matters so the site never points at files that aren't there yet:
  1. thumbnails, gallery images, previews (cached by browsers for a week)
  2. trip.json, trip.js, index.html        (never cached, so fixes show at once)
  3. trips.json                            (never cached)
Only new or changed files are sent.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LONG = "Cache-Control: public, max-age=604800"
NOCACHE = "Cache-Control: no-cache"
DATA_FILES = ("trip.json",)
# Never uploaded: local editor files (trip.js holds local folder paths) and build leftovers
PRIVATE = ("trip.js", "index.html", "build_args.json", "build_errors.txt", "*.part.mp4")


def log(msg):
    print(msg, flush=True)


def rclone(*args, stdin=None, capture=False):
    # The bucket already exists; skipping rclone's "create bucket" check lets a key
    # that's limited to one bucket (the safe setup) upload single files.
    cmd = ["rclone", *args, "--s3-no-check-bucket"]
    if capture:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", bufsize=1)
    last_err = ""
    for line in p.stdout:
        line = line.strip()
        if line:
            log("  " + line)
            if "ERROR" in line:
                last_err = line.split("ERROR", 1)[1].lstrip(" :")
    return p.wait(), "", last_err


def main():
    ap = argparse.ArgumentParser(description="Publish a built trip to R2 via rclone.")
    ap.add_argument("trip", nargs="?", default=None, help="Trip folder (default: the folder containing TripMap)")
    ap.add_argument("--remote", default="r2:trip-media", help="rclone remote and bucket (default r2:trip-media)")
    ap.add_argument("--transfers", type=int, default=16, help="Files uploaded in parallel (default 16)")
    args = ap.parse_args()

    if not shutil.which("rclone"):
        sys.exit("rclone isn't installed or not on PATH. Install it with: winget install Rclone.Rclone")
    root = Path(args.trip).resolve() if args.trip else HERE.parent
    out = root / "_tripmap"
    tj = out / "trip.json"
    if not tj.exists():
        sys.exit(f"No trip.json in {out}. Run the build first (Apply to map / Scan for new files).")
    trip = json.loads(tj.read_text(encoding="utf-8"))
    slug = trip.get("slug")
    if not slug:
        sys.exit("trip.json has no slug. Re-run the build.")
    remote = args.remote.rstrip("/")
    dst = f"{remote}/{slug}"
    stats = ["--stats", "3s", "--stats-one-line", "--stats-log-level", "NOTICE"]
    speed = ["--transfers", str(args.transfers), "--checkers", "16", "--s3-upload-concurrency", "4"]
    excl = []
    for pat in (*DATA_FILES, *PRIVATE):
        excl += ["--exclude", pat]

    log(f"Publishing '{trip.get('title')}' to {dst}")
    log("1/3 Uploading thumbnails, gallery images and previews (only new or changed ones)...")
    code, _, err = rclone("sync", str(out), dst, *excl, "--header-upload", LONG, "--fast-list", *speed, *stats)
    if code:
        sys.exit(f"Upload failed: {err or f'rclone exit {code}'}")

    log("2/3 Uploading the map data...")
    inc = []
    for f in DATA_FILES:
        inc += ["--include", f]
    code, _, err = rclone("copy", str(out), dst, *inc, "--header-upload", NOCACHE, "--no-traverse", *stats)
    if code:
        sys.exit(f"Data upload failed: {err or f'rclone exit {code}'}")

    log("3/3 Updating the landing page (cover images and list of trips)...")
    code, existing, err = rclone("cat", f"{remote}/trips.json", capture=True)
    try:
        index = json.loads(existing) if code == 0 and existing.strip() else {}
    except ValueError:
        index = {}
    trips = [t for t in index.get("trips", []) if t.get("slug") != slug]
    # Covers live in the public folder so the landing page can show them to
    # everyone, while the trip's own files stay behind its login.
    cover_item = next((x for x in trip.get("items", []) if x.get("card") == trip.get("cover")), None)
    cover, cover_image = None, None
    if trip.get("cover") and (out / trip["cover"]).exists():
        cover = f"public/covers/{slug}-card.jpg"
        big = out / cover_item["media"] if cover_item and cover_item.get("type") == "photo" and cover_item.get("media") else None
        cover_image = f"public/covers/{slug}.jpg" if big and big.exists() else cover
        for local, remote_key in ((out / trip["cover"], cover), (big, cover_image)):
            if local is None or remote_key is None or not local.exists():
                continue
            code, _, err = rclone("copyto", str(local), f"{remote}/{remote_key}",
                                  "--header-upload", "Cache-Control: public, max-age=3600", capture=True)
            if code:
                sys.exit(f"Couldn't upload the cover image: {err.strip()[:300]}")
    trips.append({
        "slug": slug,
        "title": trip.get("title"),
        "start": trip.get("start"),
        "end": trip.get("end"),
        "days": len(trip.get("days") or []),
        "cover": cover,
        "coverImage": cover_image,
        "counts": trip.get("counts"),
        "data": f"{slug}/trip.json",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    trips.sort(key=lambda t: t.get("start") or "", reverse=True)
    body = json.dumps({"version": 1, "trips": trips}, indent=1)
    code, _, err = rclone("rcat", f"{remote}/trips.json", "--header-upload", NOCACHE,
                          "--header-upload", "Content-Type: application/json", stdin=body, capture=True)
    if code:
        sys.exit(f"Couldn't update trips.json: {err.strip()[:300]}")

    log(f"Published. {trip['counts']['items']} shots live under {slug}/ "
        f"({len(trips)} trip{'s' if len(trips) != 1 else ''} in the archive).")


if __name__ == "__main__":
    main()
