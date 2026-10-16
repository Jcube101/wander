#!/usr/bin/env python3
"""
Publish a built trip to Cloudflare R2 (or any rclone remote).

    python publish.py "D:\\2026_ Thailand Trip"            # uses r2:trip-media
    python publish.py "D:\\2026_ Thailand Trip" --dry-run  # show the plan, change nothing

Uploads <trip>/_tripmap to <remote>/<slug>/ and updates <remote>/trips.json,
the list of trips the Wander site shows on its home page.

Refuses to publish unless Cloudflare Access already guards the trip, so a new
trip is never briefly public (--allow-unprotected skips this check).

Only files trip.json references are uploaded, so archived shots never leave the
disk. Order matters so the site never points at files that aren't there yet:
  1. thumbnails, gallery images, previews (cached by browsers for a week)
  2. trip.json                             (never cached, so fixes show at once)
  3. delete remote previews trip.json no longer references (archived/removed
     shots); only after 1 and 2 succeeded, and refused if it's > 20% of the trip
     unless --allow-mass-delete
  4. covers and trips.json                 (never cached)
Only new or changed files are sent.
"""
import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LONG = "Cache-Control: public, max-age=604800"
NOCACHE = "Cache-Control: no-cache"
DATA_FILES = ("trip.json",)
PREVIEW_DIRS = ("thumbs/", "cards/", "media/")
MAX_DELETE_SHARE = 0.20
MEDIA_HOST = "media.job-joseph.com"
# What Access answers a visitor without a cookie. The Worker itself never
# redirects or refuses trip.json, so these mean the trip's Access app exists.
PROTECTED = (302, 401, 403)
# R2 storage check: warn only, never blocks a publish. Cloudflare bills decimal GB.
GB = 1e9
STORAGE_WARN_GB = 8
FREE_TIER_GB = 10


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


def check_protected(slug, host=MEDIA_HOST, timeout=15):
    """Ask for the trip's data as a stranger would (no cookies, no redirects).
    Returns (protected, status); status is the HTTP code or the error text."""
    conn = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        conn.request("GET", f"/{slug}/trip.json", headers={"User-Agent": "wander-publish"})
        status = conn.getresponse().status
    except (OSError, http.client.HTTPException) as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        conn.close()
    return status in PROTECTED, status


def referenced_files(trip):
    """Preview paths (relative to <slug>/) that the published trip.json points at."""
    refs = {x[k] for x in trip.get("items", []) for k in ("thumb", "card", "media") if x.get(k)}
    if trip.get("cover"):
        refs.add(trip["cover"])
    return sorted(r for r in refs if r.startswith(PREVIEW_DIRS))


def remote_previews(dst):
    """Preview files currently on the remote under <slug>/, as {path: bytes}
    ({} for a new trip)."""
    code, out, err = rclone("lsf", "-R", "--files-only", "--format", "sp", dst, capture=True)
    if code:
        if "directory not found" in err.lower():
            return {}
        sys.exit(f"ERROR: couldn't list {dst}: {err.strip()[:300]}")
    files = {}
    for line in out.splitlines():
        size, _, path = line.strip().partition(";")
        if path.startswith(PREVIEW_DIRS):
            files[path] = int(size) if size.isdigit() else 0
    return dict(sorted(files.items()))


def bucket_size(remote):
    """Bytes used by the whole bucket, or (None, reason) if rclone can't tell."""
    code, out, err = rclone("size", remote, "--json", capture=True)
    try:
        if code:
            raise ValueError(err.strip()[:200] or f"rclone exit {code}")
        return int(json.loads(out)["bytes"]), None
    except (ValueError, KeyError, TypeError) as e:
        return None, str(e) or type(e).__name__


def storage_report(now, upload_bytes, delete_bytes):
    """The storage line plus a warning (or None) for the projected size."""
    after = now + upload_bytes - delete_bytes
    line = f"R2 storage: {now / GB:.2f} GB now → {after / GB:.2f} GB after publish (free tier {FREE_TIER_GB} GB)"
    if after > FREE_TIER_GB * GB:
        warn = (f"WARNING: R2 will be over the {FREE_TIER_GB} GB free tier and start costing money "
                f"(a few cents per GB per month). Archive shots or rebuild smaller previews "
                f"(--crf 30 or --video-height 540).")
    elif after > STORAGE_WARN_GB * GB:
        warn = (f"WARNING: R2 storage is getting close to the {FREE_TIER_GB} GB free tier. Consider smaller "
                f"previews (--crf 30 or --video-height 540) or archiving shots.")
    else:
        warn = None
    return line, warn


def too_many_deletes(deletes, remote_files):
    return bool(remote_files) and len(deletes) / len(remote_files) > MAX_DELETE_SHARE


def write_list(paths):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="\n")
    f.write("".join(p + "\n" for p in paths))
    f.close()
    return f.name


def main():
    ap = argparse.ArgumentParser(description="Publish a built trip to R2 via rclone.")
    ap.add_argument("trip", nargs="?", default=None, help="Trip folder (default: the folder containing TripMap)")
    ap.add_argument("--remote", default="r2:trip-media", help="rclone remote and bucket (default r2:trip-media)")
    ap.add_argument("--transfers", type=int, default=16, help="Files uploaded in parallel (default 16)")
    ap.add_argument("--allow-unprotected", action="store_true",
                    help="Publish even if no Cloudflare Access app guards this trip yet")
    ap.add_argument("--allow-mass-delete", action="store_true",
                    help=f"Allow removing more than {MAX_DELETE_SHARE:.0%} of the trip's files from the remote")
    ap.add_argument("--dry-run", action="store_true", help="Run the checks and print the plan; change nothing")
    ap.add_argument("-v", "--verbose", action="store_true", help="List every removed file")
    args = ap.parse_args()
    try:  # a non-UTF-8 console or pipe must never crash a publish over the → in a log line
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

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
    if args.allow_unprotected:
        log(f"WARNING: skipping the Access check; {slug} may be visible to anyone.")
    else:
        protected, status = check_protected(slug)
        if not protected:
            how = f"got {status}" if isinstance(status, int) else f"couldn't check: {status}"
            sys.exit(f"ERROR: {slug} isn't protected by Cloudflare Access ({how}). "
                     f"Create the Access app for {slug} first, see docs/runbook.md"
                     f"{'' if isinstance(status, int) else ' (or use --allow-unprotected)'}")
        log(f"Access check: {slug} is protected ({status}).")
    remote = args.remote.rstrip("/")
    dst = f"{remote}/{slug}"
    stats = ["--stats", "3s", "--stats-one-line", "--stats-log-level", "NOTICE"]
    speed = ["--transfers", str(args.transfers), "--checkers", "16", "--s3-upload-concurrency", "4"]

    # Plan (read-only): what to upload, what's missing locally, what to remove.
    refs = referenced_files(trip)
    missing = [r for r in refs if not (out / r).exists()]
    uploads = [r for r in refs if r not in set(missing)]
    remote_files = remote_previews(dst)
    deletes = sorted(set(remote_files) - set(refs))
    # Bucket size after this publish: new files go up, unused ones come off.
    # Files already on R2 are replaced, so they're counted as no change.
    now, why = bucket_size(remote)
    storage = []
    if now is None:
        log(f"WARNING: couldn't check R2 storage ({why}); publishing anyway.")
    else:
        up_bytes = sum((out / r).stat().st_size for r in uploads if r not in remote_files)
        line, warn = storage_report(now, up_bytes, sum(remote_files[d] for d in deletes))
        storage = [line] + ([warn] if warn else [])
        for s in storage:
            log(s)
    if missing:
        log(f"WARNING: {len(missing)} file(s) trip.json references are missing from {out} "
            f"(not uploaded; run Scan for new files): " + ", ".join(missing))
    blocked = too_many_deletes(deletes, remote_files) and not args.allow_mass_delete
    stop_msg = (f"ERROR: publishing would remove {len(deletes)} of {len(remote_files)} files from {dst} "
                f"(over {MAX_DELETE_SHARE:.0%}). Nothing was changed. Check the archived shots, then run "
                f"publish.py with --allow-mass-delete from a terminal if this is intended.")

    if args.dry_run:
        log(f"Dry run for '{trip.get('title')}' -> {dst} (nothing will be changed)")
        log(f"  upload: {len(uploads)} referenced files (only new or changed ones are sent)")
        log(f"  then: trip.json, covers, trips.json")
        log(f"  remove: {len(deletes)} of {len(remote_files)} remote files no longer referenced"
            + (":" if deletes else ""))
        for d in deletes:
            log(f"    {d}")
        if blocked:
            log("  A real publish would STOP here: " + stop_msg.split(": ", 1)[1])
        return
    if blocked:
        sys.exit(stop_msg)

    log(f"Publishing '{trip.get('title')}' to {dst}")
    log("1/4 Uploading thumbnails, gallery images and previews (only new or changed ones)...")
    up_list = write_list(uploads)
    try:
        code, _, err = rclone("copy", str(out), dst, "--files-from", up_list,
                              "--header-upload", LONG, *speed, *stats)
    finally:
        os.unlink(up_list)
    if code:
        sys.exit(f"Upload failed: {err or f'rclone exit {code}'}")

    log("2/4 Uploading the map data...")
    inc = []
    for f in DATA_FILES:
        inc += ["--include", f]
    code, _, err = rclone("copy", str(out), dst, *inc, "--header-upload", NOCACHE, "--no-traverse", *stats)
    if code:
        sys.exit(f"Data upload failed: {err or f'rclone exit {code}'}")

    # Only reached when 1 and 2 succeeded: the site no longer points at these.
    log("3/4 Removing previews the trip no longer uses (archived or removed shots)...")
    delete_err = None
    if deletes:
        del_list = write_list(deletes)
        try:
            code, _, err = rclone("delete", dst, "--files-from", del_list, *stats)
        finally:
            os.unlink(del_list)
        if code:
            delete_err = err or f"rclone exit {code}"
            log(f"  couldn't remove them: {delete_err}")
        else:
            log(f"  removed {len(deletes)} file{'s' if len(deletes) != 1 else ''}")
            if args.verbose:
                for d in deletes:
                    log(f"    {d}")
    else:
        log("  nothing to remove")

    log("4/4 Updating the landing page (cover images and list of trips)...")
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

    if delete_err:
        sys.exit(f"ERROR: published, but couldn't remove {len(deletes)} unused files ({delete_err}). "
                 f"The site no longer shows them; publish again to retry.")
    log(f"Published. {trip['counts']['items']} shots live under {slug}/ "
        f"({len(trips)} trip{'s' if len(trips) != 1 else ''} in the archive).")
    for s in storage:  # again, so it's in the editor's last log lines
        log(s)


if __name__ == "__main__":
    main()
