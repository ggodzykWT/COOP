#!/usr/bin/env python3
"""
Rebuild the Whittier Tech co-op signage HTML files from the published
Google Sheet CSV.

What it does, in order:
  1. Fetch the published CSV (Partner(s), Street, City, State, ZIP,
     List entries, category).
  2. Geocode any address not already in data/coords_cache.json —
     primary: US Census Bureau geocoder (free, no key, built for
     exactly this kind of batch/automated US-address use).
     fallback: Nominatim/OpenStreetMap (rate-limited to 1 req/sec per
     its usage policy), for addresses the Census geocoder can't match.
  3. Re-embed the resulting `records` and `COORDS` JS literals into
     each of the 6 signage HTML files, in place. Nothing else in those
     files is touched — layout, styling, map zoom, popup behavior, the
     try/catch hardening, etc. all stay exactly as already tuned.

Usage:
  python3 scripts/build.py [--csv-url URL] [--dry-run]

Exit code is non-zero if any HTML file failed to update (so CI can
tell something needs attention), even if other files updated fine.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
COORDS_CACHE_PATH = os.path.join(DATA_DIR, "coords_cache.json")
PARTNERS_CSV_PATH = os.path.join(DATA_DIR, "partners.csv")

CSV_URL_DEFAULT = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSKiem6vEk3k-bAipPEk6bT-3D88fpuYd8zhZ1q52MytQl_057SQHljvfckIj-fvJTiy4cVgOn0jgY5/"
    "pub?output=csv"
)

HTML_FILES = [
    "whittier_tech_coop_impact_dashboard_signage.html",
    "whittier_tech_coop_signage_1_overview.html",
    "whittier_tech_coop_signage_2_map.html",
    "whittier_tech_coop_signage_3_district.html",
    "whittier_tech_coop_signage_4_industries.html",
    "whittier_tech_coop_signage_5_communities.html",
]

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "WhittierTechCoopDashboard/1.0 (contact: ggodzyk@whittier.tec.ma.us)"


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig")


def parse_records(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    records = []
    for row in reader:
        name = (row.get("Partner(s)") or "").strip()
        if not name:
            continue  # blank/placeholder row
        street = (row.get("Street") or "").strip()
        city = (row.get("City") or "").strip()
        state = (row.get("State") or "").strip()
        zip_ = (row.get("ZIP") or "").strip()
        entries_raw = (row.get("List entries") or "").strip()
        category = (row.get("category") or "").strip()

        if not category:
            print(f"  WARNING: {name!r} has no category set", file=sys.stderr)

        if zip_:
            address = f"{street}, {city}, {state} {zip_}"
            full_address = f"{street}, {city}, {state}, {zip_}"
        else:
            address = f"{street}, {city}, {state}"
            full_address = f"{street}, {city}, {state}"

        records.append(
            {
                "Partner(s)": name,
                "Full address": full_address,
                "Street": street,
                "City": city,
                "State": state,
                "ZIP": zip_,
                "List entries": entries_raw or "0",
                "category": category,
                "address": address,
            }
        )
    return records


def geocode_census(address):
    params = urllib.parse.urlencode(
        {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    )
    url = f"{CENSUS_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    matches = data.get("result", {}).get("addressMatches") or []
    if not matches:
        return None
    coords = matches[0]["coordinates"]
    return [round(coords["y"], 6), round(coords["x"], 6)]  # [lat, lon]


def geocode_nominatim(address):
    params = urllib.parse.urlencode(
        {"q": address, "format": "json", "limit": 1, "countrycodes": "us"}
    )
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
    if not data:
        return None
    return [round(float(data[0]["lat"]), 6), round(float(data[0]["lon"]), 6)]


def geocode(address, cache):
    if address in cache:
        return cache[address]
    result = None
    try:
        result = geocode_census(address)
    except Exception as e:
        print(f"  Census geocoder error for {address!r}: {e}", file=sys.stderr)
    if result is None:
        try:
            result = geocode_nominatim(address)
        except Exception as e:
            print(f"  Nominatim geocoder error for {address!r}: {e}", file=sys.stderr)
    if result is None:
        print(f"  geocode FAILED (no match) for {address!r}", file=sys.stderr)
    cache[address] = result
    return result


def rebuild_html_files(records, coords):
    # ensure_ascii=True (the default) to match the escaping style already
    # used in the existing files (e.g. ½, ·) — keeps diffs small
    # and avoids any encoding surprises.
    records_json = json.dumps(records, separators=(",", ":"))
    coords_json = json.dumps(coords, separators=(",", ":"))
    records_line = f"const records={records_json};"
    coords_line = f"const COORDS={coords_json};"

    changed, failed = [], []
    for filename in HTML_FILES:
        path = os.path.join(REPO_ROOT, filename)
        if not os.path.exists(path):
            print(f"  WARNING: {filename} not found, skipping", file=sys.stderr)
            failed.append(filename)
            continue
        with open(path, encoding="utf-8") as f:
            content = f.read()

        new_content, n1 = re.subn(
            r"^const records=.*;$", lambda m: records_line, content, count=1, flags=re.MULTILINE
        )
        new_content, n2 = re.subn(
            r"^const COORDS=.*;$", lambda m: coords_line, new_content, count=1, flags=re.MULTILINE
        )
        if n1 != 1 or n2 != 1:
            print(
                f"  ERROR: {filename} — expected exactly 1 records/COORDS line, "
                f"found {n1}/{n2}. Leaving file untouched.",
                file=sys.stderr,
            )
            failed.append(filename)
            continue

        if new_content != content:
            changed.append(filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

    return changed, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-url", default=CSV_URL_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"Fetching CSV from {args.csv_url}")
    csv_text = fetch_csv(args.csv_url)
    if not args.dry_run:
        with open(PARTNERS_CSV_PATH, "w", encoding="utf-8") as f:
            f.write(csv_text)

    records = parse_records(csv_text)
    print(f"Parsed {len(records)} partner record(s)")
    if not records:
        print("No records found in CSV — nothing to build. Exiting without changes.")
        return 0

    cache = {}
    if os.path.exists(COORDS_CACHE_PATH):
        with open(COORDS_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    cache_before = dict(cache)

    addresses = sorted({r["address"] for r in records})
    # Use .get() rather than `in`: a previously-failed lookup is cached as
    # None (so a run doesn't log the same failure twice), but must still be
    # retried on the next run rather than permanently blacklisted.
    new_addresses = [a for a in addresses if not cache.get(a)]
    print(f"{len(addresses)} unique address(es), {len(new_addresses)} need geocoding")

    for i, addr in enumerate(new_addresses, 1):
        print(f"  [{i}/{len(new_addresses)}] geocoding {addr!r}")
        geocode(addr, cache)

    if cache != cache_before and not args.dry_run:
        with open(COORDS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=0, sort_keys=True)
            f.write("\n")

    coords = {addr: cache[addr] for addr in addresses if cache.get(addr)}
    missing = [addr for addr in addresses if not cache.get(addr)]
    if missing:
        print(f"WARNING: {len(missing)} address(es) could not be geocoded "
              f"and will be omitted from the map (still counted in stats/tables):",
              file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)

    if args.dry_run:
        print(f"[dry-run] Would embed {len(records)} records / {len(coords)} coords "
              f"into {len(HTML_FILES)} HTML file(s). No files written.")
        return 0

    changed, failed = rebuild_html_files(records, coords)
    if changed:
        print(f"Updated {len(changed)} file(s): {', '.join(changed)}")
    else:
        print("No HTML files changed (data identical to last build)")

    if failed:
        print(f"FAILED to update {len(failed)} file(s): {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
