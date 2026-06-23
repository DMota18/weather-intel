# Weather Intelligence System for Stamped Concrete

![CI](https://github.com/DMota18/weather-intel/actions/workflows/ci.yml/badge.svg)

A full-stack weather intelligence tool that ingests raw NOAA data, scores conditions for concrete pouring and sealer application, and serves live forecasts through a FastAPI application. Built for a stamped concrete business in Massachusetts — used daily for scheduling decisions.

## The Problem

Stamped concrete is weather-sensitive at every stage:
- **Pouring** requires specific temperature (50-90°F), low wind (<10mph), no precipitation, and manageable humidity
- **Sealer application** requires 24 hours of dry conditions before AND after application, plus favorable dew point spread
- **Curing** needs 48 hours without freezing, heavy rain, or extreme heat

No weather app scores these conditions for concrete work. This tool does.

## Architecture

```
┌─────────────────────────────────────────────────┐
│            EC2 Instance ($1.30/mo)              │
│                                                 │
│  FastAPI App (systemd, auto-restart)            │
│    ├── HTML Dashboard (mobile-friendly)         │
│    ├── Forecast / Sealer / Cure-time endpoints  │
│    └── 7 Analytics endpoints                    │
│                                                 │
│  PostgreSQL 16                                  │
│    ├── 18,000+ daily weather observations       │
│    ├── 10 Massachusetts weather stations        │
│    ├── 8 analytical views (2 materialized)      │
│    └── Data: January 2021 → present             │
│                                                 │
│  ETL Pipeline (weekly cron)                     │
│    └── NOAA GHCN .dly → parse → clean → load   │
└─────────────────────────────────────────────────┘
         │                    │
    Open-Meteo API       NOAA GHCN-Daily
    (live forecasts)     (historical, raw)
```

## Data Source: NOAA GHCN-Daily

The historical data comes from NOAA's Global Historical Climatology Network — a notoriously messy public dataset:

- **Fixed-width format** — not CSV. Each line is one station + one month + one element, with 31 value slots packed into positional columns
- **Missing values coded as `-9999`** — not NULL, not empty string
- **Quality flags per value** — each measurement has a flag indicating whether it passed NOAA's quality checks
- **Units in metric fragments** — temperature in tenths of degrees Celsius, precipitation in tenths of millimeters, wind in tenths of meters per second
- **Stations go online/offline** — coverage varies by station and year

The ETL pipeline handles all of this: parsing fixed-width positions, filtering on quality flags, converting units to °F/inches/mph, computing daily aggregates, and scoring each day for concrete viability.

## Schema

```
stations (10 rows)
├── station_id (PK)    -- "USW00094746"
├── name               -- "Worcester Regional"
├── covers             -- "Central MA"
├── latitude, longitude
└── state

daily_weather (18,000+ rows)
├── station_id (FK → stations)
├── observation_date
├── temp_max_f, temp_min_f, temp_mean_f
├── precip_in, snow_in, snow_depth_in
├── wind_avg_mph, wind_max_mph
├── pour_score     -- green / yellow / red
├── sealer_score   -- green / yellow / red
└── score_details  -- JSONB with per-factor breakdown
```

## Analytical SQL Views

Eight views demonstrate advanced PostgreSQL features:

| View | Techniques | Purpose |
|---|---|---|
| `v_temperature_anomalies` | Rolling AVG + STDDEV window functions, CASE | Flag days where temp deviated >2σ from 7-day average |
| `v_weather_streaks` | Gap-and-island (date - ROW_NUMBER), RANK | Find longest consecutive dry/wet streaks |
| `v_seasonal_analysis` | FILTER clause, EXTRACT, percentages | Monthly pour/sealer viability by station and year |
| `v_data_quality` | generate_series, LEFT JOIN, coverage % | Audit data completeness across stations |
| `v_year_over_year` | LAG window function | Same month across years — trend detection |
| `v_best_work_weeks` | 5-day sliding SUM window, RANK | Best work weeks per year (materialized) |
| `v_station_comparison` | Self-join, CORR(), FILTER | Cross-station microclimate differences (materialized) |
| `v_season_boundaries` | ROW_NUMBER + FILTER, date arithmetic | When does concrete season start/end each year? |

### Example: Gap-and-Island Streak Detection

```sql
WITH rain_flag AS (
    SELECT station_id, observation_date, precip_in,
        CASE WHEN COALESCE(precip_in, 0) > 0 THEN 1 ELSE 0 END AS is_rain,
        observation_date - (ROW_NUMBER() OVER (
            PARTITION BY station_id,
                CASE WHEN COALESCE(precip_in, 0) > 0 THEN 1 ELSE 0 END
            ORDER BY observation_date
        ))::int AS streak_group
    FROM daily_weather
)
SELECT MIN(observation_date) AS streak_start,
       MAX(observation_date) AS streak_end,
       COUNT(*) AS streak_days
FROM rain_flag
GROUP BY station_id, streak_group, is_rain
HAVING COUNT(*) >= 5;
```

## API Endpoints

### Core

| Endpoint | Description |
|---|---|
| `GET /` | HTML dashboard (mobile-friendly) |
| `GET /api/v1/forecast/{town}` | 48h hourly forecast with pour scoring |
| `GET /api/v1/sealer-check/{town}` | Last 24h + next 24h sealer safety check |
| `GET /api/v1/cure-check/{town}` | 48h curing window assessment |
| `GET /api/v1/weather/{town}/{date}` | Historical lookup from NOAA data |
| `GET /api/v1/towns` | List available towns |

### Analytics

| Endpoint | Description |
|---|---|
| `GET /api/v1/analytics/seasonal?town=&year=` | Monthly viability breakdown |
| `GET /api/v1/analytics/streaks?town=&streak_type=DRY` | Longest dry/wet streaks |
| `GET /api/v1/analytics/anomalies?town=` | Temperature anomaly days |
| `GET /api/v1/analytics/quality` | Data completeness audit |
| `GET /api/v1/analytics/season-boundaries?town=` | Season start/end per year |
| `GET /api/v1/analytics/year-over-year?town=` | Year-over-year trends |
| `GET /api/v1/analytics/best-weeks?town=&year=` | Best 5-day work windows |
| `GET /api/v1/analytics/station-comparison` | Cross-station correlation |

### Scoring Thresholds

**Pour score** (hourly):

| Factor | Green | Yellow | Red |
|---|---|---|---|
| Temperature | 50-90°F | 40-50 or 90-95°F | <40 or >95°F |
| Humidity | 25-70% | 15-25 or 70-85% | <15 or >85% |
| Wind | <10 mph | 10-20 mph | >20 mph |
| Precip probability | <15% | 15-40% | >40% |
| Dew point spread | >10°F | 5-10°F | <5°F |

**Sealer score**: No rain in previous 24h, <10% rain chance next 24h, temp 50-90°F, humidity <70%.

**Cure score**: No freezing (<40°F) in 48h window, <40% rain chance in first 24h, no extreme heat (>95°F), wind <25 mph.

## Station Coverage

| Station | Area |
|---|---|
| Hyannis/Barnstable | Cape Cod |
| Plymouth | South Shore |
| Taunton | SE MA / Brockton |
| New Bedford | South Coast |
| Norwood | Metro South / Norfolk |
| Worcester | Central MA |
| Fitchburg | North Central MA |
| Lawrence/Lowell | Merrimack Valley |
| Springfield/Chicopee | Springfield area |
| Westfield | Western MA |

## Setup

```bash
# Clone and install
git clone https://github.com/YOUR_USER/weather-intel.git
cd weather-intel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables (or use defaults for local dev)
export WI_DB_NAME=weather_intel
export WI_DB_USER=weather
export WI_DB_PASSWORD=your_password
export WI_DB_HOST=localhost

# Create database and schema
sudo -u postgres psql -f sql/schema.sql

# Download and load NOAA data
cd etl
python 01_download_stations.py
python 02_parse_and_load.py

# Create analytical views
cat ../sql/portfolio_queries.sql | sudo -u postgres psql -d weather_intel

# Run the app
cd ../app
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Tests

```bash
pytest tests/ -v    # 28 tests covering scoring engine
```

## Tech Stack

- **Data source**: NOAA GHCN-Daily (historical), Open-Meteo (forecasts)
- **Database**: PostgreSQL 16
- **API**: FastAPI + uvicorn
- **ETL**: Python with psycopg2
- **Deployment**: AWS EC2, systemd service
- **Cost**: $1.30/month (EBS disk expansion only)
