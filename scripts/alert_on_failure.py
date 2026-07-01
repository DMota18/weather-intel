"""
Airflow failure callback — logs failures and can be extended with email/Slack/webhook.

Used as on_failure_callback in DAG default_args.
"""

import logging
import json
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"alert","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("alert")

ALERT_LOG = "/home/ubuntu/weather-intel/airflow/logs/failures.jsonl"


def on_failure(context):
    """Called by Airflow when a task fails."""
    dag_id = context.get("dag", {}).dag_id if context.get("dag") else "unknown"
    task_id = context.get("task_instance", {}).task_id if context.get("task_instance") else "unknown"
    execution_date = str(context.get("execution_date", ""))
    exception = str(context.get("exception", ""))

    alert = {
        "timestamp": datetime.now(ET).isoformat(),
        "dag_id": dag_id,
        "task_id": task_id,
        "execution_date": execution_date,
        "error": exception[:500],
    }

    logger.error("PIPELINE FAILURE: %s.%s — %s", dag_id, task_id, exception[:200])

    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(alert) + "\n")
