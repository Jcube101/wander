#!/usr/bin/env python3
"""
Copy someone's favourites in a trip, as the original files, into a folder you can hand over.

    python export_favs.py "<trip folder>"                              # your own (owner_email in the config)
    python export_favs.py "<trip folder>" --email friend@example.com   # someone else's
    python export_favs.py "<trip folder>" --dry-run                    # list only
    python export_favs.py "<trip folder>" --out "D:/Exports"           # default: your Downloads folder

Reads the person's favourites from R2 (rclone cat: read-only), finds the originals
through the trip's local data (_tripmap/trip.js) and copies them (full-resolution
photos, full camera MP4s; never .LRF proxies) into <out>/<slug>-favourites-<name>/,
named like the site's downloads: <YYYY-MM-DD_HHMM>_<original name>.<ext>, the time
in the trip's zone. Prints the count and size first and asks y/N.

The favourites file is favs/<slug>/<sha256(salt + lowercase email)>.json, as the
Worker names it; the salt is the Worker secret FAVS_SALT, read from
~/.wander/favs-salt and never printed. Never uploads, changes or deletes anything,
on R2 or in the trip folder. A file already in the folder at the same size is
skipped, so an interrupted export can simply be run again.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

REPO = HERE.parent
SALT_FILE = Path.home() / ".wander" / "favs-salt"
NAME_MAX = 80
PLACEHOLDER = "you@example.com"  # wander.config.example.json's owner_email


def log(msg=""):
    print(msg, flush=True)


def favs_key(slug, salt, email):
    """The person's favourites file in the bucket, named exactly as the Worker names it."""
    digest = hashlib.sha256((salt + email.strip().lower()).encode("utf-8")).hexdigest()
    return f"favs/{slug}/{digest}.json"


def clean(s, limit=NAME_MAX):
    """A-Z a-z 0-9 . _ - only (accents dropped, anything else -> "_"), trimmed, at most `limit`."""
    s = unicodedata.normalize("NFKD", s if isinstance(s, str) else "")
    s = re.sub(r"[\u0300-\u036f]", "", s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    return s[:limit].rstrip("._-")


def download_name(orig, t, tz, item_id, ext):
    """<YYYY-MM-DD_HHMM>_<original name without extension>.<ext>, the time in the trip's zone.
    The Worker's Content-Disposition and the sites use the same rule (SPEC.md -> Downloads)."""
    s = orig if isinstance(orig, str) else ""
    dot = s.rfind(".")
    base = clean(s[:dot] if dot > 0 else s) or item_id
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        return f"{base}.{ext}"
    when = datetime.fromtimestamp(t + (tz or 0) * 60, timezone.utc)
    return f"{when:%Y-%m-%d_%H%M}_{base}.{ext}"


def unique_name(name, used):
    """name, or name_2, name_3 ... before the extension, unused so far (case-insensitive,
    as on Windows and macOS). Adds the result to `used`."""
    dot = name.rfind(".")
    stem, ext = (name[:dot], name[dot:]) if dot > 0 else (name, "")
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{stem}_{n}{ext}"
        n += 1
    used.add(candidate.lower())
    return candidate


def gb(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


def read_salt(path=None):
    path = Path(path or SALT_FILE)
    try:
        salt = path.read_text(encoding="utf-8").strip()
    except OSError:
        salt = ""
    if not salt:
        sys.exit(f"ERROR: no favourites salt in {path}. It's the Worker secret FAVS_SALT; "
                 f"see SETUP.md -> Favourites (a new salt would orphan everyone's favourites).")
    return salt


def read_trip(root):
    """The trip's local data (_tripmap/trip.js: has each item's path in the trip folder)."""
    path = root / "_tripmap" / "trip.js"
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))
    except (OSError, ValueError) as e:
        sys.exit(f"ERROR: can't read {path} ({e}). Build the trip first (the editor's Apply to map).")


def read_favourites(remote, key):
    """The ids in the person's favourites file on R2, or None if there's no such file.
    rclone cat only: reads, never writes."""
    cmd = ["rclone", "cat", f"{remote}/{key}", "--s3-no-check-bucket"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        if "not found" in (r.stderr or "").lower():
            return None
        sys.exit(f"ERROR: couldn't read the favourites from R2: {(r.stderr or '').strip()[:300] or f'rclone exit {r.returncode}'}")
    if not r.stdout.strip():
        return None
    try:
        ids = json.loads(r.stdout).get("ids")
    except (ValueError, AttributeError):
        sys.exit("ERROR: the favourites file on R2 isn't valid JSON.")
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def inside(path, folder):
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def confirm(prompt):
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def default_out():
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy someone's favourites in a trip, as originals, into a folder.")
    ap.add_argument("trip", help="Trip folder (the one with the originals and _tripmap/)")
    ap.add_argument("--email", default=None, help="Whose favourites (the email they sign in with). Default: owner_email in the config")
    ap.add_argument("--out", default=None, help="Where to put the folder (default: your Downloads folder)")
    ap.add_argument("--dry-run", action="store_true", help="List what would be copied; copy nothing")
    args = ap.parse_args(argv)
    try:  # a non-UTF-8 console must never crash over a file name
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        cfg = config.load()
    except config.ConfigError as e:
        sys.exit(f"ERROR: {e}")
    email = (args.email if args.email is not None else cfg.owner_email).strip()
    if not email:
        sys.exit(f"ERROR: whose favourites? Pass --email, or set owner_email in {cfg.path}.")
    if args.email is None and email.lower() == PLACEHOLDER:
        sys.exit(f"ERROR: owner_email in {cfg.path} is still the example ({PLACEHOLDER}). "
                 f"Put the email you sign in with there, or pass --email.")
    if not config.EMAIL.fullmatch(email):
        sys.exit(f"ERROR: {email!r} doesn't look like an email address.")
    if not shutil.which("rclone"):
        sys.exit("rclone isn't installed or not on PATH. Install it: https://rclone.org/install/")
    salt = read_salt()

    root = Path(args.trip).resolve()
    trip = read_trip(root)
    slug, tz = trip.get("slug"), trip.get("tzOffsetMin") or 0
    if not slug:
        sys.exit("ERROR: the trip's data has no slug. Re-run the build.")
    out = Path(args.out).expanduser().resolve() if args.out else default_out()
    dest = out / f"{slug}-favourites-{clean(email.split('@')[0]) or 'someone'}"
    if inside(dest, root):
        sys.exit(f"ERROR: {dest} is inside the trip folder; the next Scan would add the copies to the trip. "
                 f"Pick another --out.")
    if inside(dest, REPO):
        sys.exit(f"ERROR: {dest} is inside the Wander repo; originals don't belong there. Pick another --out.")

    log(f"Favourites of {email} in '{trip.get('title') or slug}' ({slug})")
    ids = read_favourites(cfg.remote.rstrip("/"), favs_key(slug, salt, email))
    if ids is None:
        log(f"  None: {email} has no favourites in this trip (check it's the email they sign in with).")
        return 0

    by_id = {x.get("id"): x for x in trip.get("items", [])}
    unknown, archived, missing, plan = [], [], [], []
    for i in dict.fromkeys(ids):  # once each, in their order
        x = by_id.get(i)
        if x is None:
            unknown.append(i)
        elif x.get("archived"):
            archived.append(x)
        else:
            src = root / x.get("rel", "")
            if x.get("rel") and src.is_file() and src.suffix.lower() != ".lrf":
                plan.append((x, src, src.stat().st_size))
            else:
                missing.append(x)
    plan.sort(key=lambda p: p[0].get("t") or 0)
    used = set()
    plan = [(x, src, size, unique_name(download_name(x.get("orig"), x.get("t"), tz, x["id"],
                                                     src.suffix.lower().lstrip(".")), used))
            for x, src, size in plan]
    total = sum(p[2] for p in plan)

    log(f"  {len(plan)} originals, {gb(total)} -> {dest}")
    if unknown:
        log(f"  WARNING: {len(unknown)} favourite(s) aren't in this trip's local data (removed or renamed since?); skipped.")
    if archived:
        log(f"  Skipped {len(archived)} archived shot(s) (not in the published trip): "
            + ", ".join(x.get("rel", "?") for x in archived))
    for x in missing:
        log(f"  WARNING: original missing, skipped: {x.get('rel') or x.get('orig')}")
    if args.dry_run:
        for x, src, size, name in plan:
            log(f"    {name}  ({gb(size)})  <- {x.get('rel')}")
        log("Dry run: nothing copied.")
        return 0
    if not plan:
        log("Nothing to copy.")
        return 0

    need = sum(size for *_, size, name in plan if not (dest / name).exists())
    probe = dest
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if need > free:
        sys.exit(f"ERROR: that needs {gb(need)}, but only {gb(free)} is free at {probe}. Pick another --out.")
    if not confirm(f"Copy {len(plan)} files ({gb(total)}) to {dest}?"):
        log("Nothing copied.")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    copied = already = clashes = 0
    for n, (x, src, size, name) in enumerate(plan, 1):
        target = dest / name
        if target.exists():
            if target.stat().st_size == size:
                already += 1
            else:
                clashes += 1
                log(f"  WARNING: {name} is already there with a different size; left as it is.")
            continue
        log(f"  [{n}/{len(plan)}] {name} ({gb(size)})")
        part = target.with_name(name + ".part")
        shutil.copy2(src, part)  # reads the original; keeps its modified time
        os.replace(part, target)
        copied += 1
    log(f"Done: {copied} copied" + (f", {already} already there" if already else "")
        + (f", {clashes} left as they were" if clashes else "") + f".\n  {dest}")
    log("Share the folder however you like (a USB stick, a shared cloud folder, AirDrop).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
