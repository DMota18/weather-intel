"""Concrete work scoring engine.

Fail-safe contract: a None input means "no data", and no data must never
improve a verdict. Any missing core input adds a "data" factor at yellow
(so the hour can never score green), and an hour with no usable inputs
scores None — which every aggregation downstream must treat as non-green.
"""

# Precipitation totals below this are sensor noise, not rain.
TRACE_PRECIP_IN = 0.005


def score_pour_hour(temp_f, humidity_pct, wind_mph, precip_prob_pct, dewpoint_f=None):
    factors = {}

    if temp_f is not None:
        if 50 <= temp_f <= 90:
            factors["temperature"] = "green"
        elif 40 <= temp_f < 50 or 90 < temp_f <= 95:
            factors["temperature"] = "yellow"
        else:
            factors["temperature"] = "red"

    if humidity_pct is not None:
        if 25 <= humidity_pct <= 70:
            factors["humidity"] = "green"
        elif 15 <= humidity_pct < 25 or 70 < humidity_pct <= 85:
            factors["humidity"] = "yellow"
        else:
            factors["humidity"] = "red"

    if wind_mph is not None:
        if wind_mph < 10:
            factors["wind"] = "green"
        elif wind_mph < 20:
            factors["wind"] = "yellow"
        else:
            factors["wind"] = "red"

    if precip_prob_pct is not None:
        if precip_prob_pct < 15:
            factors["precipitation"] = "green"
        elif precip_prob_pct < 40:
            factors["precipitation"] = "yellow"
        else:
            factors["precipitation"] = "red"

    if dewpoint_f is not None and temp_f is not None:
        spread = temp_f - dewpoint_f
        if spread > 10:
            factors["dewpoint"] = "green"
        elif spread > 5:
            factors["dewpoint"] = "yellow"
        else:
            factors["dewpoint"] = "red"

    if not factors:
        return None, factors

    if temp_f is None or humidity_pct is None or wind_mph is None or precip_prob_pct is None:
        factors["data"] = "yellow"

    if "red" in factors.values():
        return "red", factors
    elif "yellow" in factors.values():
        return "yellow", factors
    else:
        return "green", factors


def score_sealer_hour(temp_f, humidity_pct, precip_last_24h_in, precip_prob_next_24h,
                      dewpoint_f=None, wind_mph=None, min_temp_next_12h=None):
    factors = {}

    if temp_f is not None:
        if 50 <= temp_f <= 90:
            factors["temperature"] = "green"
        elif 40 <= temp_f < 50:
            factors["temperature"] = "yellow"
        else:
            factors["temperature"] = "red"

    # Sealer cures over hours — a warm afternoon reading hides a cold night
    if min_temp_next_12h is not None:
        if min_temp_next_12h >= 50:
            factors["cure_temp"] = "green"
        elif min_temp_next_12h >= 40:
            factors["cure_temp"] = "yellow"
        else:
            factors["cure_temp"] = "red"

    # Overspray drift and wind-blown debris onto wet sealer
    if wind_mph is not None:
        if wind_mph < 10:
            factors["wind"] = "green"
        elif wind_mph < 15:
            factors["wind"] = "yellow"
        else:
            factors["wind"] = "red"

    if humidity_pct is not None:
        if humidity_pct < 70:
            factors["humidity"] = "green"
        elif humidity_pct < 85:
            factors["humidity"] = "yellow"
        else:
            factors["humidity"] = "red"

    if precip_last_24h_in is not None:
        if precip_last_24h_in < TRACE_PRECIP_IN:
            factors["rain_last_24h"] = "green"
        elif precip_last_24h_in < 0.1:
            factors["rain_last_24h"] = "yellow"
        else:
            factors["rain_last_24h"] = "red"

    if precip_prob_next_24h is not None:
        if precip_prob_next_24h < 10:
            factors["rain_next_24h"] = "green"
        elif precip_prob_next_24h < 40:
            factors["rain_next_24h"] = "yellow"
        else:
            factors["rain_next_24h"] = "red"

    if dewpoint_f is not None and temp_f is not None:
        spread = temp_f - dewpoint_f
        if spread > 10:
            factors["dewpoint"] = "green"
        elif spread > 5:
            factors["dewpoint"] = "yellow"
        else:
            factors["dewpoint"] = "red"

    if not factors:
        return None, factors

    if (temp_f is None or humidity_pct is None or precip_last_24h_in is None
            or precip_prob_next_24h is None or wind_mph is None or min_temp_next_12h is None):
        factors["data"] = "yellow"

    if "red" in factors.values():
        return "red", factors
    elif "yellow" in factors.values():
        return "yellow", factors
    else:
        return "green", factors


def score_cure_window(hourly_forecast: list[dict]) -> tuple:
    """Score the 48-hour curing window after a pour.

    Concrete needs 24-48h of favorable conditions to cure properly:
    - No freezing (below 40°F kills the hydration reaction)
    - No heavy rain (washes out surface, causes scaling)
    - Moderate humidity preferred (prevents too-rapid moisture loss)
    """
    factors = {}
    issues = []

    if not hourly_forecast:
        return None, factors, issues

    temps = [h["temp_f"] for h in hourly_forecast if h.get("temp_f") is not None]
    first_24h = hourly_forecast[:24]
    probs_24h = [h["precip_prob_pct"] for h in first_24h if h.get("precip_prob_pct") is not None]
    precips_24h = [h["precip_in"] for h in first_24h if h.get("precip_in") is not None]
    winds_24h = [h["wind_mph"] for h in first_24h if h.get("wind_mph") is not None]
    gusts_24h = [h["wind_gust_mph"] for h in first_24h if h.get("wind_gust_mph") is not None]

    if not temps and not probs_24h and not precips_24h and not winds_24h:
        issues.append("No usable forecast data — cannot assess cure window")
        return None, factors, issues

    missing = []

    # Check for freeze risk in the full window
    min_temp = min(temps) if temps else None

    if min_temp is not None:
        if min_temp >= 50:
            factors["freeze_risk"] = "green"
        elif min_temp >= 40:
            factors["freeze_risk"] = "yellow"
            freeze_hours = [h for h in hourly_forecast if h.get("temp_f") is not None and h["temp_f"] < 50]
            if freeze_hours:
                issues.append(f"Temp drops to {min_temp:.0f}°F — consider blankets/enclosures")
        else:
            factors["freeze_risk"] = "red"
            issues.append(f"Freeze risk: low of {min_temp:.0f}°F — concrete will not cure properly")
    else:
        missing.append("temperature")

    # Check for rain risk in the first 24h (most critical)
    if probs_24h or precips_24h:
        max_precip_prob_24h = max(probs_24h) if probs_24h else 0
        total_precip_24h = sum(precips_24h) if precips_24h else 0
        if not probs_24h or not precips_24h:
            missing.append("precipitation")

        if max_precip_prob_24h < 15 and total_precip_24h < 0.1:
            factors["rain_during_cure"] = "green"
        elif max_precip_prob_24h < 40:
            factors["rain_during_cure"] = "yellow"
            issues.append(f"Rain chance up to {max_precip_prob_24h:.0f}% in first 24h — have tarps ready")
        else:
            factors["rain_during_cure"] = "red"
            issues.append(f"Rain likely ({max_precip_prob_24h:.0f}%) in first 24h — will damage fresh surface")
    else:
        missing.append("precipitation")

    # Check for rain risk in hours 24-48 (secondary)
    second_24h = hourly_forecast[24:48]
    if second_24h:
        probs_48h = [h["precip_prob_pct"] for h in second_24h if h.get("precip_prob_pct") is not None]
        if probs_48h and max(probs_48h) >= 40:
            if factors.get("rain_during_cure") != "red":
                factors["rain_during_cure"] = "yellow"
                issues.append(f"Rain likely in hours 24-48 ({max(probs_48h):.0f}%) — less critical but monitor")

    # Check for extreme heat (rapid moisture loss)
    max_temp = max(temps) if temps else None
    if max_temp is not None:
        if max_temp <= 90:
            factors["heat_stress"] = "green"
        elif max_temp <= 95:
            factors["heat_stress"] = "yellow"
            issues.append(f"High of {max_temp:.0f}°F — mist cure or apply curing compound")
        else:
            factors["heat_stress"] = "red"
            issues.append(f"Extreme heat ({max_temp:.0f}°F) — rapid moisture loss, high crack risk")

    # Check for high wind (surface drying) — sustained and gusts scored
    # separately (gusts drive plastic-shrinkage cracking; higher thresholds),
    # worst of the two wins
    wind_levels = []
    if winds_24h:
        max_wind = max(winds_24h)
        if max_wind < 15:
            wind_levels.append("green")
        elif max_wind < 25:
            wind_levels.append("yellow")
            issues.append(f"Sustained wind to {max_wind:.0f}mph — accelerates surface drying")
        else:
            wind_levels.append("red")
            issues.append(f"High sustained wind ({max_wind:.0f}mph) — significant surface drying and crack risk")
    else:
        missing.append("wind")

    if gusts_24h:
        max_gust = max(gusts_24h)
        if max_gust < 25:
            wind_levels.append("green")
        elif max_gust < 35:
            wind_levels.append("yellow")
            issues.append(f"Wind gusts to {max_gust:.0f}mph — accelerates surface drying")
        else:
            wind_levels.append("red")
            issues.append(f"Severe wind gusts ({max_gust:.0f}mph) — high surface-drying and crack risk")

    if wind_levels:
        factors["wind_drying"] = ("red" if "red" in wind_levels
                                  else "yellow" if "yellow" in wind_levels
                                  else "green")

    if missing:
        factors["data"] = "yellow"
        issues.append(f"Missing forecast data ({', '.join(missing)}) — treat with caution")

    # Overall
    if "red" in factors.values():
        overall = "red"
    elif "yellow" in factors.values():
        overall = "yellow"
    else:
        overall = "green"

    return overall, factors, issues


def summarize_day(day_hours, start_hour=7, end_hour=17):
    """Aggregate hourly pour scores into a day verdict for the working window.

    Fail-safe: a day with zero scored working hours returns None ("no data",
    never green), and any unscored working hour caps the day at yellow.
    end_hour is EXCLUSIVE — the default 7..17 is 7AM–5PM, the same window
    find_best_window uses, so day colors and window labels always agree.
    """
    window = [h for h in day_hours if start_hour <= h["hour"] < end_hour]
    scores = [h.get("pour_score") for h in window if h.get("pour_score")]

    if not scores:
        return None
    if "red" in scores:
        return "red"
    if "yellow" in scores or len(scores) < len(window):
        return "yellow"
    return "green"


def find_best_window(hourly_scores, start_hour=7, end_hour=17):
    """Find longest contiguous green window within working hours."""
    best_start = None
    best_length = 0
    current_start = None
    current_length = 0

    for entry in hourly_scores:
        hour = entry["hour"]
        if hour < start_hour or hour >= end_hour:
            current_start = None
            current_length = 0
            continue

        if entry["score"] == "green":
            if current_start is None:
                current_start = hour
                current_length = 1
            else:
                current_length += 1
            if current_length > best_length:
                best_length = current_length
                best_start = current_start
        else:
            current_start = None
            current_length = 0

    if best_start is None:
        # Fall back to longest yellow-or-better window
        current_start = None
        current_length = 0
        for entry in hourly_scores:
            hour = entry["hour"]
            if hour < start_hour or hour >= end_hour:
                current_start = None
                current_length = 0
                continue
            if entry["score"] in ("green", "yellow"):
                if current_start is None:
                    current_start = hour
                    current_length = 1
                else:
                    current_length += 1
                if current_length > best_length:
                    best_length = current_length
                    best_start = current_start
            else:
                current_start = None
                current_length = 0

    if best_start is not None:
        return f"{best_start:02d}:00-{best_start + best_length:02d}:00"
    return None
