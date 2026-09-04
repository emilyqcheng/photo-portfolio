#!/usr/bin/env python3
"""
build_data.py — generates data/photos.json for the portfolio site.

WHAT IT DOES
    Reads two sources and merges them:
      1. images/full/*.jpg  -> camera settings + dimensions, read from EXIF
      2. data/captions.json -> titles, locations, notes, and display order (yours)
    Writes:
      3. data/photos.json   -> the single file the website fetches

WHY IT'S SPLIT THIS WAY
    Machine-readable facts (aperture, ISO, pixel dimensions) should never be
    typed by hand — they already exist inside the files. Human judgement
    (what to call a photo, what to say about it) can't be extracted from
    anything. So each lives in its own place, and this script joins them.

    This script only ever WRITES to data/photos.json. It never modifies
    captions.json. That means you can re-run it as often as you like —
    after adding photos, after re-exporting, after reordering — and your
    writing is never at risk. Generated files are disposable; source files
    are precious. Keep the line between them sharp.

USAGE
    python3 build_data.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ExifTags
except ImportError:
    sys.exit("Pillow is not installed. Run:  conda install -y pillow")


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Path(__file__).parent = the folder this script lives in. Building paths
# relative to the script (rather than to wherever you happen to be standing
# in the terminal) means the script works no matter which directory you run
# it from. Hardcoded absolute paths like /Users/emilycheng/... would break
# on any other machine, including a fresh clone of your own repo.
ROOT = Path(__file__).parent

FULL_DIR = ROOT / "images" / "full"
THUMB_DIR = ROOT / "images" / "thumbs"
CAPTIONS_FILE = ROOT / "data" / "captions.json"
OUTPUT_FILE = ROOT / "data" / "photos.json"

# Display names for each category key. The keys must match captions.json.
CATEGORY_LABELS = {
    "nature": "Nature & Wildlife",
    "city": "City & Culture",
    "food": "Food",
    "people": "People & Pets",
}


# ---------------------------------------------------------------------------
# EXIF HELPERS
# ---------------------------------------------------------------------------

def format_shutter(exposure_time):
    """Turn EXIF's decimal seconds into what a photographer would write.

    EXIF stores 1/2000s as the float 0.0005, which is correct but unreadable.
    Long exposures stay as seconds ("2.5s"); short ones become fractions.
    """
    if not exposure_time:
        return None
    seconds = float(exposure_time)
    if seconds >= 1:
        # Strip a pointless trailing zero: 2.0s -> 2s
        return f"{seconds:g}s"
    return f"1/{round(1 / seconds)}"


def format_aperture(f_number):
    """5.6 -> 'f/5.6', and 8.0 -> 'f/8' rather than 'f/8.0'."""
    if not f_number:
        return None
    # :g drops insignificant trailing zeros
    return f"f/{float(f_number):g}"


def format_focal(focal_length):
    """180.0 -> '180mm'."""
    if not focal_length:
        return None
    return f"{float(focal_length):g}mm"


def clean_camera(make, model):
    """'NIKON CORPORATION' + 'NIKON D3300' -> 'Nikon D3300'.

    Camera manufacturers write the make in shouty caps and often repeat it
    inside the model string, so naive concatenation gives you
    'NIKON CORPORATION NIKON D3300'.
    """
    if not model:
        return None
    model = str(model).strip()
    if make:
        # Take just the first word of the make ('NIKON' from 'NIKON CORPORATION')
        brand = str(make).strip().split()[0]
        if model.upper().startswith(brand.upper()):
            # Model already contains the brand — just fix the capitalisation
            return brand.capitalize() + model[len(brand):]
        return f"{brand.capitalize()} {model}"
    return model


def read_exif(path):
    """Pull the fields we display from one image file.

    Returns a dict. Every value may be None — a photo that lost its metadata
    should still appear on the site, just without a settings panel.
    """
    data = {
        "width": None, "height": None, "aspect": None,
        "camera": None, "lens": None,
        "focal": None, "aperture": None, "shutter": None, "iso": None,
        "date": None, "date_display": None,
    }

    with Image.open(path) as img:
        # Dimensions come from the file itself, not EXIF, so they're always
        # available. The gallery layout needs the aspect ratio to size each
        # photo before it downloads — that's what prevents the page from
        # jumping around as images arrive.
        data["width"], data["height"] = img.size
        data["aspect"] = round(img.size[0] / img.size[1], 4)

        exif = img.getexif()
        if not exif:
            return data

        # Top-level block: make, model, software
        top = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}

        # Exposure settings live in a NESTED block called the Exif IFD
        # (Image File Directory). This is the trap that makes people think
        # their files have no EXIF: reading only the top level finds no
        # aperture, no ISO, no shutter speed.
        try:
            ifd = {ExifTags.TAGS.get(k, k): v
                   for k, v in exif.get_ifd(ExifTags.IFD.Exif).items()}
        except Exception:
            ifd = {}

        data["camera"] = clean_camera(top.get("Make"), top.get("Model"))
        data["lens"] = str(ifd["LensModel"]).strip() if ifd.get("LensModel") else None

        # Use FNumber and ExposureTime, NOT ApertureValue and ShutterSpeedValue.
        # The *Value variants are APEX numbers — logarithmic encodings. An
        # ApertureValue of 4.97 means f/5.6, not f/4.97.
        data["aperture"] = format_aperture(ifd.get("FNumber"))
        data["shutter"] = format_shutter(ifd.get("ExposureTime"))
        data["focal"] = format_focal(ifd.get("FocalLength"))

        iso = ifd.get("ISOSpeedRatings") or ifd.get("PhotographicSensitivity")
        if iso:
            # Some cameras write this as a tuple
            data["iso"] = int(iso[0] if isinstance(iso, tuple) else iso)

        # DateTimeOriginal = when you pressed the shutter.
        # DateTime = when Lightroom last wrote the file. Always want the former.
        raw_date = ifd.get("DateTimeOriginal") or top.get("DateTime")
        if raw_date:
            try:
                dt = datetime.strptime(str(raw_date), "%Y:%m:%d %H:%M:%S")
                data["date"] = dt.strftime("%Y-%m-%d")          # for sorting
                data["date_display"] = dt.strftime("%B %-d, %Y")  # for humans
            except ValueError:
                pass  # unparseable date is not worth crashing over

        # Note what we deliberately DON'T copy: BodySerialNumber. It's in your
        # files, but this output becomes a public file on the internet, and
        # your camera's serial number has no business being there. When a
        # script turns private files into published data, decide what crosses
        # that line on purpose rather than by accident.

    return data


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    if not CAPTIONS_FILE.exists():
        sys.exit(f"Missing {CAPTIONS_FILE}")

    with open(CAPTIONS_FILE, encoding="utf-8") as f:
        captions = json.load(f)

    photos = []
    problems = {"no_full": [], "no_thumb": [], "no_title": [], "no_location": []}

    for category, entries in captions.items():
        # Skip the "_readme" key — it's documentation, not data
        if category.startswith("_"):
            continue

        if category not in CATEGORY_LABELS:
            print(f"  ! unknown category '{category}' in captions.json — skipped")
            continue

        for index, entry in enumerate(entries):
            filename = entry["file"]
            full_path = FULL_DIR / filename

            # A photo listed in captions.json but not yet exported is normal
            # while you're mid-export. Record it and move on rather than
            # crashing — a build script that dies on the first missing file
            # is useless during exactly the period you need it most.
            if not full_path.exists():
                problems["no_full"].append(filename)
                continue

            if not (THUMB_DIR / filename).exists():
                problems["no_thumb"].append(filename)

            if not entry.get("title"):
                problems["no_title"].append(filename)
            if not entry.get("location"):
                problems["no_location"].append(filename)

            exif = read_exif(full_path)

            photos.append({
                "id": filename.rsplit(".", 1)[0],   # 'nature-001'
                "category": category,
                "categoryLabel": CATEGORY_LABELS[category],
                "order": index,
                "full": f"images/full/{filename}",
                "thumb": f"images/thumbs/{filename}",
                "title": entry.get("title", ""),
                "location": entry.get("location", ""),
                "notes": entry.get("notes", ""),
                # alt text for screen readers and for when an image fails to load
                "alt": entry.get("title") or f"Photograph, {CATEGORY_LABELS[category]}",
                **exif,
            })

    # Flag exported files that nothing in captions.json refers to — usually a
    # filename typo or a photo you forgot to add an entry for.
    if FULL_DIR.exists():
        listed = {e["file"] for k, v in captions.items()
                  if not k.startswith("_") for e in v}
        orphans = sorted(p.name for p in FULL_DIR.glob("*.jpg")
                         if p.name not in listed)
    else:
        orphans = []

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        # ensure_ascii=False keeps Jökulsárlón and 峨眉山 as real characters
        # instead of \u escapes. indent=2 makes the file readable and gives
        # git meaningful line-by-line diffs.
        json.dump({
            "categories": CATEGORY_LABELS,
            "photos": photos,
        }, f, ensure_ascii=False, indent=2)

    # ---- report -----------------------------------------------------------
    print(f"\n  Wrote {OUTPUT_FILE.relative_to(ROOT)} — {len(photos)} photos\n")

    for cat, label in CATEGORY_LABELS.items():
        n = sum(1 for p in photos if p["category"] == cat)
        print(f"    {label:<20} {n:>3}")

    def report(key, message):
        # Accepts either a key into `problems` or a ready-made list.
        # Checking isinstance is necessary because a list is unhashable and
        # `key in problems` would raise TypeError on one.
        items = problems[key] if isinstance(key, str) else key
        if items:
            print(f"\n  {message} ({len(items)})")
            for name in items[:8]:
                print(f"    - {name}")
            if len(items) > 8:
                print(f"    ... and {len(items) - 8} more")

    report("no_full", "Listed in captions.json but not exported yet")
    report("no_thumb", "Missing a thumbnail (full exists, thumb doesn't)")
    report("no_title", "No title yet")
    report("no_location", "No location — these won't get a map pin")
    report(orphans, "Exported but not in captions.json (typo?)")

    missing_exif = [p["id"] for p in photos if not p["camera"]]
    report(missing_exif, "No EXIF — metadata was stripped on export")

    print()


if __name__ == "__main__":
    main()
