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
import re
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

# Used to build the copyright line. Change this and every photo updates.
OWNER = "Emily Cheng"

# LENS NAME NORMALISATION
# Cameras and Lightroom are inconsistent about how they write LensModel: some
# shots carry the full marketing name, others only the bare optical spec. The
# lens is physically the same, so the site shouldn't say two different things.
#
# Left side = the raw string as it appears in EXIF (the script prints every
# distinct value it finds, so you can copy them in exactly).
# Right side = what you want displayed.
LENS_ALIASES = {
    # Nikon 18-55mm — 47 photos, split across two raw spellings
    "18.0-55.0 mm f/3.5-5.6": "AF-S DX NIKKOR 18-55mm f/3.5-5.6G VR II",
    "AF-S DX VR Nikkor 18-55mm f/3.5-5.6G II": "AF-S DX NIKKOR 18-55mm f/3.5-5.6G VR II",

    # Nikon 55-200mm — 21 photos, also two raw spellings
    "55.0-200.0 mm f/4.0-5.6": "AF-S DX VR Zoom-Nikkor ED 55-200mm F4-5.6G",
    "AF-S DX VR Zoom-Nikkor 55-200mm f/4-5.6G IF-ED": "AF-S DX VR Zoom-Nikkor ED 55-200mm F4-5.6G",

    # Canon PowerShot G7 X Mark III — fixed lens. Labelled with its 35mm
    # equivalent range, because 8.8-36.8mm on a 1-inch sensor tells a reader
    # nothing about how wide or long the shot actually is.
    "8.8-36.8 mm": "24-100mm f/1.8-2.8",
}

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


def format_focal(focal_length, equivalent=None):
    """Format focal length, adding the 35mm equivalent when it differs.

    '180mm (270mm eq.)' on the APS-C Nikon, '8.8mm (24mm eq.)' on the
    1-inch Canon, and a plain '50mm' on any full-frame body.

    The physical focal length is a property of the glass and never changes.
    The ANGLE OF VIEW depends on sensor size too, because a smaller sensor
    captures less of the image circle the lens projects. The equivalent
    figure answers "what lens on a full-frame camera would frame this the
    same way?" — which is the number photographers have intuition for.
    """
    if not focal_length:
        return None

    actual = f"{float(focal_length):g}mm"

    if not equivalent:
        return actual

    # Guard: some cameras write 0 when they don't know, and there's no point
    # printing '50mm (50mm eq.)' on a full-frame body where they're equal.
    # The 1mm tolerance absorbs rounding.
    try:
        if float(equivalent) > 0 and abs(float(focal_length) - float(equivalent)) > 1:
            return f"{actual} ({float(equivalent):g}mm eq.)"
    except (TypeError, ValueError):
        pass

    return actual


def resolve_place(entry):
    """Work out the place line shown under the title in the lightbox.

    Three-tier fallback:
      1. An explicit "place" in captions.json always wins — write anything
         you like there, including "" to show nothing for that photo.
      2. Otherwise use "location", which is the geocoder string.
      3. Unless location just restates the title, in which case show nothing.

    Rule 3 is the reason this function exists. "Seljalandsfoss, Iceland" as
    both title and place says the same thing twice, but "Peyto Lake, Banff"
    with "Peyto Lake, Banff National Park, Alberta, Canada" underneath adds
    the park and country. Defaulting sensibly means you only hand-write the
    ones you actually want to differ.
    """
    # `is not None` rather than a plain truthiness check, so an explicit ""
    # is respected as "deliberately blank" instead of falling through.
    if entry.get("place") is not None:
        return entry["place"]

    location = entry.get("location", "")
    title = entry.get("title", "")

    if location and location != title:
        return location
    return ""


def clean_lens(raw):
    """Normalise a lens name, preferring your chosen display name.

    Falls back to tidying the raw spec: '18.0-55.0 mm' -> '18-55mm'. Those
    trailing '.0's are how EXIF stores a whole number, not something you'd
    ever write on a spec sheet.
    """
    if not raw:
        return None
    raw = str(raw).strip()

    if raw in LENS_ALIASES:
        return LENS_ALIASES[raw]

    tidy = re.sub(r"(\d+)\.0(?!\d)", r"\1", raw)   # 18.0 -> 18
    tidy = re.sub(r"\s+mm", "mm", tidy)              # '55 mm' -> '55mm'
    return tidy


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
        "datetime_full": None, "copyright": None,
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
        data["lens"] = clean_lens(ifd.get("LensModel"))
        # Keep the raw value too, so the report below can show you exactly
        # what to paste into LENS_ALIASES.
        data["_lens_raw"] = str(ifd["LensModel"]).strip() if ifd.get("LensModel") else None

        # Use FNumber and ExposureTime, NOT ApertureValue and ShutterSpeedValue.
        # The *Value variants are APEX numbers — logarithmic encodings. An
        # ApertureValue of 4.97 means f/5.6, not f/4.97.
        data["aperture"] = format_aperture(ifd.get("FNumber"))
        data["shutter"] = format_shutter(ifd.get("ExposureTime"))
        data["focal"] = format_focal(
            ifd.get("FocalLength"),
            ifd.get("FocalLengthIn35mmFilm"),
        )

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
                data["date"] = dt.strftime("%Y-%m-%d")            # for sorting
                data["date_display"] = dt.strftime("%B %-d, %Y")    # for humans
                data["datetime_full"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                # Copyright year comes from when the shutter fired, which is
                # the year that actually matters for the claim.
                data["copyright"] = f"\u00a9 {dt.year} {OWNER}"
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
    lens_values = {}   # raw EXIF lens string -> how many photos use it
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
            # Pop the raw lens off so it doesn't ship in the public JSON —
            # it's a diagnostic for the report, not site content.
            raw_lens = exif.pop("_lens_raw", None)
            if raw_lens:
                lens_values.setdefault(raw_lens, 0)
                lens_values[raw_lens] += 1

            photos.append({
                "id": filename.rsplit(".", 1)[0],   # 'nature-001'
                "category": category,
                "categoryLabel": CATEGORY_LABELS[category],
                "order": index,
                "full": f"images/full/{filename}",
                "thumb": f"images/thumbs/{filename}",
                "title": entry.get("title", ""),
                "location": entry.get("location", ""),   # geocoder input
                "place": resolve_place(entry),            # what the panel shows
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

    # Show every distinct lens string found, with a count and how it will be
    # displayed. Anything showing "(auto-tidied)" is not in LENS_ALIASES yet —
    # paste the raw string in if you want a different name.
    if lens_values:
        print(f"\n  Lenses found ({len(lens_values)} distinct)")
        for raw in sorted(lens_values):
            mapped = LENS_ALIASES.get(raw)
            shown = mapped if mapped else clean_lens(raw) + "   (auto-tidied)"
            print(f"    {lens_values[raw]:>3}x  {raw}")
            print(f"          -> {shown}")

    print()


if __name__ == "__main__":
    main()