"""
Airflow failure callback — pushes a notification and logs the failure.

Used as on_failure_callback in DAG default_args.

Notification channels (set either or both as environment variables for the
Airflow worker; without them failures are LOG-ONLY and nobody gets told):
  WI_ALERT_NTFY_TOPIC   — ntfy.sh topic name; free push notifications to a
                          phone via the ntfy app (subscribe to the topic)
  WI_ALERT_WEBHOOK_URL  — webhook receiving {"text": "..."} JSON POSTs
                          (Slack/Discord-compatible incoming webhook)
"""

import logging
import json
import os
import urllib.request
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

    _notify(alert)


def _notify(alert):
    """Push the failure to a human. A broken pipeline means the app quietly
    serves aging data — that must reach a phone, not just a log file."""
    title = f"weather-intel FAILURE: {alert['dag_id']}.{alert['task_id']}"
    body = alert["error"][:300] or "task failed (no exception text)"
    sent = False

    ntfy_topic = os.environ.get("WI_ALERT_NTFY_TOPIC", "")
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=body.encode(),
                headers={"Title": title, "Priority": "high", "Tags": "warning"},
            )
            urllib.request.urlopen(req, timeout=10)
            sent = True
        except Exception as e:
            logger.error("ntfy notification failed: %s", e)

    webhook_url = os.environ.get("WI_ALERT_WEBHOOK_URL", "")
    if webhook_url:
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps({"text": f"{title}\n{body}"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            sent = True
        except Exception as e:
            logger.error("Webhook notification failed: %s", e)

    if not sent:
        logger.warning(
            "NO NOTIFICATION SENT — set WI_ALERT_NTFY_TOPIC or WI_ALERT_WEBHOOK_URL "
            "so pipeline failures reach a human instead of only this log file"
        )
