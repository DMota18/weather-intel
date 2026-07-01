"""
Hourly Forecast DAG: Fetch Open-Meteo forecasts → Cache to Postgres

Runs every hour. Pre-warms the forecast cache so dashboard loads are instant.
Stores forecasts in the weather_forecasts table for historical tracking.
"""

import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

sys.path.insert(0, "/home/ubuntu/weather-intel/scripts")
from alert_on_failure import on_failure

VENV = "/home/ubuntu/weather-intel/venv/bin"
PROJECT = "/home/ubuntu/weather-intel"

default_args = {
    "owner": "dylan",
    "depends_on_past": False,
    "on_failure_callback": on_failure,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

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
        bash_command=f"cd {PROJECT}/scripts && {VENV}/python cache_forecasts.py",
    )

    cleanup_stale = BashOperator(
        task_id="cleanup_stale_forecasts",
        bash_command=f"""sudo -u postgres psql -d weather_intel -c "DELETE FROM weather_forecasts WHERE expires_at < now() - interval '7 days';" """,
    )

    fetch_and_cache >> cleanup_stale
