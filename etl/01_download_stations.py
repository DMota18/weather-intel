"""Download raw GHCN daily observation files (.dly fixed-width format)."""

import os
import urllib.request
import time
from config import STATIONS

GHCN_BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/"
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")


def download_station(station_id):
    url = f"{GHCN_BASE_URL}{station_id}.dly"
    dest = os.path.join(RAW_DIR, f"{station_id}.dly")

    if os.path.exists(dest):
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  SKIP {station_id} (already exists, {size_mb:.1f} MB)")
        return

    print(f"  Downloading {station_id}...")
    urllib.request.urlretrieve(url, dest)
    size_mb = os.path.getsize(dest) / (1024 * 1024)
    print(f"  OK: {size_mb:.1f} MB")


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"Downloading {len(STATIONS)} station .dly files...\n")

    for i, (station_id, info) in enumerate(STATIONS.items(), 1):
        print(f"[{i}/{len(STATIONS)}] {info['name']} ({info['covers']})")
        try:
            download_station(station_id)
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(1)

    print("\nRaw files:")
    for f in sorted(os.listdir(RAW_DIR)):
        if f.endswith(".dly"):
            size = os.path.getsize(os.path.join(RAW_DIR, f)) / (1024 * 1024)
            print(f"  {f}: {size:.1f} MB")


if __name__ == "__main__":
    main()
