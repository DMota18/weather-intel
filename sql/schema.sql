-- Weather Intelligence Database Schema
-- PostgreSQL 16

-- Stations table (NOAA GHCN stations)
CREATE TABLE IF NOT EXISTS stations (
    station_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    covers          TEXT,
    state           TEXT,
    latitude        DECIMAL(7,4) NOT NULL,
    longitude       DECIMAL(7,4) NOT NULL,
    elevation_m     DECIMAL(6,1)
);

-- Daily weather observations (cleaned from GHCN .dly files)
CREATE TABLE IF NOT EXISTS daily_weather (
    id                  SERIAL PRIMARY KEY,
    station_id          TEXT NOT NULL REFERENCES stations(station_id),
    observation_date    DATE NOT NULL,
    temp_max_f          DECIMAL(5,1),
    temp_min_f          DECIMAL(5,1),
    temp_mean_f         DECIMAL(5,1),
    precip_in           DECIMAL(5,2),
    snow_in             DECIMAL(5,1),
    snow_depth_in       DECIMAL(5,1),
    wind_avg_mph        DECIMAL(5,1),
    wind_max_mph        DECIMAL(5,1),
    pour_score          TEXT CHECK (pour_score IN ('green', 'yellow', 'red')),
    sealer_score        TEXT CHECK (sealer_score IN ('green', 'yellow', 'red')),
    score_details       JSONB,
    UNIQUE (station_id, observation_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_weather_date ON daily_weather (observation_date);
CREATE INDEX IF NOT EXISTS idx_daily_weather_station_date ON daily_weather (station_id, observation_date);
CREATE INDEX IF NOT EXISTS idx_daily_weather_pour ON daily_weather (pour_score, observation_date);
CREATE INDEX IF NOT EXISTS idx_daily_weather_sealer ON daily_weather (sealer_score, observation_date);

-- Forecast cache (from Open-Meteo)
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id                  SERIAL PRIMARY KEY,
    station_id          TEXT NOT NULL REFERENCES stations(station_id),
    forecast_hour       TIMESTAMPTZ NOT NULL,
    temp_f              DECIMAL(5,1),
    humidity_pct        DECIMAL(4,1),
    wind_mph            DECIMAL(5,1),
    wind_gust_mph       DECIMAL(5,1),
    precip_prob_pct     DECIMAL(4,1),
    precip_amount_in    DECIMAL(5,2),
    dewpoint_f          DECIMAL(5,1),
    cloud_cover_pct     DECIMAL(4,1),
    pour_score          TEXT CHECK (pour_score IN ('green', 'yellow', 'red')),
    sealer_score        TEXT CHECK (sealer_score IN ('green', 'yellow', 'red')),
    score_factors       JSONB,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (station_id, forecast_hour, fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_weather_fcst_lookup ON weather_forecasts (station_id, forecast_hour);
CREATE INDEX IF NOT EXISTS idx_weather_fcst_expires ON weather_forecasts (expires_at);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    job_id          INTEGER PRIMARY KEY,
    start_date      DATE,
    completion_date DATE,
    final_revenue   NUMERIC(10,2),
    month           TEXT,
    lead_name       TEXT,
    address         TEXT,
    job_type        TEXT,
    concrete_type   TEXT,
    lead_status     TEXT,
    square_footage  INTEGER,
    concrete_company TEXT,
    sealer_coats    INTEGER,
    admixture_type  TEXT,
    station_id      TEXT REFERENCES stations(station_id)
);
