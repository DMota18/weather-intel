"""
Hourly forecast snapshot job — run by the hourly_forecast_cache DAG.

Fetches the 48h Open-Meteo forecast for every station, scores each hour,
and appends the snapshot to the weather_forecasts table. This builds the
forecast history used for accuracy tracking and model training (the API
serves live requests from its own in-process cache, not this table).

Exit codes: 0 = all stations stored, 1 = every station failed (Airflow
retries + alerts); partial failures log errors but still exit 0 so one
flaky station doesn't mask the other nine.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"cache_forecasts","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("cache_forecasts")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from config import DB_CONFIG, STATIONS  # noqa: E402
from weather_client import fetch_forecast_48h, parse_forecast_hours  # noqa: E402
from scoring import score_pour_hour  # noqa: E402

ET = ZoneInfo("America/New_York")

INSERT_SQL = """
    INSERT INTO weather_forecasts
        (station_id, forecast_hour, temp_f, humidity_pct, wind_mph, wind_gust_mph,
         precip_prob_pct, precip_amount_in, dewpoint_f, cloud_cover_pct,
         pour_score, fetched_at, expires_at)
    VALUES %s
    ON CONFLICT (station_id, forecast_hour, fetched_at) DO NOTHING
"""


def store_forecast(conn, station_id: str, hours: list[dict], fetched_at: datetime) -> int:
    # Superseded by the next hourly run; the DAG prunes rows 7 days after expiry
    expires_at = fetched_at + timedelta(hours=1)

    rows = []
    for h in hours:
        score, _ = score_pour_hour(
            temp_f=h["temp_f"],
            humidity_pct=h["humidity_pct"],
            wind_mph=h["wind_mph"],
            precip_prob_pct=h["precip_prob_pct"],
            dewpoint_f=h["dewpoint_f"],
        )
        rows.append((
            station_id,
            datetime.fromisoformat(h["time"]).replace(tzinfo=ET),
            h["temp_f"], h["humidity_pct"], h["wind_mph"], h["wind_gust_mph"],
            h["precip_prob_pct"], h["precip_in"], h["dewpoint_f"], h["cloud_cover_pct"],
            score, fetched_at, expires_at,
        ))

    with conn.cursor() as cur:
        execute_values(cur, INSERT_SQL, rows, page_size=100)
    conn.commit()
    return len(rows)


async def main() -> int:
    fetched_at = datetime.now(ET)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        logger.error("Cannot connect to database: %s", e)
        return 1

    ok, failed = 0, 0
    try:
        for slug, info in STATIONS.items():
            try:
                data = await fetch_forecast_48h(info["lat"], info["lon"])
                hours = parse_forecast_hours(data)
                if not hours:
                    raise ValueError("empty forecast response")
                count = store_forecast(conn, info["station_id"], hours, fetched_at)
                logger.info("%s: stored %d forecast hours", slug, count)
                ok += 1
            except Exception as e:
                conn.rollback()
                logger.error("%s: failed — %s", slug, e)
                failed += 1
    finally:
        conn.close()

    logger.info("Done: %d stations stored, %d failed", ok, failed)
    return 1 if ok == 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
