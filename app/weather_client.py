"""Open-Meteo API client for forecasts and recent history, plus NWS alerts."""

import asyncio
import logging
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import OPEN_METEO_FORECAST_URL

ET = ZoneInfo("America/New_York")
logger = logging.getLogger("weather-intel")

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
NWS_USER_AGENT = "(weather-intel, dylanmota18@gmail.com)"

RETRY_ATTEMPTS = 3


async def _get_json(url: str, params: dict, headers: dict = None, timeout: int = 10) -> dict:
    """GET with retries and exponential backoff (1s, 2s) — a single upstream
    blip must not turn into a failed pour/seal verdict."""
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < RETRY_ATTEMPTS - 1:
                delay = 2 ** attempt
                logger.warning("Fetch failed (attempt %d/%d), retrying in %ds: %s",
                               attempt + 1, RETRY_ATTEMPTS, delay, e)
                await asyncio.sleep(delay)
    raise last_exc

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

    return await _get_json(OPEN_METEO_FORECAST_URL, params)


async def fetch_last_24h(lat: float, lon: float) -> dict:
    """Fetch recent weather from Open-Meteo (yesterday + today).

    NOTE: the response covers whole calendar days — yesterday 00:00 through
    today 23:00 local, with hours after "now" filled with FORECAST values.
    Callers must slice to the true last 24 hours by timestamp; taking the
    tail of the list gives today-including-future, not the last 24h.
    """
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

    return await _get_json(OPEN_METEO_FORECAST_URL, params)


async def fetch_nws_alerts(lat: float, lon: float) -> list[dict]:
    """Fetch active NWS alerts for a point (severe weather awareness)."""
    params = {"point": f"{lat},{lon}", "status": "actual", "message_type": "alert"}
    headers = {"User-Agent": NWS_USER_AGENT}
    data = await _get_json(NWS_ALERTS_URL, params, headers=headers)
    return data.get("features", [])


# Anything Severe/Extreme always passes; keywords catch lower-severity events
# that still matter for concrete work.
ALERT_KEYWORDS = [
    "freeze", "frost", "wind", "thunder", "hail", "flood", "ice",
    "tornado", "heat", "storm", "snow", "blizzard", "winter", "rain", "hurricane",
]

_SEVERITY_RANK = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


def alert_is_relevant(props: dict) -> bool:
    if (props.get("severity") or "") in ("Extreme", "Severe"):
        return True
    text = f"{props.get('event') or ''} {props.get('headline') or ''}".lower()
    return any(kw in text for kw in ALERT_KEYWORDS)


def parse_alerts(features: list[dict]) -> list[dict]:
    """Filter NWS alert features to concrete-relevant ones, most severe first."""
    alerts = []
    for feature in features:
        props = feature.get("properties", {})
        if not alert_is_relevant(props):
            continue
        alerts.append({
            "event": props.get("event", ""),
            "headline": props.get("headline", ""),
            "severity": props.get("severity", ""),
            "urgency": props.get("urgency", ""),
            "areas": props.get("areaDesc", ""),
            "onset": props.get("onset", ""),
            "expires": props.get("expires", ""),
            "description": (props.get("description") or "")[:300],
        })
    alerts.sort(key=lambda a: _SEVERITY_RANK.get(a["severity"], 4))
    return alerts


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
