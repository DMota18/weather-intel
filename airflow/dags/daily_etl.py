"""
Daily ETL DAG: Download NOAA updates → Parse & Load → dbt run → dbt test → Health check

Runs every day at 6AM ET. NOAA updates their files with ~1-2 day lag,
so this catches yesterday's observations.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

VENV = "/home/ubuntu/weather-intel/venv/bin"
PROJECT = "/home/ubuntu/weather-intel"
DBT_DIR = f"{PROJECT}/dbt_project"
DBT_PROFILES = f"--profiles-dir {DBT_DIR}"

default_args = {
    "owner": "dylan",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "daily_weather_etl",
    default_args=default_args,
    description="Daily NOAA data ingestion → dbt transformation → validation",
    schedule_interval="0 10 * * *",  # 6AM ET = 10 UTC
    start_date=datetime(2026, 6, 10),
    catchup=False,
    tags=["etl", "noaa", "dbt"],
) as dag:

    download_noaa = BashOperator(
        task_id="download_noaa_stations",
        bash_command=f"cd {PROJECT}/etl && {VENV}/python 01_download_stations.py",
    )

    parse_and_load = BashOperator(
        task_id="parse_and_load_to_postgres",
        bash_command=f"cd {PROJECT}/etl && {VENV}/python 02_parse_and_load.py",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt run {DBT_PROFILES}",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt test {DBT_PROFILES}",
    )

    health_check = BashOperator(
        task_id="api_health_check",
        bash_command='curl -sf http://localhost:8000/api/v1/towns > /dev/null && echo "API OK" || (echo "API FAILED" && exit 1)',
    )

    download_noaa >> parse_and_load >> dbt_run >> dbt_test >> health_check
