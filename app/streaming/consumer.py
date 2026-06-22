"""
Weather Stream Consumer

Reads from Redis Streams and:
1. Updates the Postgres forecast cache with latest conditions
2. Maintains a list of active WebSocket connections
3. Pushes real-time updates to connected dashboards
"""

import asyncio
import json
import time
import redis
import psycopg2
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import DB_CONFIG

REDIS = redis.Redis(host="localhost", port=6379, decode_responses=True)
STREAM_WEATHER = "weather:updates"
STREAM_ALERTS = "weather:alerts"

# WebSocket connections managed by the FastAPI app — consumer writes to a pubsub channel
PUBSUB_CHANNEL = "weather:live"


def process_weather_update(message):
    """Store latest conditions and notify WebSocket subscribers."""
    station = message.get("station", "")
    score_changed = message.get("score_changed") == "1"

    # Publish to Redis pubsub for WebSocket broadcast
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
        print(f"  SCORE CHANGE: {station} -> {message.get('pour_score')}")


def process_alert(message):
    """Forward NWS alert to WebSocket subscribers."""
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
    print(f"  ALERT: {message.get('event')} - {message.get('headline')}")


def run():
    print("Weather Stream Consumer starting...")
    print(f"  Reading: {STREAM_WEATHER}, {STREAM_ALERTS}")
    print(f"  Publishing to: {PUBSUB_CHANNEL}")

    last_ids = {
        STREAM_WEATHER: "$",
        STREAM_ALERTS: "$",
    }

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

        except redis.ConnectionError:
            print("Redis connection lost, reconnecting...")
            time.sleep(5)
        except Exception as e:
            print(f"Consumer error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    run()
