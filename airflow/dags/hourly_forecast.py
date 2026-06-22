"""
Hourly Forecast DAG: Fetch Open-Meteo forecasts → Cache to Postgres → Detect changes

Runs every hour. Pre-warms the forecast cache so dashboard loads are instant.
Stores forecasts in the weather_forecasts table for historical tracking.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

VENV = "/home/ubuntu/weather-intel/venv/bin"
PROJECT = "/home/ubuntu/weather-intel"

default_args = {
    "owner": "dylan",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

FETCH_SCRIPT = """
cd {project} && {venv}/python -c "
import asyncio, json, psycopg2
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.weather_client import fetch_forecast_48h, parse_forecast_hours
from app.config import STATIONS, DB_CONFIG
from app.scoring import score_pour_hour

ET = ZoneInfo('America/New_York')

async def main():
    conn = psycopg2.connect(**DB_CONFIG)
    now = datetime.now(ET)
    expires = now + timedelta(hours=3)
    total = 0

    for slug, station in STATIONS.items():
        try:
            data = await fetch_forecast_48h(station['lat'], station['lon'])
            hours = parse_forecast_hours(data)

            with conn.cursor() as cur:
                for h in hours:
                    score, factors = score_pour_hour(
                        temp_f=h['temp_f'], humidity_pct=h['humidity_pct'],
                        wind_mph=h['wind_mph'], precip_prob_pct=h['precip_prob_pct'],
                        dewpoint_f=h['dewpoint_f']
                    )
                    cur.execute('''
                        INSERT INTO weather_forecasts
                            (station_id, forecast_hour, temp_f, humidity_pct, wind_mph,
                             wind_gust_mph, precip_prob_pct, precip_amount_in, dewpoint_f,
                             cloud_cover_pct, pour_score, score_factors, fetched_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (station_id, forecast_hour, fetched_at) DO NOTHING
                    ''', (
                        station['station_id'],
                        h['time'] + ':00-04:00',
                        h['temp_f'], h['humidity_pct'], h['wind_mph'],
                        h['wind_gust_mph'], h['precip_prob_pct'], h['precip_in'],
                        h['dewpoint_f'], h['cloud_cover_pct'],
                        score, json.dumps(factors),
                        now, expires
                    ))
            conn.commit()
            total += len(hours)
            print(f'  {{slug}}: {{len(hours)}} hours cached')
        except Exception as e:
            print(f'  {{slug}}: FAILED - {{e}}')

    # Cleanup expired forecasts older than 24h
    with conn.cursor() as cur:
        cur.execute(\"DELETE FROM weather_forecasts WHERE expires_at < now() - interval '24 hours'\")
        deleted = cur.rowcount
    conn.commit()
    conn.close()
    print(f'Total: {{total}} forecast hours cached, {{deleted}} expired rows cleaned')

asyncio.run(main())
"
""".format(venv=VENV, project=PROJECT)

with DAG(
    "hourly_forecast_cache",
    default_args=default_args,
    description="Hourly: fetch forecasts from Open-Meteo, cache to Postgres",
    schedule_interval="0 * * * *",
    start_date=datetime(2026, 6, 10),
    catchup=False,
    tags=["forecast", "cache"],
) as dag:

    fetch_and_cache = BashOperator(
        task_id="fetch_and_cache_forecasts",
        bash_command=FETCH_SCRIPT,
    )

    cleanup_stale = BashOperator(
        task_id="cleanup_stale_forecasts",
        bash_command=f"""sudo -u postgres psql -d weather_intel -c "DELETE FROM weather_forecasts WHERE expires_at < now() - interval '7 days';" """,
    )

    fetch_and_cache >> cleanup_stale
