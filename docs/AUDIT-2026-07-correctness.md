# Correctness & Decision-Trustworthiness Audit — July 2026

Scope: scoring engine, forecast/data parsing, fail-safe behavior, weather-app quality, ops.
Method: full code read of `app/`, `etl/`, `airflow/dags/`, `dbt_project/`, templates, tests;
`pytest tests/test_scoring.py` (28/28 pass); unsafe-default scenarios reproduced by direct
simulation against the real scoring code; template crash reproduced by rendering
`dashboard.html` with a null temperature. `tests/test_api.py` cannot even be collected
without Postgres (see C4). Live Open-Meteo probing was blocked by the sandbox proxy;
API-shape findings (C2) are based on Open-Meteo's documented contract.

Verdict: **RED** — see bottom.

> **Status update (2026-07-16):** All Critical (C1–C4) and High (H1–H5) items
> are fixed on this branch. H1: NWS alerts now render as a dashboard banner
> (fetched server-side per station, 5-min cache) with a broadened filter that
> catches Tornado/Heat warnings, plus a /api/v1/alerts/{town} endpoint; when
> the feed is unreachable the dashboard says so instead of implying all-clear.
> H2: template null-guards. H3: shorter TTLs + a "data as of HH:MM" freshness
> line that turns into a STALE warning on fallback data. H4:
> scripts/cache_forecasts.py now exists (48h scored snapshots into
> weather_forecasts, exit 1 only on total failure). H5: all upstream fetches
> retry with backoff, then fall back to last-known-good data explicitly marked
> stale, then return an honest 503 "treat as NO-GO".
>
> Medium items M1–M8 are also fixed: M1 `is not None` in get_historical (0°F /
> 0.00" preserved); M2 working window unified to 7 ≤ hour < 17 everywhere;
> M3 top-level best_window now carries its date; M4 cure check scores gusts
> (25/35 mph) alongside sustained wind (15/25) with accurate messages; M5
> sealer scoring adds a wind factor (10/15 mph) and the next-12h minimum temp
> (a warm afternoon reading no longer hides a freezing night), both required
> for green; M6 the stream consumer checkpoints its position in Redis instead
> of dropping backlog on restart; M7 pipeline failures push to a phone via
> WI_ALERT_NTFY_TOPIC / WI_ALERT_WEBHOOK_URL (log-only fallback warns loudly);
> M8 historical ETL scores cap at yellow when temp/precip observations are
> missing, and mart_job_weather exposes missing_precip_days. Low items remain
> open.

---

## CRITICAL — wrong greens on real money paths

### C1. Days with no scorable daytime hours are labeled GREEN
`app/main.py:168-174` (API) and `app/main.py:575-576` (dashboard):

```python
scores = [h["pour_score"] for h in day_hours if h["pour_score"] and 7 <= h["hour"] <= 17]
if "red" in scores: ... elif "yellow" in scores: ... else: day_score = "green"
```

If `scores` is empty, the day is green. **Reproduced two ways:**
- The 48h forecast fetched in the evening includes a "today" fragment with only hours
  18–23. Even when every one of those hours is RED (90% rain), today is labeled **green**.
  This fires *every single evening*.
- A day whose hours all scored `None` (missing data) is labeled **green**.

Business impact: the top-of-dashboard "Pour: Go" chip is driven by `today.score`. You can
be told "Go" with literally zero supporting data.

Fix: empty `scores` → `day_score = None`, rendered as a gray "NO DATA" chip; additionally
require a minimum number of scored working hours (e.g. ≥6) before a day can be green.

### C2. "Last 24h" is actually calendar-today — including hours that haven't happened yet
`app/weather_client.py:41-62` requests `start_date=yesterday, end_date=today` from the
Open-Meteo *forecast* endpoint. Per the API contract that returns full calendar days:
yesterday 00:00 → today 23:00 (48 rows), with future hours of today filled with
*forecast* values. Then:

- `app/main.py:232` `recent_hours = history_hours[-24:]` → **today 00:00–23:00**, not the
  last 24 hours. At 7 AM, rain that fell yesterday from 8 AM to midnight is invisible.
  "No rain in last 24h" → sealer green → sealer applied over a slab that got soaked
  yesterday afternoon. This is the exact failure the "dry 24h before" rule exists to prevent.
- `app/main.py:242` / `main.py:556` `current = recent_hours[-1]` → the **23:00 tonight
  forecast row**, not current conditions. The sealer verdict's temp/humidity/dewpoint
  inputs and the dashboard's "current" readings are a forecast for 11 PM.

Fix: fetch with `past_days=1` (or keep start/end dates) and slice by actual timestamps:
`last_24h = [h for h in hours if now-24h <= h.time <= now]`, `current` = latest hour ≤ now.
Parse `h["time"]` into an aware datetime instead of relying on list position.

### C3. Missing data is systematically treated as safe
The engine's contract is "skip unknown factors, grade the rest" — unknown ≠ safe:

- `app/scoring.py:4-56` `score_pour_hour`: an hour with *only* temperature known returns
  **green** (verified; `tests/test_scoring.py:88` asserts this as desired behavior).
  If Open-Meteo returns null precipitation probabilities, rain simply stops being scored.
- `app/scoring.py:114-198` `score_cure_window`: 48 rows of all-null data returns **green**
  (verified). Missing temps → no freeze factor at all; missing precip prob and wind are
  coerced to 0 via `or 0` (scoring.py:146-147, 161, 180) → green.
- Sealer, dashboard path `app/main.py:553-555`: when the history fetch fails (`except: history_hours = []`),
  `total_precip_24h = 0` → `rain_last_24h = green`; `max_precip_prob` defaults to `0` →
  `rain_next_24h = green`. The dashboard shows **"Sealer: Go" when the data source is down.**
  (The API variant `main.py:240` at least uses `None` for empty forecast, but shares the
  `total=0` bug.)

Fix: distinguish "0" from "unknown" end to end. Any missing critical factor (precip, temp)
caps the hour/window at yellow and adds a "missing data" note; a fully-unknown input is
`None`/"no data", never green. Delete the `or 0` coercions on precip/wind aggregation.

### C4. The whole app dies when Postgres *or* Redis is down
- `app/main.py:37` creates the connection pool at import time. Postgres unreachable →
  the process won't start (verified: even `pytest` collection dies on it). Forecast,
  sealer, and cure endpoints don't need Postgres at all.
- `app/main.py:646-648` the startup hook calls `pubsub.subscribe(...)`; Redis down →
  startup exception → app won't boot. The WebSocket feature is decorative; it must not
  be able to take down the pour/seal verdicts.

This fails *closed* (no wrong greens) but means a routine infra hiccup takes the entire
decision tool offline the morning you need it.

Fix: lazy pool creation with retry inside `get_db()`; wrap the Redis subscribe in
try/except with reconnect; log and continue.

---

## HIGH

### H1. NWS severe-weather alerts never reach you
The pipeline exists (producer → Redis stream → consumer → pubsub → `/ws/live`) but
`app/templates/dashboard.html` contains **no WebSocket client and no alert UI** — the only
script is `togglePanel`. Nothing anywhere renders an alert to a human. Additionally the
relevance filter `app/streaming/producer.py:122` (`freeze, frost, wind, thunder, hail,
flood, ice`) drops **Tornado Warnings** and **Excessive Heat Warnings** outright.

Fix: fetch active NWS alerts for the station's zone server-side at dashboard render (one
HTTP call, no Redis dependency) and show a banner; filter on `severity in (Severe, Extreme)`
plus keywords rather than keywords alone.

### H2. Dashboard crashes (HTTP 500) on a single null temperature
`app/templates/dashboard.html:388` `{{ h.temp_f|round(0)|int }}` has no None guard
(verified: `TypeError: NoneType doesn't define __round__`). Same pattern at line 286
(`today.temp_high|round(0)|int`) and line 429/432 are guarded by `or t_min` but the
hourly scroll is not. One missing hourly value from the API and the whole dashboard is a
stack trace instead of a degraded page.

Fix: guard every `round/int` filter (`if h.temp_f is not none else '—'`).

### H3. 3-hour cache TTL serves stale data as "Now"
`app/main.py:51` `FORECAST_CACHE_TTL = timedelta(hours=3)`:
- The header temp labeled "Now" can be 3 hours old; `forecast_hours[0]` silently becomes
  a past hour, shifting `next_24h`, `find_best_window`, and the cure window backwards.
- The `history24` cache means rain that started 2 hours ago can be invisible to the
  sealer check (unsafe direction, compounds C2).
- Cached across midnight, `days[0]` ("today") is yesterday.

Fix: TTL ≤30 min for history/current, ≤1 h for forecast; after cache read, drop hours
whose timestamp < now; display "data as of HH:MM" on the dashboard so staleness is honest.

### H4. The hourly pre-warm DAG calls a script that does not exist
`airflow/dags/hourly_forecast.py:39` runs `scripts/cache_forecasts.py` — there is no such
file in `scripts/`. The DAG fails every hour, the `weather_forecasts` table
(`sql/schema.sql:40`) is never populated, and the app's in-memory cache doesn't read that
table anyway (each uvicorn worker cold-fetches independently). The advertised "instant
dashboard, forecast history tracking" pipeline is fiction.

Fix: implement the script (fetch all 10 stations, upsert into `weather_forecasts`) and
make the app read-through that table, or delete the DAG + table.

### H5. No retries or graceful degradation on the API endpoints
`fetch_forecast_48h`/`fetch_last_24h` are single-shot with a 10 s timeout;
`get_forecast`, `sealer_check`, `cure_check` have no try/except → any Open-Meteo blip is
a raw 500. The dashboard catches the exception but then scores green on empty data (C3).

Fix: 2–3 retries with backoff in `weather_client`; on final failure serve last-known-good
cached data explicitly marked `"stale": true`, else a structured "data unavailable —
treat as NO-GO" response.

---

## MEDIUM

### M1. Zero-truthiness bugs corrupt real readings
- `app/main.py:322-328` (`get_historical`): `float(row["temp_max_f"]) if row["temp_max_f"] else None`
  turns a real **0.0 °F day into null**, and **0.00" precip into null** — a bone-dry day
  becomes indistinguishable from missing data in the API output. MA hits 0 °F.
- `app/main.py:600`: `if current.get("temp_f") and current.get("dewpoint_f")` — dewpoint
  spread hidden at 0 °F (display only; the scorers themselves correctly use `is not None`).
- `dashboard.html:277, 314-316`: `if now.temp_f` / `if sealer_details.current_temp` hide
  real zero readings as "—".

Fix: `is not None` everywhere a value can legitimately be 0.

### M2. Two different definitions of the working day
Day summaries and the pour panel use `7 <= hour <= 17` (11 hours, includes the 5 PM hour);
`find_best_window` (`app/scoring.py:210`) uses `hour < 17` (excludes it). A red 17:00 hour
colors the day but can't appear in the window; the label "07:00-17:00" actually means
hours 7–16. Pick one definition (suggest `7 <= h < 17`, i.e. 7 AM–5 PM) and use it in all
three places.

### M3. Top-level `best_window` has no date
`app/main.py:157` computes the best window across all 48 h and returns "08:00-12:00" with
no indication whether that's today or tomorrow. Attach the date or drop it in favor of the
per-day windows.

### M4. Cure wind check ignores gusts while warning about "gusts"
`app/scoring.py:180-188` scores `wind_mph` (sustained) but the issue text says "Wind gusts
to X mph". `wind_gust_mph` is fetched and never used anywhere. Plastic-shrinkage cracking
is driven by gusts; sustained-only understates risk. Score gusts (with appropriately higher
thresholds) or `max(sustained, gust*0.7)`.

### M5. Sealer model gaps
- Wind is not scored at all — overspray/drift and debris onto wet sealer are real.
- Uses the single "current" hour temp instead of the minimum over the drying window; a
  70 °F 6 PM reading hides a 40 °F night, and solvent/water-based sealers both need temps
  held above threshold for hours.
- `precip_last_24h_in == 0` exact float equality (`app/scoring.py:79`): today it "works"
  only because missing data is coerced to exactly 0 (C3). Once C2/C3 are fixed, use
  `< 0.005` for green and keep any measurable amount ≥0.01" at yellow/red.

### M6. Streaming quietly dies and stays dead
`app/main.py:624-628`: the pubsub listener thread's `for message in pubsub.listen()`
raises on any Redis hiccup and the thread exits permanently — live updates stop with no
log, no restart, until the app is bounced. `consumer.py:70-73` starts at `"$"`, dropping
any backlog on every restart.

### M7. "Failure alerting" alerts no one
`scripts/alert_on_failure.py` writes a JSONL line to a log file. A broken ETL (e.g. H4,
which fails hourly) notifies nobody; you'd keep making calls on silently-aging data. Wire
it to email/SMS/Slack — anything that reaches a phone.

### M8. Historical scores treat missing precip as dry
`etl/02_parse_and_load.py:130` `precip = row.get("precip_in") or 0` → days with missing
PRCP get green precipitation factors in the DB; `dbt_project/models/marts/mart_job_weather.sql:17-18`
`coalesce(precip_in, 0)` repeats the pattern. Affects analytics/seasonal stats, not the
live verdicts. (The GHCN parser itself is solid: -9999, QFLAG, and unit conversions are
all handled correctly.)

---

## LOW

- `app/main.py:179-187`: day warnings report at most **one** issue, only wind/precip
  (never temperature/freeze reds), and scan night hours, so a warning can cite 02:00.
- `app/streaming/producer.py:77-80`: streamed `pour_score` is computed without
  precipitation probability — systematically more optimistic than the dashboard's score.
- `airflow/dags/daily_etl.py:33`: `0 10 * * *` is 6 AM ET only during DST; 5 AM EST in
  winter (harmless direction, wrong comment).
- `tests/test_scoring.py:88` (`test_partial_none_values`) asserts the unsafe
  missing-data-is-green behavior as correct; `score_cure_window` and the day-aggregation
  logic in `main.py` have **zero** test coverage — the two places the worst bugs live.
- `dashboard.html:292-293`: when a score is missing the chip text says "No" but the chip
  color falls back to yellow — mixed signal.

## Things checked and found OK
Timezone handling is correct end to end: Open-Meteo is queried with
`timezone=America/New_York`, `h["hour"]` is parsed from local time strings, no hardcoded
offsets remain. Threshold values themselves (50–90 °F pour, <40 red, 40 °F freeze floor,
wind 10/20, precip prob 15/40) are consistent with ACI 305/306-style field guidance.
GHCN parsing (missing values, quality flags, tenths conversions, leap days) is correct.
The 28 scoring unit tests pass. SQL parameterization is fine.

---

## Verdict: RED

Not safe to bet jobs on today. The scoring math is fine when it's fed complete, current
data — but the system has multiple *verified* paths that manufacture green out of nothing:
every evening "today" shows green regardless of actual conditions (C1), the sealer check
cannot see yesterday afternoon's rain and grades "current" conditions off tonight's 11 PM
forecast (C2), missing or failed data collapses to green across pour, seal, and cure (C3),
and a single null value or infra hiccup takes the dashboard down entirely (C4, H2).
Severe-weather alerts, a headline feature, never reach the screen (H1). The fixes are
mostly small and localized — the fail-safe inversions in C1–C3 plus the last-24h window
in C2 are the must-do set before trusting a single green verdict; H1–H5 are what stand
between "correct" and "as trustworthy as a real weather app."
