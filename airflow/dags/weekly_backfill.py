"""
Weekly Backfill DAG: Full NOAA re-download → Reload → dbt → Refresh materialized views

Runs every Sunday at 5AM ET. Re-downloads all station files to catch any
NOAA retroactive corrections, then does a full dbt run + materialized view refresh.
"""

import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

sys.path.insert(0, "/home/ubuntu/weather-intel/scripts")
from alert_on_failure import on_failure

VENV = "/home/ubuntu/weather-intel/venv/bin"
PROJECT = "/home/ubuntu/weather-intel"
DBT_DIR = f"{PROJECT}/dbt_project"
DBT_PROFILES = f"--profiles-dir {DBT_DIR}"

default_args = {
    "owner": "dylan",
    "depends_on_past": False,
    "on_failure_callback": on_failure,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    "weekly_full_backfill",
    default_args=default_args,
    description="Weekly: full NOAA re-download, reload, dbt, materialized view refresh",
    schedule_interval="0 9 * * 0",  # 5AM ET Sunday = 9 UTC
    start_date=datetime(2026, 6, 10),
    catchup=False,
    tags=["etl", "backfill", "weekly"],
) as dag:

    # Delete existing .dly files to force fresh download
    clear_old_files = BashOperator(
        task_id="clear_old_station_files",
        bash_command=f"rm -f {PROJECT}/data/raw/*.dly && echo 'Cleared old files'",
    )

    download_all = BashOperator(
        task_id="download_all_stations",
        bash_command=f"cd {PROJECT}/etl && {VENV}/python 01_download_stations.py",
    )

    parse_and_load = BashOperator(
        task_id="parse_and_load_all",
        bash_command=f"cd {PROJECT}/etl && {VENV}/python 02_parse_and_load.py",
    )

    dbt_run = BashOperator(
        task_id="dbt_run_full",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt run --full-refresh {DBT_PROFILES}",
    )

    dbt_test = BashOperator(
        task_id="dbt_test_full",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt test {DBT_PROFILES}",
    )

    refresh_materialized = BashOperator(
        task_id="refresh_materialized_views",
        bash_command='sudo -u postgres psql -d weather_intel -c "REFRESH MATERIALIZED VIEW v_station_comparison; REFRESH MATERIALIZED VIEW v_best_work_weeks;"',
    )

    dbt_docs = BashOperator(
        task_id="regenerate_dbt_docs",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt docs generate {DBT_PROFILES}",
    )

    clear_old_files >> download_all >> parse_and_load >> dbt_run >> dbt_test >> refresh_materialized >> dbt_docs
