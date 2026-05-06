#!/usr/bin/env python3
"""
Download DB-IP "IP to Country Lite" MMDB (Creative Commons Attribution 4.0).

Compatible with geoip2.DatabaseReader — set GEOIP_DB_PATH to the output .mmdb.

Tries the current calendar month URL first, then walks back month-by-month
until a release is found (DB-IP names files dbip-country-lite-YYYY-MM.mmdb.gz).

Run from repository root:
  python3 backend/scripts/download_dbip_country_lite.py

Default output: <repo>/data/geoip/dbip-country-lite.mmdb

Attribution: https://db-ip.com/db/ip-to-country-lite — if you expose geolocation
to end users, CC-BY requires a link back to DB-IP.com (see their license page).
"""
from __future__ import annotations

import argparse
import gzip
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_MMDB = _REPO_ROOT / "data" / "geoip" / "dbip-country-lite.mmdb"

DOWNLOAD_TEMPLATE = "https://download.db-ip.com/free/dbip-country-lite-{ym}.mmdb.gz"
USER_AGENT = "migraine-chatbot-geoip-fetch/1.0"


def month_keys(max_attempts: int = 6) -> list[str]:
    d = date.today()
    keys: list[str] = []
    for _ in range(max_attempts):
        keys.append(f"{d.year:04d}-{d.month:02d}")
        first_this = date(d.year, d.month, 1)
        last_prev = first_this - timedelta(days=1)
        d = date(last_prev.year, last_prev.month, 1)
    return keys


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_MMDB,
        help=f"Path to write decompressed .mmdb (default: {_DEFAULT_MMDB})",
    )
    parser.add_argument(
        "-m",
        "--month",
        help="Force YYYY-MM instead of probing recent months (e.g. 2026-05)",
    )
    args = parser.parse_args()
    out: Path = args.output
    out.parent.mkdir(parents=True, exist_ok=True)

    months = [args.month] if args.month else month_keys()
    for ym in months:
        url = DOWNLOAD_TEMPLATE.format(ym=ym)
        try:
            raw = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404 and not args.month:
                continue
            print(f"HTTP {e.code} for {url}", file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"Download failed: {e}", file=sys.stderr)
            return 1
        try:
            data = gzip.decompress(raw)
        except OSError as e:
            print(f"Invalid gzip from {url}: {e}", file=sys.stderr)
            return 1
        out.write_bytes(data)
        print(f"Wrote {out.resolve()} ({len(data)} bytes) from {url}")
        return 0

    print(
        "No DB-IP lite MMDB found for recent months. "
        "Pass --month YYYY-MM from https://db-ip.com/db/download/ip-to-country-lite",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
