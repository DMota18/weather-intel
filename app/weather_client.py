"""Open-Meteo API client for forecasts and recent history."""

import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import OPEN_METEO_FORECAST_URL, OPEN_METEO_HISTORY_URL

ET = ZoneInfo("America/New_York")

HOURLY_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation_probability",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "cloud_cover",
]


async def fetch_forecast_48h(lat: float, lon: float) -> dict:
    """Fetch 48-hour hourly forecast from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_PARAMS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
        "forecast_hours": 48,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_last_24h(lat: float, lon: float) -> dict:
    """Fetch last 24 hours of actual weather from Open-Meteo."""
    now = datetime.now(ET)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,wind_speed_10m,wind_gusts_10m,cloud_cover",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
        "start_date": start_date,
        "end_date": end_date,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def parse_forecast_hours(data: dict) -> list[dict]:
    """Parse Open-Meteo response into list of hourly dicts."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    results = []

    for i, time_str in enumerate(times):
        results.append({
            "time": time_str,
            "hour": int(time_str[11:13]),
            "temp_f": hourly.get("temperature_2m", [None])[i],
            "humidity_pct": hourly.get("relative_humidity_2m", [None])[i],
            "dewpoint_f": hourly.get("dew_point_2m", [None])[i],
            "precip_prob_pct": hourly.get("precipitation_probability", [None])[i],
            "precip_in": hourly.get("precipitation", [None])[i],
            "wind_mph": hourly.get("wind_speed_10m", [None])[i],
            "wind_gust_mph": hourly.get("wind_gusts_10m", [None])[i],
            "cloud_cover_pct": hourly.get("cloud_cover", [None])[i],
        })

    return results


def parse_history_hours(data: dict) -> list[dict]:
    """Parse Open-Meteo history response into list of hourly dicts."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    results = []

    for i, time_str in enumerate(times):
        results.append({
            "time": time_str,
            "hour": int(time_str[11:13]),
            "temp_f": hourly.get("temperature_2m", [None])[i],
            "humidity_pct": hourly.get("relative_humidity_2m", [None])[i],
            "dewpoint_f": hourly.get("dew_point_2m", [None])[i],
            "precip_in": hourly.get("precipitation", [None])[i],
            "wind_mph": hourly.get("wind_speed_10m", [None])[i],
            "wind_gust_mph": hourly.get("wind_gusts_10m", [None])[i],
            "cloud_cover_pct": hourly.get("cloud_cover", [None])[i],
        })

    return results
