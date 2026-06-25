"""Weather Intelligence API — FastAPI application."""

import os
import decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import asyncio
import threading
import redis
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import psycopg2
import psycopg2.pool
import psycopg2.extras

from config import DB_CONFIG, STATIONS
from weather_client import fetch_forecast_48h, fetch_last_24h, parse_forecast_hours, parse_history_hours
from scoring import score_pour_hour, score_sealer_hour, score_cure_window, find_best_window

ET = ZoneInfo("America/New_York")

app = FastAPI(title="Weather Intelligence", version="1.1.0")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# --- Connection pool (fix #8) ---
db_pool = psycopg2.pool.SimpleConnectionPool(1, 5, **DB_CONFIG)


@contextmanager
def get_db():
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)


# --- Forecast cache (fix #9) ---
FORECAST_CACHE_TTL = timedelta(hours=3)
_forecast_cache = {}


def _get_cached_forecast(station_id: str, cache_type: str):
    key = f"{station_id}:{cache_type}"
    if key in _forecast_cache:
        data, fetched_at = _forecast_cache[key]
        if datetime.now(ET) - fetched_at < FORECAST_CACHE_TTL:
            return data
        del _forecast_cache[key]
    return None


def _set_cached_forecast(station_id: str, cache_type: str, data):
    key = f"{station_id}:{cache_type}"
    _forecast_cache[key] = (data, datetime.now(ET))


# --- Station name lookup ---
STATION_ID_TO_DB_NAME = {}


def _init_station_names():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT station_id, name FROM stations")
            for row in cur.fetchall():
                STATION_ID_TO_DB_NAME[row[0]] = row[1]


def _get_db_station_name(town_slug):
    if not STATION_ID_TO_DB_NAME:
        _init_station_names()
    station_id = STATIONS[town_slug]["station_id"]
    return STATION_ID_TO_DB_NAME.get(station_id, STATIONS[town_slug]["name"])


# --- Date validation helper (fix #6) ---
def _parse_date(date_str: str) -> str:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str}. Use YYYY-MM-DD.")


# --- Helpers ---
def _serialize_row(row):
    return {k: (float(v) if isinstance(v, decimal.Decimal) else str(v) if hasattr(v, 'isoformat') else v) for k, v in row.items()}


def _query_view(query, params=None):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            rows = cur.fetchall()
    return [_serialize_row(row) for row in rows]


# ============================================================
# CORE ENDPOINTS
# ============================================================

@app.get("/api/v1/towns")
async def list_towns():
    """List available towns."""
    return {slug: {"name": info["name"], "covers": info["covers"]} for slug, info in STATIONS.items()}


@app.get("/api/v1/forecast/{town}")
async def get_forecast(town: str):
    """48-hour forecast with pour scoring.

    Note: scoring uses hourly temperature, humidity, wind, precipitation probability,
    and dew point. This differs from historical daily scores which use daily aggregates
    (temp_max, actual precipitation). Hourly scoring is more granular and actionable
    for scheduling.
    """
    if town not in STATIONS:
        raise HTTPException(status_code=404, detail=f"Unknown town: {town}. Available: {list(STATIONS.keys())}")

    station = STATIONS[town]

    cached = _get_cached_forecast(station["station_id"], "forecast48")
    if cached:
        hours = cached
    else:
        data = await fetch_forecast_48h(station["lat"], station["lon"])
        hours = parse_forecast_hours(data)
        _set_cached_forecast(station["station_id"], "forecast48", hours)

    scored_hours = []
    for h in hours:
        score, factors = score_pour_hour(
            temp_f=h["temp_f"],
            humidity_pct=h["humidity_pct"],
            wind_mph=h["wind_mph"],
            precip_prob_pct=h["precip_prob_pct"],
            dewpoint_f=h["dewpoint_f"],
        )
        scored_hours.append({**h, "pour_score": score, "pour_factors": factors})

    best_window = find_best_window([{"hour": h["hour"], "score": h["pour_score"]} for h in scored_hours])

    days = {}
    for h in scored_hours:
        day_key = h["time"][:10]
        if day_key not in days:
            days[day_key] = []
        days[day_key].append(h)

    day_summaries = []
    for day_key, day_hours in days.items():
        scores = [h["pour_score"] for h in day_hours if h["pour_score"] and 7 <= h["hour"] <= 17]
        if "red" in scores:
            day_score = "red"
        elif "yellow" in scores:
            day_score = "yellow"
        else:
            day_score = "green"

        temps = [h["temp_f"] for h in day_hours if h["temp_f"] is not None]
        day_window = find_best_window([{"hour": h["hour"], "score": h["pour_score"]} for h in day_hours])

        warnings = []
        for h in day_hours:
            if h.get("pour_factors", {}).get("wind") == "red":
                warnings.append(f"Wind {h['wind_mph']:.0f}mph at {h['hour']:02d}:00")
                break
            if h.get("pour_factors", {}).get("precipitation") == "red":
                warnings.append(f"Rain {h['precip_prob_pct']:.0f}% at {h['hour']:02d}:00")
                break

        day_summaries.append({
            "date": day_key,
            "score": day_score,
            "temp_high_f": max(temps) if temps else None,
            "temp_low_f": min(temps) if temps else None,
            "best_window": day_window,
            "warnings": warnings,
            "hours": day_hours,
        })

    return {
        "town": station["name"],
        "covers": station["covers"],
        "best_window": best_window,
        "days": day_summaries,
    }


@app.get("/api/v1/sealer-check/{town}")
async def sealer_check(town: str):
    """Check if conditions are safe to apply sealer (last 24h + next 24h)."""
    if town not in STATIONS:
        raise HTTPException(status_code=404, detail=f"Unknown town: {town}. Available: {list(STATIONS.keys())}")

    station = STATIONS[town]

    # Last 24h — use cache
    cached_hist = _get_cached_forecast(station["station_id"], "history24")
    if cached_hist:
        history_hours = cached_hist
    else:
        history_data = await fetch_last_24h(station["lat"], station["lon"])
        history_hours = parse_history_hours(history_data)
        _set_cached_forecast(station["station_id"], "history24", history_hours)

    # Forecast — use cache
    cached_fc = _get_cached_forecast(station["station_id"], "forecast48")
    if cached_fc:
        forecast_hours = cached_fc
    else:
        forecast_data = await fetch_forecast_48h(station["lat"], station["lon"])
        forecast_hours = parse_forecast_hours(forecast_data)
        _set_cached_forecast(station["station_id"], "forecast48", forecast_hours)

    recent_hours = history_hours[-24:] if len(history_hours) >= 24 else history_hours

    total_precip_24h = sum(h["precip_in"] or 0 for h in recent_hours)
    max_humidity = max((h["humidity_pct"] or 0) for h in recent_hours) if recent_hours else None
    min_temp = min((h["temp_f"] for h in recent_hours if h["temp_f"] is not None), default=None)
    max_temp = max((h["temp_f"] for h in recent_hours if h["temp_f"] is not None), default=None)

    next_24h = forecast_hours[:24]
    max_precip_prob = max((h["precip_prob_pct"] or 0) for h in next_24h) if next_24h else None

    current = recent_hours[-1] if recent_hours else {}

    score, factors = score_sealer_hour(
        temp_f=current.get("temp_f"),
        humidity_pct=current.get("humidity_pct"),
        precip_last_24h_in=total_precip_24h,
        precip_prob_next_24h=max_precip_prob,
        dewpoint_f=current.get("dewpoint_f"),
    )

    details = []
    if total_precip_24h == 0:
        details.append("No rain in last 24h")
    else:
        details.append(f"Rain in last 24h: {total_precip_24h:.2f} in")

    if min_temp is not None:
        details.append(f"Temp range: {min_temp:.0f}-{max_temp:.0f}°F")
    if current.get("humidity_pct") is not None:
        details.append(f"Current humidity: {current['humidity_pct']:.0f}%")
    if max_precip_prob is not None:
        details.append(f"Max rain chance next 24h: {max_precip_prob:.0f}%")
    if current.get("dewpoint_f") is not None and current.get("temp_f") is not None:
        spread = current["temp_f"] - current["dewpoint_f"]
        details.append(f"Dew point spread: {spread:.1f}°F")

    return {
        "town": station["name"],
        "covers": station["covers"],
        "score": score,
        "verdict": "SAFE TO SEAL" if score == "green" else ("USE CAUTION" if score == "yellow" else "DO NOT SEAL"),
        "factors": factors,
        "details": details,
        "current": {
            "temp_f": current.get("temp_f"),
            "humidity_pct": current.get("humidity_pct"),
            "dewpoint_f": current.get("dewpoint_f"),
            "wind_mph": current.get("wind_mph"),
        },
        "last_24h": {
            "total_precip_in": round(total_precip_24h, 2),
            "temp_low_f": min_temp,
            "temp_high_f": max_temp,
            "max_humidity_pct": max_humidity,
        },
        "next_24h_max_precip_prob": max_precip_prob,
        "hours": recent_hours,
    }


@app.get("/api/v1/weather/{town}/{date}")
async def get_historical(town: str, date: str):
    """Look up historical weather from the database.

    Note: historical scores use daily aggregates (temp_max for temperature,
    actual precipitation amount). Live forecast scores use hourly granularity
    and precipitation probability. Both are valid for their context.
    """
    if town not in STATIONS:
        raise HTTPException(status_code=404, detail=f"Unknown town: {town}")

    validated_date = _parse_date(date)
    station = STATIONS[town]

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM daily_weather
                   WHERE station_id = %s AND observation_date = %s""",
                (station["station_id"], validated_date)
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"No data for {town} on {date}")

    return {
        "town": station["name"],
        "date": str(row["observation_date"]),
        "source": "database",
        "temp_max_f": float(row["temp_max_f"]) if row["temp_max_f"] else None,
        "temp_min_f": float(row["temp_min_f"]) if row["temp_min_f"] else None,
        "temp_mean_f": float(row["temp_mean_f"]) if row["temp_mean_f"] else None,
        "precip_in": float(row["precip_in"]) if row["precip_in"] else None,
        "snow_in": float(row["snow_in"]) if row["snow_in"] else None,
        "wind_avg_mph": float(row["wind_avg_mph"]) if row["wind_avg_mph"] else None,
        "wind_max_mph": float(row["wind_max_mph"]) if row["wind_max_mph"] else None,
        "pour_score": row["pour_score"],
        "sealer_score": row["sealer_score"],
        "score_details": row["score_details"],
    }


@app.get("/api/v1/cure-check/{town}")
async def cure_check(town: str):
    """Score the 48-hour curing window — will conditions allow fresh concrete to cure properly?

    Checks freeze risk, rain probability, extreme heat, and wind drying
    across the full 48-hour window after a hypothetical pour right now.
    """
    if town not in STATIONS:
        raise HTTPException(status_code=404, detail=f"Unknown town: {town}. Available: {list(STATIONS.keys())}")

    station = STATIONS[town]

    cached = _get_cached_forecast(station["station_id"], "forecast48")
    if cached:
        forecast_hours = cached
    else:
        data = await fetch_forecast_48h(station["lat"], station["lon"])
        forecast_hours = parse_forecast_hours(data)
        _set_cached_forecast(station["station_id"], "forecast48", forecast_hours)

    overall, factors, issues = score_cure_window(forecast_hours)

    temps = [h["temp_f"] for h in forecast_hours if h.get("temp_f") is not None]

    return {
        "town": station["name"],
        "covers": station["covers"],
        "score": overall,
        "verdict": "SAFE TO POUR & CURE" if overall == "green" else ("POUR WITH CAUTION" if overall == "yellow" else "DO NOT POUR"),
        "factors": factors,
        "issues": issues,
        "window": {
            "hours": len(forecast_hours),
            "temp_low_f": min(temps) if temps else None,
            "temp_high_f": max(temps) if temps else None,
        },
    }


# ============================================================
# ANALYTICS ENDPOINTS
# ============================================================

@app.get("/api/v1/analytics/seasonal")
async def analytics_seasonal(town: str = None, year: int = None):
    """Monthly pour/sealer viability by station and year."""
    q = "SELECT * FROM v_seasonal_analysis WHERE 1=1"
    params = []
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    if year:
        q += " AND year = %s"
        params.append(year)
    q += " ORDER BY station_name, year, month_num"
    return _query_view(q, params)


@app.get("/api/v1/analytics/streaks")
async def analytics_streaks(town: str = None, streak_type: str = None, min_days: int = 3):
    """Longest dry and wet streaks by station."""
    q = "SELECT * FROM v_weather_streaks WHERE streak_days >= %s"
    params = [min_days]
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    if streak_type in ("DRY", "WET"):
        q += " AND streak_type = %s"
        params.append(streak_type)
    q += " ORDER BY streak_days DESC LIMIT 50"
    return _query_view(q, params)


@app.get("/api/v1/analytics/anomalies")
async def analytics_anomalies(town: str = None, flag: str = "EXTREME"):
    """Temperature anomaly days."""
    q = "SELECT * FROM v_temperature_anomalies WHERE anomaly_flag = %s"
    params = [flag]
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    q += " ORDER BY ABS(temp_anomaly) DESC LIMIT 50"
    return _query_view(q, params)


@app.get("/api/v1/analytics/quality")
async def analytics_quality():
    """Data quality audit across all stations."""
    return _query_view("SELECT * FROM v_data_quality ORDER BY coverage_pct")


@app.get("/api/v1/analytics/season-boundaries")
async def analytics_season_boundaries(town: str = None):
    """Concrete season start/end dates per year."""
    q = "SELECT * FROM v_season_boundaries WHERE 1=1"
    params = []
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    q += " ORDER BY station_name, year"
    return _query_view(q, params)


@app.get("/api/v1/analytics/year-over-year")
async def analytics_yoy(town: str = None):
    """Year-over-year monthly comparisons."""
    q = "SELECT * FROM v_year_over_year WHERE prev_year_avg_temp IS NOT NULL"
    params = []
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    q += " ORDER BY station_name, month, year"
    return _query_view(q, params)


@app.get("/api/v1/analytics/best-weeks")
async def analytics_best_weeks(town: str = None, year: int = None):
    """Best 5-day work windows ranked by green days."""
    q = "SELECT * FROM v_best_work_weeks WHERE year_rank <= 10"
    params = []
    if town and town in STATIONS:
        q += " AND station_name = %s"
        params.append(_get_db_station_name(town))
    if year:
        q += " AND EXTRACT(YEAR FROM week_ending) = %s"
        params.append(year)
    q += " ORDER BY green_in_5day DESC, avg_high_5day DESC LIMIT 50"
    return _query_view(q, params)


@app.get("/api/v1/analytics/station-comparison")
async def analytics_station_comparison():
    """Cross-station weather correlation and disagreement rates."""
    return _query_view("SELECT * FROM v_station_comparison ORDER BY pct_disagree DESC")


# ============================================================
# JOB-WEATHER CORRELATION
# ============================================================

@app.get("/api/v1/jobs")
async def list_jobs():
    """All jobs with weather summary."""
    return _query_view("SELECT * FROM v_job_weather_summary ORDER BY start_date DESC")


@app.get("/api/v1/jobs/{job_id}")
async def get_job_weather(job_id: int):
    """Day-by-day weather for a specific job."""
    rows = _query_view(
        "SELECT * FROM v_job_weather WHERE job_id = %s ORDER BY observation_date",
        [job_id]
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id}")
    return rows


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """About page — explains the project for non-technical visitors."""
    return templates.TemplateResponse(request, "about.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, town: str = "worcester"):
    """Main dashboard page."""
    if town not in STATIONS:
        town = "worcester"

    station = STATIONS[town]

    try:
        cached = _get_cached_forecast(station["station_id"], "forecast48")
        if cached:
            forecast_hours = cached
        else:
            forecast_data = await fetch_forecast_48h(station["lat"], station["lon"])
            forecast_hours = parse_forecast_hours(forecast_data)
            _set_cached_forecast(station["station_id"], "forecast48", forecast_hours)
    except Exception:
        forecast_hours = []

    try:
        cached_hist = _get_cached_forecast(station["station_id"], "history24")
        if cached_hist:
            history_hours = cached_hist
        else:
            history_data = await fetch_last_24h(station["lat"], station["lon"])
            history_hours = parse_history_hours(history_data)
            _set_cached_forecast(station["station_id"], "history24", history_hours)
    except Exception:
        history_hours = []

    scored_forecast = []
    for h in forecast_hours:
        score, factors = score_pour_hour(
            temp_f=h["temp_f"],
            humidity_pct=h["humidity_pct"],
            wind_mph=h["wind_mph"],
            precip_prob_pct=h["precip_prob_pct"],
            dewpoint_f=h["dewpoint_f"],
        )
        scored_forecast.append({**h, "pour_score": score, "pour_factors": factors})

    recent_hours = history_hours[-24:] if len(history_hours) >= 24 else history_hours
    total_precip_24h = sum(h["precip_in"] or 0 for h in recent_hours)
    next_24h = forecast_hours[:24]
    max_precip_prob = max((h["precip_prob_pct"] or 0) for h in next_24h) if next_24h else 0
    current = recent_hours[-1] if recent_hours else {}

    sealer_score, sealer_factors = score_sealer_hour(
        temp_f=current.get("temp_f"),
        humidity_pct=current.get("humidity_pct"),
        precip_last_24h_in=total_precip_24h,
        precip_prob_next_24h=max_precip_prob,
        dewpoint_f=current.get("dewpoint_f"),
    )

    days = {}
    for h in scored_forecast:
        day_key = h["time"][:10]
        if day_key not in days:
            days[day_key] = []
        days[day_key].append(h)

    day_summaries = []
    for day_key, day_hours in days.items():
        scores = [h["pour_score"] for h in day_hours if h["pour_score"] and 7 <= h["hour"] <= 17]
        day_score = "red" if "red" in scores else ("yellow" if "yellow" in scores else "green")
        temps = [h["temp_f"] for h in day_hours if h["temp_f"] is not None]
        day_window = find_best_window([{"hour": h["hour"], "score": h["pour_score"]} for h in day_hours])
        day_summaries.append({
            "date": day_key,
            "score": day_score,
            "temp_high": max(temps) if temps else None,
            "temp_low": min(temps) if temps else None,
            "best_window": day_window,
            "hours": day_hours,
        })

    context = {
        "request": request,
        "town": town,
        "station": station,
        "stations": STATIONS,
        "sealer_score": sealer_score,
        "sealer_factors": sealer_factors,
        "sealer_details": {
            "total_precip_24h": round(total_precip_24h, 2),
            "current_temp": current.get("temp_f"),
            "current_humidity": current.get("humidity_pct"),
            "max_precip_prob": max_precip_prob,
            "dewpoint_spread": round(current["temp_f"] - current["dewpoint_f"], 1) if current.get("temp_f") and current.get("dewpoint_f") else None,
        },
        "days": day_summaries,
        "forecast_hours": scored_forecast,
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


# ============================================================
# WEBSOCKET — Real-time weather updates
# ============================================================

connected_clients: list[WebSocket] = []
PUBSUB_CHANNEL = "weather:live"


async def redis_listener():
    """Background task: subscribe to Redis pubsub and broadcast to WebSocket clients."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(PUBSUB_CHANNEL)

    loop = asyncio.get_event_loop()

    def _listen():
        for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                asyncio.run_coroutine_threadsafe(_broadcast(data), loop)

    thread = threading.Thread(target=_listen, daemon=True)
    thread.start()


async def _broadcast(data: str):
    """Send data to all connected WebSocket clients."""
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


@app.on_event("startup")
async def start_redis_listener():
    await redis_listener()


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """Real-time weather updates via WebSocket.

    Clients connect and receive JSON messages whenever:
    - Weather conditions update (every 15 min)
    - Pour/sealer scores change
    - NWS issues a severe weather alert relevant to concrete work
    """
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(ws)


@app.get("/api/v1/stream/status")
async def stream_status():
    """Check streaming system health."""
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    try:
        weather_len = r.xlen("weather:updates")
        alerts_len = r.xlen("weather:alerts")
        last_entries = r.xrevrange("weather:updates", count=1)
        last_update = last_entries[0][1] if last_entries else None
    except Exception as e:
        return {"status": "error", "detail": str(e)}

    return {
        "status": "ok",
        "connected_clients": len(connected_clients),
        "stream_weather_entries": weather_len,
        "stream_alerts_entries": alerts_len,
        "last_update": last_update,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
