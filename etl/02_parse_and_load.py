"""
Parse GHCN .dly fixed-width files and load into PostgreSQL.

The .dly format:
- Each line = one station + one month + one element (TMAX, TMIN, PRCP, etc.)
- Columns:
    0-10:  Station ID (11 chars)
    11-14: Year (4 chars)
    15-16: Month (2 chars)
    17-20: Element (4 chars)
    21+:   31 x (VALUE(5) + MFLAG(1) + QFLAG(1) + SFLAG(1)) = 8 chars per day
- VALUE = -9999 means missing
- QFLAG != ' ' means failed quality check
- Units: TMAX/TMIN in tenths of Celsius, PRCP in tenths of mm,
         SNOW/SNWD in mm, AWND/WSF2/WSF5 in tenths of m/s
"""

import os
import sys
import json
from datetime import date
from calendar import monthrange
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import STATIONS, ELEMENTS_NEEDED, BACKFILL_START_YEAR

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw")

DB_CONFIG = {
    "dbname": os.environ.get("WI_DB_NAME", "weather_intel"),
    "user": os.environ.get("WI_DB_USER", "weather"),
    "password": os.environ.get("WI_DB_PASSWORD", "weather_local"),
    "host": os.environ.get("WI_DB_HOST", "localhost"),
    "port": int(os.environ.get("WI_DB_PORT", "5432")),
}


def tenths_c_to_f(val):
    if val is None:
        return None
    return round((val / 10.0) * 9.0 / 5.0 + 32, 1)


def tenths_mm_to_inches(val):
    if val is None:
        return None
    return round(val / 10.0 / 25.4, 2)


def mm_to_inches(val):
    if val is None:
        return None
    return round(val / 25.4, 1)


def tenths_ms_to_mph(val):
    if val is None:
        return None
    return round(val / 10.0 * 2.237, 1)


def parse_dly_line(line):
    station_id = line[0:11].strip()
    year = int(line[11:15])
    month = int(line[15:17])
    element = line[17:21].strip()

    days_in_month = monthrange(year, month)[1]
    daily_values = []

    for day in range(1, 32):
        offset = 21 + (day - 1) * 8
        raw_value = line[offset:offset + 5].strip()
        qflag = line[offset + 6:offset + 7]

        if day > days_in_month:
            continue

        if not raw_value or raw_value == "-9999":
            value = None
        else:
            value = int(raw_value)

        if value is not None and qflag.strip():
            value = None

        daily_values.append({"day": day, "value": value})

    return {"station_id": station_id, "year": year, "month": month, "element": element, "values": daily_values}


def parse_station_file(station_id, start_year):
    filepath = os.path.join(RAW_DIR, f"{station_id}.dly")
    observations = {}

    with open(filepath, "r") as f:
        for line in f:
            if len(line) < 269:
                continue

            parsed = parse_dly_line(line)

            if parsed["year"] < start_year:
                continue
            if parsed["element"] not in ELEMENTS_NEEDED:
                continue

            for dv in parsed["values"]:
                if dv["value"] is None:
                    continue

                try:
                    obs_date = date(parsed["year"], parsed["month"], dv["day"])
                except ValueError:
                    continue

                key = obs_date.isoformat()
                if key not in observations:
                    observations[key] = {"date": obs_date, "station_id": station_id}
                observations[key][parsed["element"]] = dv["value"]

    return list(observations.values())


def compute_scores(row):
    temp_high = row.get("temp_max_f")
    temp_low = row.get("temp_min_f")
    precip = row.get("precip_in") or 0
    wind = row.get("wind_max_mph")

    pour_factors = {}
    if temp_high is not None:
        if 50 <= temp_high <= 90:
            pour_factors["temperature"] = "green"
        elif 40 <= temp_high < 50 or 90 < temp_high <= 95:
            pour_factors["temperature"] = "yellow"
        else:
            pour_factors["temperature"] = "red"

    if precip is not None:
        if precip == 0:
            pour_factors["precipitation"] = "green"
        elif precip < 0.1:
            pour_factors["precipitation"] = "yellow"
        else:
            pour_factors["precipitation"] = "red"

    if wind is not None:
        if wind < 10:
            pour_factors["wind"] = "green"
        elif wind < 20:
            pour_factors["wind"] = "yellow"
        else:
            pour_factors["wind"] = "red"

    if pour_factors:
        if "red" in pour_factors.values():
            pour_score = "red"
        elif "yellow" in pour_factors.values():
            pour_score = "yellow"
        else:
            pour_score = "green"
    else:
        pour_score = None

    sealer_factors = {}
    if precip is not None:
        if precip == 0:
            sealer_factors["precipitation"] = "green"
        elif precip < 0.05:
            sealer_factors["precipitation"] = "yellow"
        else:
            sealer_factors["precipitation"] = "red"

    if temp_high is not None and temp_low is not None:
        if temp_low >= 50 and temp_high <= 90:
            sealer_factors["temperature"] = "green"
        elif temp_low >= 40:
            sealer_factors["temperature"] = "yellow"
        else:
            sealer_factors["temperature"] = "red"

    if sealer_factors:
        if "red" in sealer_factors.values():
            sealer_score = "red"
        elif "yellow" in sealer_factors.values():
            sealer_score = "yellow"
        else:
            sealer_score = "green"
    else:
        sealer_score = None

    return pour_score, sealer_score, pour_factors, sealer_factors


def transform_observations(observations):
    rows = []
    for obs in observations:
        row = {
            "station_id": obs["station_id"],
            "date": obs["date"],
            "temp_max_f": tenths_c_to_f(obs.get("TMAX")),
            "temp_min_f": tenths_c_to_f(obs.get("TMIN")),
            "precip_in": tenths_mm_to_inches(obs.get("PRCP")),
            "snow_in": mm_to_inches(obs.get("SNOW")),
            "snow_depth_in": mm_to_inches(obs.get("SNWD")),
            "wind_avg_mph": tenths_ms_to_mph(obs.get("AWND")),
            "wind_max_mph": tenths_ms_to_mph(obs.get("WSF2") if obs.get("WSF2") is not None else obs.get("WSF5")),
        }
        if row["temp_max_f"] is not None and row["temp_min_f"] is not None:
            row["temp_mean_f"] = round((row["temp_max_f"] + row["temp_min_f"]) / 2, 1)
        else:
            row["temp_mean_f"] = None

        pour_score, sealer_score, pour_factors, sealer_factors = compute_scores(row)
        row["pour_score"] = pour_score
        row["sealer_score"] = sealer_score
        row["score_details"] = {"pour": pour_factors, "sealer": sealer_factors}
        rows.append(row)
    return rows


def load_to_db(rows, conn):
    if not rows:
        return 0

    values = [
        (
            r["station_id"], r["date"],
            r["temp_max_f"], r["temp_min_f"], r["temp_mean_f"],
            r["precip_in"], r["snow_in"], r["snow_depth_in"],
            r["wind_avg_mph"], r["wind_max_mph"],
            r["pour_score"], r["sealer_score"],
            json.dumps(r["score_details"]),
        )
        for r in rows
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO daily_weather
               (station_id, observation_date, temp_max_f, temp_min_f, temp_mean_f,
                precip_in, snow_in, snow_depth_in, wind_avg_mph, wind_max_mph,
                pour_score, sealer_score, score_details)
               VALUES %s
               ON CONFLICT (station_id, observation_date) DO UPDATE SET
                 temp_max_f = EXCLUDED.temp_max_f,
                 temp_min_f = EXCLUDED.temp_min_f,
                 temp_mean_f = EXCLUDED.temp_mean_f,
                 precip_in = EXCLUDED.precip_in,
                 snow_in = EXCLUDED.snow_in,
                 snow_depth_in = EXCLUDED.snow_depth_in,
                 wind_avg_mph = EXCLUDED.wind_avg_mph,
                 wind_max_mph = EXCLUDED.wind_max_mph,
                 pour_score = EXCLUDED.pour_score,
                 sealer_score = EXCLUDED.sealer_score,
                 score_details = EXCLUDED.score_details""",
            values,
            page_size=500,
        )
    conn.commit()
    return len(values)


def main():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)

    total_loaded = 0
    for station_id, info in STATIONS.items():
        print(f"\nProcessing {info['name']} ({station_id})...")
        print(f"  Parsing .dly file (from {BACKFILL_START_YEAR})...")
        observations = parse_station_file(station_id, BACKFILL_START_YEAR)
        print(f"  Found {len(observations)} observation days")

        print("  Transforming (unit conversion + scoring)...")
        rows = transform_observations(observations)

        print("  Loading to database...")
        count = load_to_db(rows, conn)
        total_loaded += count
        print(f"  Loaded {count} rows")

    conn.close()
    print(f"\n=== TOTAL: {total_loaded} rows loaded ===")


if __name__ == "__main__":
    main()
