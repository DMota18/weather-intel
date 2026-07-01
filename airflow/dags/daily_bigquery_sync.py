"""
Daily BigQuery Sync DAG: Export Postgres → BigQuery

Runs daily after the ETL DAG completes. Keeps the analytical warehouse
in sync with the operational database.
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
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "daily_bigquery_sync",
    default_args=default_args,
    description="Daily sync: Postgres operational DB → BigQuery analytical warehouse",
    schedule_interval="30 10 * * *",  # 6:30AM ET = 10:30 UTC, 30 min after ETL
    start_date=datetime(2026, 6, 24),
    catchup=False,
    tags=["bigquery", "sync", "warehouse"],
) as dag:

    sync_to_bq = BashOperator(
        task_id="sync_postgres_to_bigquery",
        bash_command=f"cd {PROJECT}/scripts && {VENV}/python sync_to_bigquery.py",
    )
