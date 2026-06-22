"""
Weather Stream Producer

Polls Open-Meteo every 15 minutes for all stations.
Compares with last-known conditions and publishes deltas to Redis Streams.
Also monitors NWS Alert API for severe weather in Massachusetts.
"""

import asyncio
import json
import time
import redis
import httpx
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import STATIONS
from scoring import score_pour_hour, score_sealer_hour

REDIS = redis.Redis(host="localhost", port=6379, decode_responses=True)
STREAM_WEATHER = "weather:updates"
STREAM_ALERTS = "weather:alerts"
POLL_INTERVAL = 900  # 15 minutes
NWS_POLL_INTERVAL = 300  # 5 minutes for alerts

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

MA_ZONES = ["MAZ005", "MAZ006", "MAZ007", "MAZ008", "MAZ009", "MAZ010",
            "MAZ011", "MAZ012", "MAZ013", "MAZ014", "MAZ015", "MAZ016",
            "MAZ017", "MAZ018", "MAZ019", "MAZ020", "MAZ021", "MAZ022"]


async def fetch_current(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,wind_speed_10m,wind_gusts_10m,cloud_cover",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        return resp.json().get("current", {})


async def fetch_nws_alerts():
    headers = {"User-Agent": "(weather-intel, dylanmota18@gmail.com)"}
    params = {"area": "MA", "status": "actual", "message_type": "alert"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(NWS_ALERTS_URL, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json().get("features", [])


def publish_weather_update(station_slug, station_info, current_data):
    temp = current_data.get("temperature_2m")
    humidity = current_data.get("relative_humidity_2m")
    wind = current_data.get("wind_speed_10m")
    wind_gust = current_data.get("wind_gusts_10m")
    precip = current_data.get("precipitation")
    dewpoint = current_data.get("dew_point_2m")
    cloud = current_data.get("cloud_cover")

    pour_score, pour_factors = score_pour_hour(
        temp_f=temp, humidity_pct=humidity, wind_mph=wind,
        precip_prob_pct=None, dewpoint_f=dewpoint
    )

    last_key = f"weather:last:{station_slug}"
    last_score = REDIS.hget(last_key, "pour_score")

    message = {
        "station": station_slug,
        "station_name": station_info["name"],
        "timestamp": str(int(time.time())),
        "temp_f": str(temp) if temp is not None else "",
        "humidity_pct": str(humidity) if humidity is not None else "",
        "wind_mph": str(wind) if wind is not None else "",
        "wind_gust_mph": str(wind_gust) if wind_gust is not None else "",
        "dewpoint_f": str(dewpoint) if dewpoint is not None else "",
        "cloud_cover_pct": str(cloud) if cloud is not None else "",
        "precip_in": str(precip) if precip is not None else "",
        "pour_score": pour_score or "",
        "pour_factors": json.dumps(pour_factors),
        "score_changed": "1" if last_score and last_score != pour_score else "0",
    }

    REDIS.xadd(STREAM_WEATHER, message, maxlen=1000)

    REDIS.hset(last_key, mapping={
        "pour_score": pour_score or "",
        "temp_f": str(temp) if temp is not None else "",
        "humidity_pct": str(humidity) if humidity is not None else "",
        "wind_mph": str(wind) if wind is not None else "",
        "timestamp": message["timestamp"],
    })

    return pour_score, last_score


def publish_alert(alert_feature):
    props = alert_feature.get("properties", {})
    alert_id = props.get("id", "")

    seen_key = f"alert:seen:{alert_id}"
    if REDIS.exists(seen_key):
        return False

    concrete_keywords = ["freeze", "frost", "wind", "thunder", "hail", "flood", "ice"]
    headline = (props.get("headline") or "").lower()
    event = (props.get("event") or "").lower()
    is_relevant = any(kw in headline or kw in event for kw in concrete_keywords)

    if not is_relevant:
        return False

    message = {
        "alert_id": alert_id,
        "event": props.get("event", ""),
        "headline": props.get("headline", ""),
        "severity": props.get("severity", ""),
        "urgency": props.get("urgency", ""),
        "areas": props.get("areaDesc", ""),
        "onset": props.get("onset", ""),
        "expires": props.get("expires", ""),
        "description": (props.get("description") or "")[:500],
        "timestamp": str(int(time.time())),
    }

    REDIS.xadd(STREAM_ALERTS, message, maxlen=100)
    REDIS.setex(seen_key, 86400, "1")
    return True


async def weather_loop():
    print("Starting weather producer (15-min interval)...")
    while True:
        for slug, info in STATIONS.items():
            try:
                current = await fetch_current(info["lat"], info["lon"])
                score, last = publish_weather_update(slug, info, current)
                status = f"CHANGED {last}->{score}" if last and last != score else score
                print(f"  {slug}: {info['name']} -> {status}")
            except Exception as e:
                print(f"  {slug}: ERROR - {e}")
        print(f"Next poll in {POLL_INTERVAL}s...")
        await asyncio.sleep(POLL_INTERVAL)


async def alert_loop():
    print("Starting NWS alert monitor (5-min interval)...")
    while True:
        try:
            alerts = await fetch_nws_alerts()
            new_count = sum(1 for a in alerts if publish_alert(a))
            if new_count:
                print(f"  Published {new_count} new concrete-relevant alerts")
        except Exception as e:
            print(f"  NWS alert check failed: {e}")
        await asyncio.sleep(NWS_POLL_INTERVAL)


async def main():
    print("Weather Stream Producer starting...")
    print(f"  Stations: {len(STATIONS)}")
    print(f"  Weather poll: every {POLL_INTERVAL}s")
    print(f"  Alert poll: every {NWS_POLL_INTERVAL}s")
    print(f"  Redis streams: {STREAM_WEATHER}, {STREAM_ALERTS}")
    await asyncio.gather(weather_loop(), alert_loop())


if __name__ == "__main__":
    asyncio.run(main())
