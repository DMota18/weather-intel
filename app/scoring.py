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


# --- Plain-English explanations -------------------------------------------
# The verdict colors say go/no-go; these say WHY, in the words you'd use on
# site. Derived from the same factors the scorers produce, so an explanation
# can never disagree with the verdict it sits under.

_FACTOR_ORDER = ["precipitation", "temperature", "wind", "humidity", "dewpoint", "data"]


def _clock(hour):
    """13 -> '1pm', 0 -> '12am', 7 -> '7am'."""
    suffix = "am" if hour < 12 else "pm"
    h12 = hour % 12 or 12
    return f"{h12}{suffix}"


def _span_phrase(hours, start_hour, end_hour):
    """Describe a set of working hours compactly: 'all day', 'before 9am',
    'after 1pm', '10am-2pm', or '7am, 11am' for scattered hours."""
    if not hours:
        return ""
    hours = sorted(set(hours))
    window = list(range(start_hour, end_hour))
    if len(hours) == len(window):
        return "all day"

    # Contiguous run?
    if hours == list(range(hours[0], hours[-1] + 1)):
        if hours[0] == start_hour:
            return f"before {_clock(hours[-1] + 1)}"
        if hours[-1] == end_hour - 1:
            return f"after {_clock(hours[0])}"
        return f"{_clock(hours[0])}-{_clock(hours[-1] + 1)}"

    if len(hours) <= 3:
        return ", ".join(_clock(h) for h in hours)
    return f"{_clock(hours[0])}-{_clock(hours[-1] + 1)}, on and off"


def explain_pour_day(day_hours, start_hour=7, end_hour=17):
    """Short plain-English reasons a day isn't clear, worst factor first.

    Returns [] for a fully green working window, and a single "no data"
    reason when nothing in the window could be scored.
    """
    window = [h for h in day_hours if start_hour <= h["hour"] < end_hour]
    if not window:
        return ["No forecast data for working hours — treat as no-go"]

    scored = [h for h in window if h.get("pour_score")]
    if not scored:
        return ["No forecast data for working hours — treat as no-go"]

    # Collect per factor, then sort reds ahead of yellows: the first reason
    # has to be the one that actually drove the verdict, since compact views
    # show only reasons[0]. Ties break on factor importance.
    found = []
    for rank, factor in enumerate(_FACTOR_ORDER):
        red = [h for h in window if h.get("pour_factors", {}).get(factor) == "red"]
        yellow = [h for h in window if h.get("pour_factors", {}).get(factor) == "yellow"]
        bad = red or yellow
        if not bad:
            continue

        span = _span_phrase([h["hour"] for h in bad], start_hour, end_hour)
        severity = "red" if red else "yellow"
        phrase = _factor_phrase(factor, bad, span, severity)
        if phrase:
            found.append((0 if red else 1, rank, phrase))

    found.sort(key=lambda x: (x[0], x[1]))
    reasons = [phrase for _, _, phrase in found]

    unscored = len(window) - len(scored)
    if unscored and not any(r.startswith("Missing") for r in reasons):
        reasons.append(f"Missing data for {unscored} working hour(s)")

    return reasons


def _factor_phrase(factor, bad_hours, span, severity):
    """One human sentence for a factor over the hours it misbehaves."""
    if factor == "precipitation":
        probs = [h["precip_prob_pct"] for h in bad_hours if h.get("precip_prob_pct") is not None]
        if not probs:
            return f"Rain risk {span}"
        peak = max(probs)
        verb = "Rain likely" if severity == "red" else "Rain possible"
        return f"{verb} — {peak:.0f}% chance {span}"

    if factor == "temperature":
        temps = [h["temp_f"] for h in bad_hours if h.get("temp_f") is not None]
        if not temps:
            return f"Temperature out of range {span}"
        # Cold and hot read very differently to a finisher
        if min(temps) < 50:
            low = min(temps)
            word = "Too cold" if severity == "red" else "Cold"
            return f"{word} — {low:.0f}°F {span}"
        high = max(temps)
        word = "Too hot" if severity == "red" else "Hot"
        return f"{word} — {high:.0f}°F {span}"

    if factor == "wind":
        winds = [h["wind_mph"] for h in bad_hours if h.get("wind_mph") is not None]
        if not winds:
            return f"Windy {span}"
        peak = max(winds)
        word = "High wind" if severity == "red" else "Breezy"
        return f"{word} — {peak:.0f}mph {span}"

    if factor == "humidity":
        hums = [h["humidity_pct"] for h in bad_hours if h.get("humidity_pct") is not None]
        if not hums:
            return f"Humidity out of range {span}"
        if max(hums) > 70:
            return f"Humid — {max(hums):.0f}% {span}"
        return f"Very dry air — {min(hums):.0f}% {span} (surface may crust)"

    if factor == "dewpoint":
        spreads = [h["temp_f"] - h["dewpoint_f"] for h in bad_hours
                   if h.get("temp_f") is not None and h.get("dewpoint_f") is not None]
        if not spreads:
            return f"Narrow dew point spread {span}"
        return f"Dew point within {min(spreads):.0f}°F of air temp {span} — slow drying"

    if factor == "data":
        return f"Missing forecast data {span}"

    return ""


def explain_sealer(factors, total_precip_24h=None, max_precip_prob=None,
                   min_temp_next_12h=None, current=None):
    """Short plain-English reasons for the sealer verdict, worst first."""
    current = current or {}
    reasons = []

    rain_last = factors.get("rain_last_24h")
    if rain_last == "red":
        reasons.append(f"{total_precip_24h:.2f}\" rain in last 24h — slab needs to dry"
                       if total_precip_24h is not None else "Rain in last 24h — slab needs to dry")
    elif rain_last == "yellow":
        reasons.append(f"Trace rain in last 24h ({total_precip_24h:.2f}\") — check the slab is dry"
                       if total_precip_24h is not None else "Trace rain in last 24h — check the slab")

    rain_next = factors.get("rain_next_24h")
    if rain_next in ("red", "yellow") and max_precip_prob is not None:
        word = "Rain likely" if rain_next == "red" else "Rain possible"
        reasons.append(f"{word} in next 24h — {max_precip_prob:.0f}% chance")

    if factors.get("cure_temp") in ("red", "yellow") and min_temp_next_12h is not None:
        word = "Too cold overnight" if factors["cure_temp"] == "red" else "Cool overnight"
        reasons.append(f"{word} — dropping to {min_temp_next_12h:.0f}°F while it cures")

    if factors.get("temperature") in ("red", "yellow") and current.get("temp_f") is not None:
        t = current["temp_f"]
        word = "Too cold to apply" if factors["temperature"] == "red" else "Cold to apply"
        reasons.append(f"{word} — {t:.0f}°F right now")

    if factors.get("wind") in ("red", "yellow") and current.get("wind_mph") is not None:
        word = "Too windy" if factors["wind"] == "red" else "Breezy"
        reasons.append(f"{word} — {current['wind_mph']:.0f}mph (overspray and debris)")

    if factors.get("humidity") in ("red", "yellow") and current.get("humidity_pct") is not None:
        word = "Too humid" if factors["humidity"] == "red" else "Humid"
        reasons.append(f"{word} — {current['humidity_pct']:.0f}% (slow cure)")

    if factors.get("dewpoint") in ("red", "yellow"):
        if current.get("temp_f") is not None and current.get("dewpoint_f") is not None:
            spread = current["temp_f"] - current["dewpoint_f"]
            reasons.append(f"Dew point within {spread:.0f}°F of air temp — condensation risk")

    if factors.get("data") == "yellow":
        reasons.append("Some readings unavailable — verdict capped at caution")

    return reasons


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
