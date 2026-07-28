"""
Weather Stream Consumer

Reads from Redis Streams and:
1. Maintains a list of active WebSocket connections
2. Pushes real-time updates to connected dashboards
"""

import json
import logging
import time
import redis
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"consumer","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("consumer")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REDIS = redis.Redis(host="localhost", port=6379, decode_responses=True)
STREAM_WEATHER = "weather:updates"
STREAM_ALERTS = "weather:alerts"
PUBSUB_CHANNEL = "weather:live"


def process_weather_update(message):
    station = message.get("station", "")
    score_changed = message.get("score_changed") == "1"

    payload = {
        "type": "weather_update",
        "station": station,
        "station_name": message.get("station_name", ""),
        "temp_f": message.get("temp_f", ""),
        "humidity_pct": message.get("humidity_pct", ""),
        "wind_mph": message.get("wind_mph", ""),
        "dewpoint_f": message.get("dewpoint_f", ""),
        "cloud_cover_pct": message.get("cloud_cover_pct", ""),
        "pour_score": message.get("pour_score", ""),
        "score_changed": score_changed,
    }
    REDIS.publish(PUBSUB_CHANNEL, json.dumps(payload))

    if score_changed:
        logger.warning("SCORE CHANGE: %s -> %s", station, message.get("pour_score"))


def process_alert(message):
    payload = {
        "type": "nws_alert",
        "event": message.get("event", ""),
        "headline": message.get("headline", ""),
        "severity": message.get("severity", ""),
        "areas": message.get("areas", ""),
        "onset": message.get("onset", ""),
        "expires": message.get("expires", ""),
    }
    REDIS.publish(PUBSUB_CHANNEL, json.dumps(payload))
    logger.warning("ALERT: %s - %s", message.get("event"), message.get("headline"))


def _checkpoint_key(stream_name):
    return f"consumer:last:{stream_name}"


def _load_last_ids():
    """Resume from the persisted checkpoint so a restart doesn't drop
    messages published while the consumer was down ('$' skips backlog)."""
    last_ids = {}
    for stream in (STREAM_WEATHER, STREAM_ALERTS):
        try:
            last_ids[stream] = REDIS.get(_checkpoint_key(stream)) or "$"
        except redis.ConnectionError:
            last_ids[stream] = "$"
    return last_ids


def run():
    logger.info("Weather Stream Consumer starting — reading %s, %s", STREAM_WEATHER, STREAM_ALERTS)

    last_ids = _load_last_ids()
    logger.info("Resuming from checkpoints: %s", last_ids)

    while True:
        try:
            results = REDIS.xread(
                {STREAM_WEATHER: last_ids[STREAM_WEATHER],
                 STREAM_ALERTS: last_ids[STREAM_ALERTS]},
                count=10,
                block=5000,
            )

            for stream_name, messages in results:
                for msg_id, msg_data in messages:
                    last_ids[stream_name] = msg_id

                    if stream_name == STREAM_WEATHER:
                        process_weather_update(msg_data)
                    elif stream_name == STREAM_ALERTS:
                        process_alert(msg_data)

                    REDIS.set(_checkpoint_key(stream_name), msg_id)

        except redis.ConnectionError:
            logger.error("Redis connection lost, reconnecting in 5s")
            time.sleep(5)
        except Exception as e:
            logger.error("Consumer error: %s", e)
            time.sleep(1)


if __name__ == "__main__":
    run()
