"""Cache hourly forecasts from Open-Meteo to Postgres."""

import asyncio
import json
import sys
import os
import psycopg2
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from weather_client import fetch_forecast_48h, parse_forecast_hours
from config import STATIONS, DB_CONFIG
from scoring import score_pour_hour

ET = ZoneInfo("America/New_York")


async def main():
    conn = psycopg2.connect(**DB_CONFIG)
    now = datetime.now(ET)
    expires = now + timedelta(hours=3)
    total = 0

    for slug, station in STATIONS.items():
        try:
            data = await fetch_forecast_48h(station["lat"], station["lon"])
            hours = parse_forecast_hours(data)

            with conn.cursor() as cur:
                for h in hours:
                    score, factors = score_pour_hour(
                        temp_f=h["temp_f"], humidity_pct=h["humidity_pct"],
                        wind_mph=h["wind_mph"], precip_prob_pct=h["precip_prob_pct"],
                        dewpoint_f=h["dewpoint_f"]
                    )
                    cur.execute("""
                        INSERT INTO weather_forecasts
                            (station_id, forecast_hour, temp_f, humidity_pct, wind_mph,
                             wind_gust_mph, precip_prob_pct, precip_amount_in, dewpoint_f,
                             cloud_cover_pct, pour_score, score_factors, fetched_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (station_id, forecast_hour, fetched_at) DO NOTHING
                    """, (
                        station["station_id"],
                        datetime.strptime(h["time"], "%Y-%m-%dT%H:%M").replace(tzinfo=ET).isoformat(),
                        h["temp_f"], h["humidity_pct"], h["wind_mph"],
                        h["wind_gust_mph"], h["precip_prob_pct"], h["precip_in"],
                        h["dewpoint_f"], h["cloud_cover_pct"],
                        score, json.dumps(factors),
                        now, expires
                    ))
            conn.commit()
            total += len(hours)
            print(f"  {slug}: {len(hours)} hours cached")
        except Exception as e:
            print(f"  {slug}: FAILED - {e}")

    with conn.cursor() as cur:
        cur.execute("DELETE FROM weather_forecasts WHERE expires_at < now() - interval '24 hours'")
        deleted = cur.rowcount
    conn.commit()
    conn.close()
    print(f"Total: {total} forecast hours cached, {deleted} expired rows cleaned")


if __name__ == "__main__":
    asyncio.run(main())
