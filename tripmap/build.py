#!/usr/bin/env python3
"""
TripMap builder: point it at a folder of trip photos/videos and it produces a
self-contained map bundle (index.html + trip.js + thumbs/ + media/).

The bundle opens by double-clicking index.html (no server needed); serve.py
(the editor) serves the repo's viewer.html instead. publish.py uploads only
trip.json and the previews it uses. Originals are never modified.

Requires: Python 3.9+, Pillow, exiftool and ffmpeg on PATH.

Quick look (thumbnails only, fast):
    python build.py "<trip folder>" --name "Lisbon 2025" --tz +01:00 --quick
Full build (adds photo + 720p video previews):
    python build.py "<trip folder>" --name "Lisbon 2025" --tz +01:00

--tz (the trip's UTC offset) is required. The options are saved in
<trip>/_tripmap/build_args.json, so the editor's buttons re-run the same build.
"""
import argparse
import bisect
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
PROXY_EXT = {".lrf"}  # DJI low-res proxies: used as fast preview source, never listed
DEFAULT_OUT = "_tripmap"
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- helpers

def log(msg):
    print(msg, flush=True)


def parse_offset(s):
    """'+07:00' / '-5' / '+0745' -> timedelta"""
    m = re.fullmatch(r"\s*([+-])?(\d{1,2}):?(\d{2})?\s*", s or "")
    if not m:
        raise ValueError(f"Bad UTC offset: {s!r} (use e.g. +07:00)")
    sign = -1 if m.group(1) == "-" else 1
    return sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))


def parse_exif_dt(s):
    """'2026:10:02 22:33:12' (+optional fraction/offset/Z) -> (naive_dt, offset_or_None)"""
    if not s or not isinstance(s, str) or s.startswith("0000"):
        return None, None
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?", s)
    if not m:
        return None, None
    dt = datetime(*map(int, m.groups()[:6]))
    tz = m.group(7)
    off = None
    if tz == "Z":
        off = timedelta(0)
    elif tz:
        off = parse_offset(tz)
    return dt, off


def to_epoch(naive, offset):
    return (naive - offset).replace(tzinfo=timezone.utc).timestamp()


FNAME_DT = re.compile(r"(20\d{2})(\d{2})(\d{2})[_\-]?(\d{2})(\d{2})(\d{2})")
FNAME_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
WHATSAPP = re.compile(r"^(IMG|VID)-\d{8}-WA\d+", re.I)


def dt_from_name(name):
    m = FNAME_DT.search(name)
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()))
    except ValueError:
        return None


def short_id(rel):
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"ERROR: '{tool}' not found on PATH. Install it first (see SETUP.md).")


def read_text_any(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
            if enc == "utf-8-sig" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


# ---------------------------------------------------------------- metadata

EXIF_TAGS = ["FileName", "Directory", "FileSize", "MIMEType", "Make", "Model",
             "DateTimeOriginal", "OffsetTimeOriginal", "CreateDate", "GPSDateTime",
             "GPSLatitude", "GPSLongitude", "Duration", "ImageWidth", "ImageHeight", "FileModifyDate"]


def run_exiftool(root, out_dir):
    cmd = ["exiftool", "-r", "-json", "-n", "-q", "-q", "-fast",
           "-charset", "filename=utf8", "-api", "largefilesupport=1"]
    for e in sorted(PHOTO_EXT | VIDEO_EXT):
        cmd += ["-ext", e.lstrip(".")]
    try:
        rel_out = out_dir.resolve().relative_to(root.resolve())
        cmd += ["-i", str(rel_out.parts[0])]
    except ValueError:
        pass
    cmd += ["-" + t for t in EXIF_TAGS]
    cmd.append(str(root))
    log("Reading metadata with exiftool (one pass over the folder)...")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode not in (0, 1) or not res.stdout.strip():
        sys.exit("exiftool failed:\n" + res.stderr.decode("utf-8", "replace")[:2000])
    rows = json.loads(res.stdout.decode("utf-8", "replace"))
    log(f"  {len(rows)} media files in {time.time() - t0:.0f}s")
    return rows


def load_csv_locations(path, args):
    """Tolerant reader for a precomputed filename -> lat/lon(/time/confidence) table."""
    text = read_text_any(path)
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return {}
    cols = list(rows[0].keys())
    low = {c.lower().strip(): c for c in cols if c}

    def pick(explicit, *needles, exclude=()):
        if explicit:
            if explicit not in cols:
                sys.exit(f"Column {explicit!r} not in {path}. Columns: {cols}")
            return explicit
        for n in needles:
            for lc, c in low.items():
                if n in lc and not any(x in lc for x in exclude):
                    return c
        return None

    fcol = pick(args.csv_file_col, "filename", "file", "clip", "name", "source")
    latc = pick(args.csv_lat_col, "lat")
    lonc = pick(args.csv_lon_col, "lon", "lng")
    confc = pick(None, "confidence", "conf")
    timec = pick(args.csv_time_col, "utc", "corrected", "local_time", "datetime", "time",
                 exclude=("gap", "delta", "diff", "min", "offset", "anchor"))
    log(f"  clip CSV columns -> file={fcol!r} lat={latc!r} lon={lonc!r} "
        f"time={timec!r} conf={confc!r}")
    if not (fcol and latc and lonc):
        sys.exit(f"Couldn't identify file/lat/lon columns in {path}. Columns: {cols}\n"
                 "Pass --csv-file-col / --csv-lat-col / --csv-lon-col.")
    time_off = parse_offset(args.csv_time_tz or args.tz)
    if timec and "utc" in timec.lower():
        time_off = timedelta(0)
    out = {}
    for r in rows:
        fn = os.path.basename((r.get(fcol) or "").strip())
        if not fn:
            continue
        rec = {}
        try:
            lat, lon = float(r.get(latc) or "x"), float(r.get(lonc) or "x")
            if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                rec["lat"], rec["lon"] = lat, lon
        except ValueError:
            pass
        if confc:
            rec["conf"] = (r.get(confc) or "").strip().lower() or None
        if timec:
            dt, off = parse_exif_dt((r.get(timec) or "").strip())
            if dt:
                rec["t"] = to_epoch(dt, off if off is not None else time_off)
        out[fn.lower()] = rec
        out[Path(fn).stem.lower()] = rec
    return out


def is_dji(row, name):
    return (str(row.get("Make", "")).upper().startswith("DJI")
            or name.upper().startswith("DJI_"))


def resolve_time(row, name, kind, args, cam_off, def_off):
    """Return (epoch_utc, source) using the best available clue."""
    if kind == "video" and is_dji(row, name):
        dt = dt_from_name(name)
        if dt:
            return to_epoch(dt, cam_off), "dji-filename"
    if kind == "photo":
        dt, off = parse_exif_dt(row.get("DateTimeOriginal"))
        if dt:
            o2 = row.get("OffsetTimeOriginal")
            if o2:
                try:
                    return to_epoch(dt, parse_offset(o2)), "exif+offset"
                except ValueError:
                    pass
            g, goff = parse_exif_dt(row.get("GPSDateTime"))
            if g:  # GPS clock is UTC; trust it for the instant
                return to_epoch(g, goff or timedelta(0)), "gps-time"
            return to_epoch(dt, off if off is not None else def_off), "exif-assumed-tz"
    else:  # QuickTime CreateDate is UTC by spec
        dt, off = parse_exif_dt(row.get("CreateDate"))
        if dt:
            return to_epoch(dt, off or timedelta(0)), "quicktime-utc"
    dt = dt_from_name(name)
    if dt:
        return to_epoch(dt, def_off), "filename"
    # Date-only names (e.g. WhatsApp IMG-20261007-WA0013.jpg): use the file's
    # saved time if it falls on that date, else noon of that date.
    m = FNAME_DATE.search(name)
    if m:
        try:
            day = datetime(*map(int, m.groups()))
        except ValueError:
            return None, None
        mt, moff = parse_exif_dt(row.get("FileModifyDate"))
        if mt is not None:
            mt_epoch = to_epoch(mt, moff if moff is not None else def_off)
            mt_local = datetime.fromtimestamp(mt_epoch, timezone.utc).replace(tzinfo=None) + def_off
            if mt_local.date() == day.date():
                return mt_epoch, "date+filetime"
        return to_epoch(day.replace(hour=12), def_off), "date-only"
    return None, None


# ---------------------------------------------------------------- media work

def ffmpeg(args_list):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args_list],
                       capture_output=True)
    return r.returncode == 0, r.stderr.decode("utf-8", "replace")[-400:]


def make_photo(src, thumb, disp, size, quick):
    from PIL import Image, ImageOps
    try:
        if src.suffix.lower() in (".heic", ".heif"):
            import pillow_heif  # noqa: F401  (optional)
            pillow_heif.register_heif_opener()
        with Image.open(src) as im:
            if im.format == "JPEG":
                im.draft("RGB", (size, size))  # decode at reduced scale: faster, far less memory
            im = ImageOps.exif_transpose(im).convert("RGB")
            if not thumb.exists():
                ImageOps.fit(im, (200, 200), Image.LANCZOS).save(thumb, "JPEG", quality=78)
            if not quick and not disp.exists():
                im.thumbnail((size, size), Image.LANCZOS)
                im.save(disp, "JPEG", quality=82, optimize=True, progressive=True)
        return None
    except Exception as e:  # noqa: BLE001
        return f"{src.name}: {type(e).__name__}: {e!r}"


def make_video(src, proxy, thumb, disp, height, crf, quick, dur):
    source = proxy or src
    err = None
    if not thumb.exists():
        ss = "1" if (dur or 2) > 1.5 else "0"
        ok, e = ffmpeg(["-ss", ss, "-i", str(source), "-frames:v", "1", "-vf",
                        "scale=200:200:force_original_aspect_ratio=increase,crop=200:200",
                        "-q:v", "5", str(thumb)])
        if not ok:
            ok, e = ffmpeg(["-i", str(source), "-frames:v", "1", "-vf",
                            "scale=200:200:force_original_aspect_ratio=increase,crop=200:200",
                            "-q:v", "5", str(thumb)])
        if not ok:
            err = f"{src.name} thumb: {e}"
    if not quick and not disp.exists():
        box = int(height * 16 / 9) // 2 * 2
        tmp = disp.with_suffix(".part.mp4")
        ok, e = ffmpeg(["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                        "-vf", f"scale='min(iw,{box})':'min(ih,{box})':force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                        "-movflags", "+faststart", str(tmp)])
        if ok:
            os.replace(tmp, disp)
        else:
            tmp.unlink(missing_ok=True)
            err = f"{src.name} preview: {e}"
    return err


def make_card(kind, src, proxy, preview, card, dur):
    """~640px image for gallery cards. Built from the small previews when they exist (fast)."""
    if card.exists():
        return None
    try:
        if kind == "photo":
            from PIL import Image, ImageOps
            source = preview if preview.exists() else src
            with Image.open(source) as im:
                if source == src:
                    if im.format == "JPEG":
                        im.draft("RGB", (640, 640))
                    im = ImageOps.exif_transpose(im)
                im = im.convert("RGB")
                im.thumbnail((640, 640), Image.LANCZOS)
                im.save(card, "JPEG", quality=80, optimize=True, progressive=True)
            return None
        source = preview if preview.exists() else (proxy or src)
        ss = "1" if (dur or 2) > 1.5 else "0"
        vf = "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2"
        ok, e = ffmpeg(["-ss", ss, "-i", str(source), "-frames:v", "1", "-vf", vf, "-q:v", "4", str(card)])
        if not ok:
            ok, e = ffmpeg(["-i", str(source), "-frames:v", "1", "-vf", vf, "-q:v", "4", str(card)])
        return None if ok else f"{src.name} card: {e}"
    except Exception as e:  # noqa: BLE001
        return f"{src.name} card: {type(e).__name__}: {e!r}"


OFFSET_OPTS = ("--tz", "--assume-tz", "--camera-offset", "--csv-time-tz")


def join_negative_offsets(argv):
    """'--tz -05:00' -> '--tz=-05:00': argparse would read -05:00 as an option."""
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in OFFSET_OPTS and i + 1 < len(argv) and re.fullmatch(r"-\d{1,2}(:?\d{2})?", argv[i + 1]):
            out.append(f"{a}={argv[i + 1]}")
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "trip"


def default_contact():
    """defaults.contact from the Wander config; the build never needs a config."""
    sys.path.insert(0, str(HERE))
    import config
    try:
        cfg = config.load(required=False)
    except config.ConfigError as e:
        log(f"WARNING: ignoring the Wander config: {e}")
        return ""
    return cfg.contact if cfg else ""


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Build an interactive trip map from a media folder.")
    ap.add_argument("input", help="Folder containing photos/videos (scanned recursively)")
    ap.add_argument("--name", default=None, help="Trip title shown on the map")
    ap.add_argument("--slug", default=None, help="Short web name for this trip, e.g. lisbon-2025 (default: from --name)")
    ap.add_argument("--out", default=None, help=f"Output folder (default: <input>/{DEFAULT_OUT})")
    ap.add_argument("--tz", required=True,
                    help="Required. The trip's UTC offset, e.g. +07:00: day boundaries and displayed times")
    ap.add_argument("--assume-tz", default=None, help="Offset for photos with no zone info (default: --tz)")
    ap.add_argument("--camera-offset", default="+00:00",
                    help="DJI camera clock vs UTC, for clip times from filenames (default +00:00)")
    ap.add_argument("--clip-locations", default=None,
                    help="CSV with precomputed clip locations (default: <input>/clip_locations.csv if present)")
    ap.add_argument("--csv-file-col"); ap.add_argument("--csv-lat-col")
    ap.add_argument("--csv-lon-col"); ap.add_argument("--csv-time-col")
    ap.add_argument("--csv-time-tz", default=None, help="Zone of the CSV time column if not UTC (default: --tz)")
    ap.add_argument("--match-window", type=int, default=120,
                    help="Minutes: place un-geotagged items at the nearest geotagged item within this window (0=off)")
    ap.add_argument("--quick", action="store_true", help="Thumbnails only; skip photo/video previews")
    ap.add_argument("--data-only", action="store_true",
                    help="Only rewrite map data (trip.js + index.html); skip all thumbnail/preview work")
    ap.add_argument("--overrides", default=None,
                    help="Manual locations exported from the map's edit mode (default: <input>/overrides.json if present)")
    ap.add_argument("--photo-size", type=int, default=1600, help="Long edge of photo previews")
    ap.add_argument("--video-height", type=int, default=720, help="Video preview height (short side)")
    ap.add_argument("--crf", type=int, default=28, help="x264 quality for previews (higher = smaller)")
    ap.add_argument("--video-workers", type=int, default=2)
    ap.add_argument("--photo-workers", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--contact", default=None,
                    help="Email or link for 'Request original' in the local viewer, e.g. you@example.com "
                         "(default: defaults.contact in the Wander config, else none)")
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N items (testing)")
    args = ap.parse_args(join_negative_offsets(sys.argv[1:]))
    try:
        view_off = parse_offset(args.tz)
        def_off = parse_offset(args.assume_tz or args.tz)
        cam_off = parse_offset(args.camera_offset)
        parse_offset(args.csv_time_tz or args.tz)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    if args.contact is None:
        args.contact = default_contact()
    need("exiftool")
    need("ffmpeg")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("ERROR: Pillow missing. Run: pip install pillow")

    root = Path(args.input).resolve()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    out = Path(args.out).resolve() if args.out else root / DEFAULT_OUT
    for sub in ("thumbs", "media", "cards"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # Remember how this trip is built so the map's buttons can re-run it
    keep, skip = [], {"--quick", "--data-only"}
    raw = join_negative_offsets(sys.argv[1:])
    i = 0
    while i < len(raw):
        a = raw[i]
        if a in skip:
            i += 1
            continue
        if a == "--limit":
            i += 2
            continue
        keep.append(a)
        i += 1
    keep = [str(root) if a == args.input else a for a in keep]
    # Save the camera offset even when it's the default, so a trip never shifts
    # if the default changes (--tz is required, so it's always there).
    if not any(a == "--camera-offset" or a.startswith("--camera-offset=") for a in keep):
        keep += ["--camera-offset", args.camera_offset]
    (out / "build_args.json").write_text(json.dumps(keep), encoding="utf-8")

    csv_path = Path(args.clip_locations) if args.clip_locations else root / "clip_locations.csv"
    csv_locs = {}
    if csv_path.exists():
        log(f"Using precomputed locations: {csv_path}")
        csv_locs = load_csv_locations(csv_path, args)

    ov_path = Path(args.overrides) if args.overrides else root / "overrides.json"
    overrides, settings = {}, {}
    if ov_path.exists():
        try:
            raw = json.loads(read_text_any(ov_path))
            overrides = raw.get("overrides", raw) if isinstance(raw, dict) else {}
            settings = raw.get("settings") if isinstance(raw, dict) and "overrides" in raw else None
            settings = settings if isinstance(settings, dict) else {}
            log(f"Using {len(overrides)} manual locations from {ov_path.name}")
        except (ValueError, AttributeError) as e:
            sys.exit(f"Couldn't read {ov_path}: {e}")

    # DJI proxies (.LRF) by directory+stem
    proxies = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in PROXY_EXT and out not in p.parents:
            proxies[(str(p.parent).lower(), p.stem.lower())] = p

    rows = run_exiftool(root, out)
    items, unknown_time = [], []
    for r in rows:
        src = Path(r.get("SourceFile") or os.path.join(r.get("Directory", ""), r.get("FileName", "")))
        if out in src.resolve().parents:
            continue
        name = src.name
        ext = src.suffix.lower()
        kind = "video" if ext in VIDEO_EXT else "photo" if ext in PHOTO_EXT else None
        if not kind:
            continue
        rel = src.resolve().relative_to(root).as_posix()
        it = {"id": short_id(rel), "type": kind, "orig": name, "rel": rel,
              "_wa": bool(WHATSAPP.match(name)),
              "cam": " ".join(x for x in (r.get("Make"), r.get("Model")) if x).strip() or None}
        if kind == "video":
            try:
                it["dur"] = round(float(r.get("Duration") or 0), 1)
            except (TypeError, ValueError):
                pass
        t, tsrc = resolve_time(r, name, kind, args, cam_off, def_off)
        lat, lon = r.get("GPSLatitude"), r.get("GPSLongitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and (lat or lon):
            it.update(lat=round(lat, 6), lon=round(lon, 6), loc="gps")
        rec = csv_locs.get(name.lower()) or csv_locs.get(src.stem.lower())
        if rec is not None:
            it["in_csv"] = True
            if "t" in rec:
                t, tsrc = rec["t"], "csv"
            if "lat" in rec:
                it.update(lat=round(rec["lat"], 6), lon=round(rec["lon"], 6), loc="csv")
                if rec.get("conf"):
                    it["conf"] = rec["conf"]
        if t is None:
            unknown_time.append(name)
            continue
        it["t"] = int(t)
        it["tsrc"] = tsrc
        it["_src"] = src
        it["_proxy"] = proxies.get((str(src.parent).lower(), src.stem.lower()))
        items.append(it)

    # Manual overrides win over everything (value null = deliberately no location).
    # "archived" hides a shot from the published trip; it stays local and still
    # counts for day numbers, trip dates and as a location anchor.
    n_ov = 0
    for x in items:
        if x["rel"] in overrides:
            v = overrides[x["rel"]]
            if v is None:
                v = {"noloc": True}
            if not isinstance(v, dict):
                continue
            if v.get("lat") is not None and v.get("lon") is not None:
                for k in ("lat", "lon", "conf"):
                    x.pop(k, None)
                x.update(lat=round(float(v["lat"]), 6), lon=round(float(v["lon"]), 6), loc="manual")
            elif v.get("noloc"):
                for k in ("lat", "lon", "conf"):
                    x.pop(k, None)
                x["loc"] = "cleared"
            if v.get("t") is not None:
                x["t"], x["tsrc"] = int(v["t"]), "manual"
            if v.get("archived"):
                x["archived"] = True
            n_ov += 1
    if overrides and n_ov < len(overrides):
        log(f"  note: {len(overrides) - n_ov} overrides didn't match any file (renamed or moved?)")

    items.sort(key=lambda x: x["t"])
    loose = ("date+filetime", "date-only")
    firm = [x["t"] for x in items if x["tsrc"] not in loose]
    if firm:
        lo, hi = min(firm) - 86400, max(firm) + 86400
        outside = [x["orig"] for x in items if x["tsrc"] in loose and not lo <= x["t"] <= hi]
        if outside:
            log(f"  left out {len(outside)} date-only files outside the trip dates, e.g. {outside[:3]}")
        items = [x for x in items if x["tsrc"] not in loose or lo <= x["t"] <= hi]
    if args.limit:
        items = items[: args.limit]

    # Fill gaps from nearest geotagged item in time (not for items the CSV
    # deliberately left blank — those were judged too uncertain).
    if args.match_window > 0:
        anchors = [(x["t"], x) for x in items if x.get("loc") in ("gps", "manual")]
        ats = [a[0] for a in anchors]
        win = args.match_window * 60
        matched = 0
        for x in items:
            if "lat" in x or x.get("loc") == "cleared" or x.get("in_csv") or x.get("_wa") or not anchors:
                continue
            i = bisect.bisect_left(ats, x["t"])
            best = min((anchors[j] for j in (i - 1, i) if 0 <= j < len(anchors)),
                       key=lambda a: abs(a[0] - x["t"]))
            gap = abs(best[0] - x["t"])
            if gap <= win:
                x.update(lat=best[1]["lat"], lon=best[1]["lon"], loc="matched",
                         conf="high" if gap <= 600 else "medium" if gap <= 1800 else "low")
                matched += 1
        log(f"  matched {matched} items to nearby geotagged shots")

    # Days in display zone
    def local_day(t):
        return (datetime.fromtimestamp(t, timezone.utc) + view_off).date()

    day_keys = sorted({local_day(x["t"]) for x in items})
    first = day_keys[0] if day_keys else None
    days = []
    for d in day_keys:
        n = (d - first).days + 1
        cnt = sum(1 for x in items if local_day(x["t"]) == d and not x.get("archived"))
        days.append({"key": d.isoformat(), "n": n, "count": cnt})
    for x in items:
        x["day"] = local_day(x["t"]).isoformat()

    # Media generation
    photos = [x for x in items if x["type"] == "photo"]
    videos = [x for x in items if x["type"] == "video"]
    errors = []

    def run_pool(jobs, workers, label):
        if not jobs:
            return
        done, t0 = 0, time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(*j) for j in jobs]
            for f in as_completed(futs):
                e = f.result()
                if e:
                    errors.append(e)
                done += 1
                if done % 10 == 0 or done == len(jobs):
                    el = time.time() - t0
                    eta = el / done * (len(jobs) - done)
                    log(f"  {label}: {done}/{len(jobs)}  (~{eta/60:.0f} min left)")

    if args.data_only:
        log("--data-only: skipping thumbnails and previews")
        photos_todo, videos_todo = [], []
    else:
        photos_todo, videos_todo = photos, videos
    log(f"Building {len(photos_todo)} photo previews...")
    run_pool([(make_photo, x["_src"], out / "thumbs" / f"{x['id']}.jpg",
               out / "media" / f"{x['id']}.jpg", args.photo_size, args.quick) for x in photos_todo],
             args.photo_workers, "photos")
    failed = [e.split(":")[0] for e in errors]
    if failed:
        log(f"  retrying {len(failed)} photos one at a time...")
        retry = [x for x in photos_todo if x["orig"] in failed]
        errors[:] = [e for e in errors if e.split(":")[0] not in failed]
        run_pool([(make_photo, x["_src"], out / "thumbs" / f"{x['id']}.jpg",
                   out / "media" / f"{x['id']}.jpg", args.photo_size, args.quick) for x in retry],
                 1, "retry")
    log(f"Building {len(videos_todo)} video previews"
        f"{' (thumbnails only)' if args.quick else ''}... (uses .LRF proxies where available)")
    run_pool([(make_video, x["_src"], x["_proxy"], out / "thumbs" / f"{x['id']}.jpg",
               out / "media" / f"{x['id']}.mp4", args.video_height, args.crf, args.quick,
               x.get("dur")) for x in videos_todo],
             args.video_workers, "videos")

    if not args.data_only:
        todo = [x for x in items if not (out / "cards" / f"{x['id']}.jpg").exists()]
        log(f"Building {len(todo)} gallery images...")
        run_pool([(make_card, x["type"], x["_src"], x.get("_proxy"),
                   out / "media" / f"{x['id']}.{'mp4' if x['type'] == 'video' else 'jpg'}",
                   out / "cards" / f"{x['id']}.jpg", x.get("dur")) for x in todo],
                 args.photo_workers, "gallery")

    # Write data + viewer
    clean = []
    for x in items:
        ext = "mp4" if x["type"] == "video" else "jpg"
        media = out / "media" / f"{x['id']}.{ext}"
        thumb = out / "thumbs" / f"{x['id']}.jpg"
        y = {k: v for k, v in x.items() if not k.startswith("_") and k not in ("in_csv",)}
        y["thumb"] = f"thumbs/{x['id']}.jpg" if thumb.exists() else None
        y["media"] = f"media/{x['id']}.{ext}" if media.exists() else None
        card = out / "cards" / f"{x['id']}.jpg"
        y["card"] = None
        if card.exists():
            y["card"] = f"cards/{x['id']}.jpg"
            try:
                from PIL import Image
                with Image.open(card) as im:
                    y["ar"] = round(im.width / im.height, 3)
            except Exception:  # noqa: BLE001
                pass
        clean.append(y)

    def pick_cover(cands):
        # Middle of all candidates (archived included, so the pick stays put); if
        # that shot is archived, the next eligible one after it, then before it.
        mid = len(cands) // 2
        return next((y for y in cands[mid:] + cands[:mid][::-1] if not y.get("archived")), None)
    auto = pick_cover([y for y in clean if y["type"] == "photo" and y.get("card") and y.get("lat") is not None]) \
        or pick_cover([y for y in clean if y.get("card")])
    # A chosen cover (editor: Set as cover) wins if it's a published photo. It's
    # never cleared by archiving, so Restore brings it back.
    chosen_rel = settings.get("cover") if isinstance(settings.get("cover"), str) else None
    cover_item = auto
    if chosen_rel:
        c = next((y for y in clean if y["rel"] == chosen_rel), None)
        why = ("is missing (moved, renamed or not built yet)" if not c or not c.get("card") else
               "is a video" if c["type"] != "photo" else "is archived" if c.get("archived") else None)
        if why:
            log(f"WARNING: the chosen cover {chosen_rel} {why}; using the automatic pick.")
        else:
            cover_item = c
    cover = cover_item["card"] if cover_item else None

    title = args.name or root.name
    slug = args.slug or slugify(title)
    data = {
        "title": title,
        "slug": slug,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tzOffsetMin": int(view_off.total_seconds() // 60),
        "contact": args.contact,
        "coverRel": chosen_rel,
        "autoCover": auto["id"] if auto else None,
        "days": days,
        "items": clean,
    }
    (out / "trip.js").write_text("window.TRIP = " + json.dumps(data, separators=(",", ":")) + ";\n",
                                 encoding="utf-8")
    # Only for opening the bundle straight from disk (file://). serve.py ignores
    # this copy and serves the repo's viewer.html, so editor changes show on refresh.
    shutil.copyfile(HERE / "viewer.html", out / "index.html")

    # Public data for the website (no local folder paths or camera details)
    PUBLIC = ("id", "type", "t", "day", "lat", "lon", "loc", "conf", "dur", "orig", "thumb", "card", "ar", "media")
    # Archived shots are left out entirely; day numbers and trip dates still come
    # from every shot, so archiving never renumbers days.
    pub_items = [{k: y[k] for k in PUBLIC if y.get(k) is not None} for y in clean if not y.get("archived")]
    pub_days = [d for d in days if d["count"]]
    day_n = {d["key"]: d["n"] for d in days}
    for y in pub_items:
        y["dayN"] = day_n.get(y["day"])
    public = {
        "version": 1,
        "title": title,
        "slug": slug,
        "generated": data["generated"],
        "tzOffsetMin": data["tzOffsetMin"],
        "start": days[0]["key"] if days else None,
        "end": days[-1]["key"] if days else None,
        "cover": cover,
        "counts": {"items": len(pub_items), "photos": sum(1 for y in pub_items if y["type"] == "photo"),
                   "videos": sum(1 for y in pub_items if y["type"] == "video"),
                   "onMap": sum(1 for y in pub_items if y.get("lat") is not None)},
        "days": pub_days,
        "items": pub_items,
    }
    (out / "trip.json").write_text(json.dumps(public, separators=(",", ":")), encoding="utf-8")

    # Summary
    placed = sum(1 for x in clean if "lat" in x)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    by_loc = {}
    for x in clean:
        by_loc[x.get("loc", "none")] = by_loc.get(x.get("loc", "none"), 0) + 1
    log("\nDone.")
    log(f"  items: {len(clean)}  ({len(photos)} photos, {len(videos)} videos) across {len(days)} days")
    log(f"  on the map: {placed}   location source: {by_loc}")
    n_arch = sum(1 for x in clean if x.get("archived"))
    if n_arch:
        log(f"  archived (kept locally, not published): {n_arch}")
    log(f"  bundle size: {size/1e9:.2f} GB  ->  {out}")
    if unknown_time:
        log(f"  skipped (no usable time): {len(unknown_time)} e.g. {unknown_time[:3]}")
    if errors:
        (out / "build_errors.txt").write_text("\n".join(errors), encoding="utf-8")
        log(f"  {len(errors)} errors -> build_errors.txt")
    log(f"\nOpen: {out / 'index.html'}")


if __name__ == "__main__":
    main()
