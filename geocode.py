#!/usr/bin/env python3
"""
geocode.py — turns the place names in captions.json into map coordinates.

WHY THIS EXISTS
    Your D3300 has no GPS receiver, so none of your photos carry coordinates.
    But your captions already name the places, and they repeat heavily — five
    photos at Jökulsárlón, four on Tunnel Mountain Trail. So instead of
    hand-entering 105 coordinate pairs, we look up each UNIQUE place once.

HOW IT FITS TOGETHER
    captions.json  --(this script)-->  locations.json  --(build_data.py)-->  photos.json

    Run order matters: geocode.py first, then build_data.py, which merges the
    coordinates into the file the website reads.

CACHING
    Every result is saved to data/locations.json and never looked up twice.
    Re-running after adding photos only queries the genuinely new places. You
    can also hand-edit that file — the script won't overwrite existing
    entries, so a coordinate you fix by hand stays fixed.

USAGE
    python3 geocode.py             # look up anything not already cached
    python3 geocode.py --refresh   # re-query everything, ignoring the cache
    python3 geocode.py --dry-run   # just list what WOULD be looked up
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CAPTIONS_FILE = ROOT / "data" / "captions.json"
LOCATIONS_FILE = ROOT / "data" / "locations.json"

# Nominatim is OpenStreetMap's geocoder. It's free and needs no API key,
# which is why we're using it — but it's funded by donations and run by
# volunteers, so its usage policy is a real obligation, not a formality:
#
#   1. Maximum ONE request per second.
#   2. A User-Agent that identifies your application and how to contact you.
#      The default Python user-agent gets blocked outright.
#
# Respecting these is basic API etiquette, and this is a good place to learn
# it — the stakes are low here, and the habit carries to services where
# getting rate-limited actually costs you something.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "emilyqcheng-photo-portfolio/1.0 (https://emilyqcheng.github.io/photo-portfolio/)"
REQUEST_DELAY = 1.1     # seconds between requests — just over the 1/sec limit
TIMEOUT = 15


def load_json(path, default):
    """Read a JSON file, returning `default` if it doesn't exist yet."""
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def unique_locations(captions):
    """Collect every distinct non-empty location string, in first-seen order.

    dict.fromkeys() is a neat idiom for deduplicating while PRESERVING order.
    A set() would also dedupe but scrambles the sequence, which would make
    the script's output different on every run for no reason — annoying when
    you're reading a progress log or diffing the result.
    """
    found = []
    for category, entries in captions.items():
        if category.startswith("_"):        # skip the _readme block
            continue
        for entry in entries:
            location = (entry.get("location") or "").strip()
            if location:
                found.append(location)
    return list(dict.fromkeys(found))


def geocode(place):
    """Ask Nominatim for one place. Returns a dict, or None if not found."""
    params = urllib.parse.urlencode({
        "q": place,
        "format": "json",
        "limit": 1,              # we only want the best match
        "addressdetails": 0,
    })
    url = f"{NOMINATIM_URL}?{params}"

    # Building a Request object (rather than calling urlopen on the URL
    # directly) is what lets us set the User-Agent header.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            results = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        print(f"      HTTP {error.code} — {error.reason}")
        return None
    except urllib.error.URLError as error:
        print(f"      network error — {error.reason}")
        return None
    except json.JSONDecodeError:
        print("      response was not valid JSON")
        return None

    if not results:
        return None

    top = results[0]
    return {
        # Nominatim returns coordinates as STRINGS. Convert them now, so a
        # bad value fails here in the script rather than silently becoming
        # the text "64.07" in your JSON and breaking Leaflet later.
        "lat": float(top["lat"]),
        "lng": float(top["lon"]),
        # Keep what Nominatim thought you meant. This is how you spot a wrong
        # match — "Brighton, East Sussex, England" when you meant Brighton,
        # Utah is obvious here and invisible in a bare coordinate pair.
        "matched": top.get("display_name", ""),
    }


def main():
    refresh = "--refresh" in sys.argv
    dry_run = "--dry-run" in sys.argv

    captions = load_json(CAPTIONS_FILE, None)
    if captions is None:
        sys.exit(f"Missing {CAPTIONS_FILE}")

    cache = load_json(LOCATIONS_FILE, {})
    places = unique_locations(captions)

    todo = places if refresh else [p for p in places if p not in cache]

    print(f"\n  {len(places)} unique places in captions.json")
    print(f"  {len(cache)} already cached")
    print(f"  {len(todo)} to look up\n")

    if dry_run:
        for place in todo:
            print(f"    would look up: {place}")
        print()
        return

    if not todo:
        print("  Nothing to do. Use --refresh to re-query everything.\n")
        return

    # Rough time estimate, since this is deliberately slow and you should
    # know that up front rather than wondering if it's hung.
    print(f"  About {len(todo) * REQUEST_DELAY:.0f}s at 1 request/second.\n")

    resolved = 0
    failed = []

    for index, place in enumerate(todo, start=1):
        print(f"  [{index}/{len(todo)}] {place}")

        result = geocode(place)

        if result:
            cache[place] = result
            resolved += 1
            print(f"      {result['lat']:.4f}, {result['lng']:.4f}")
            print(f"      matched: {result['matched'][:70]}")
        else:
            failed.append(place)
            print("      NOT FOUND")

        # Write after EVERY lookup, not at the end. If the script dies
        # halfway — network drop, Ctrl+C — you keep everything found so far
        # and the next run resumes where it stopped. Cheap insurance when the
        # work is slow and rate-limited.
        with open(LOCATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)

        # Sleep BETWEEN requests, not after the last one.
        if index < len(todo):
            time.sleep(REQUEST_DELAY)

    print(f"\n  Resolved {resolved}. Cache now holds {len(cache)} places.")

    if failed:
        print(f"\n  Could not find ({len(failed)}):")
        for place in failed:
            print(f"    - {place}")
        print("""
  To fix these, add them to data/locations.json by hand. Right-click the
  spot in Google Maps and it copies the coordinates:

    "Some Place, Somewhere": {
      "lat": 64.0784,
      "lng": -16.2306,
      "matched": "entered manually"
    }

  Failures are NOT cached, so anything you don't fix will be retried on the
  next run — and anything you DO add by hand will be left alone.""")

    print("""
  Next: check the "matched" values above for wrong matches (place names
  repeat across the world), then run build_data.py to merge these
  coordinates into photos.json.
""")


if __name__ == "__main__":
    main()