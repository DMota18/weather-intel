-- ============================================================
-- WEATHER INTELLIGENCE — PORTFOLIO SQL QUERIES
-- Demonstrates: CTEs, window functions, generate_series,
--   FILTER clauses, JSONB, multi-table joins, date math
-- ============================================================


-- ============================================================
-- 1. ROLLING 7-DAY AVERAGES WITH ANOMALY DETECTION
--    Window function over ordered date series
-- ============================================================
CREATE OR REPLACE VIEW v_temperature_anomalies AS
WITH daily AS (
    SELECT
        dw.station_id,
        s.name AS station_name,
        dw.observation_date,
        dw.temp_mean_f,
        dw.precip_in,
        AVG(dw.temp_mean_f) OVER (
            PARTITION BY dw.station_id
            ORDER BY dw.observation_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS temp_7d_avg,
        STDDEV(dw.temp_mean_f) OVER (
            PARTITION BY dw.station_id
            ORDER BY dw.observation_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS temp_30d_stddev
    FROM daily_weather dw
    JOIN stations s ON s.station_id = dw.station_id
    WHERE dw.temp_mean_f IS NOT NULL
)
SELECT
    station_id,
    station_name,
    observation_date,
    temp_mean_f,
    ROUND(temp_7d_avg::numeric, 1) AS temp_7d_avg,
    ROUND((temp_mean_f - temp_7d_avg)::numeric, 1) AS temp_anomaly,
    ROUND(temp_30d_stddev::numeric, 1) AS temp_30d_stddev,
    CASE
        WHEN ABS(temp_mean_f - temp_7d_avg) > 2 * COALESCE(temp_30d_stddev, 10)
            THEN 'EXTREME'
        WHEN ABS(temp_mean_f - temp_7d_avg) > temp_30d_stddev
            THEN 'MODERATE'
        ELSE 'NORMAL'
    END AS anomaly_flag
FROM daily;


-- ============================================================
-- 2. CONSECUTIVE DRY/WET DAY STREAKS
--    Gap-and-island technique with window functions
-- ============================================================
CREATE OR REPLACE VIEW v_weather_streaks AS
WITH rain_flag AS (
    SELECT
        station_id,
        observation_date,
        precip_in,
        CASE WHEN COALESCE(precip_in, 0) > 0 THEN 1 ELSE 0 END AS is_rain,
        observation_date - (ROW_NUMBER() OVER (
            PARTITION BY station_id, CASE WHEN COALESCE(precip_in, 0) > 0 THEN 1 ELSE 0 END
            ORDER BY observation_date
        ))::int AS streak_group
    FROM daily_weather
),
streaks AS (
    SELECT
        station_id,
        is_rain,
        MIN(observation_date) AS streak_start,
        MAX(observation_date) AS streak_end,
        COUNT(*) AS streak_days,
        ROUND(SUM(COALESCE(precip_in, 0))::numeric, 2) AS total_precip_in
    FROM rain_flag
    GROUP BY station_id, streak_group, is_rain
)
SELECT
    str.station_id,
    s.name AS station_name,
    CASE WHEN str.is_rain = 0 THEN 'DRY' ELSE 'WET' END AS streak_type,
    str.streak_start,
    str.streak_end,
    str.streak_days,
    str.total_precip_in,
    RANK() OVER (
        PARTITION BY str.station_id, str.is_rain
        ORDER BY str.streak_days DESC
    ) AS streak_rank
FROM streaks str
JOIN stations s ON s.station_id = str.station_id
WHERE str.streak_days >= 3;


-- ============================================================
-- 3. SEASONAL POUR/SEALER VIABILITY ANALYSIS
--    Monthly aggregates with FILTER and percentage calculations
-- ============================================================
CREATE OR REPLACE VIEW v_seasonal_analysis AS
SELECT
    s.name AS station_name,
    s.covers,
    EXTRACT(YEAR FROM dw.observation_date) AS year,
    EXTRACT(MONTH FROM dw.observation_date) AS month_num,
    TO_CHAR(dw.observation_date, 'Mon') AS month_name,
    COUNT(*) AS total_days,
    COUNT(*) FILTER (WHERE dw.pour_score = 'green') AS pour_green,
    COUNT(*) FILTER (WHERE dw.pour_score = 'yellow') AS pour_yellow,
    COUNT(*) FILTER (WHERE dw.pour_score = 'red') AS pour_red,
    ROUND(100.0 * COUNT(*) FILTER (WHERE dw.pour_score = 'green') / NULLIF(COUNT(*), 0), 1) AS pct_pour_green,
    COUNT(*) FILTER (WHERE dw.sealer_score = 'green') AS sealer_green,
    ROUND(100.0 * COUNT(*) FILTER (WHERE dw.sealer_score = 'green') / NULLIF(COUNT(*), 0), 1) AS pct_sealer_green,
    ROUND(AVG(dw.temp_max_f)::numeric, 1) AS avg_high,
    ROUND(AVG(dw.temp_min_f)::numeric, 1) AS avg_low,
    ROUND(SUM(COALESCE(dw.precip_in, 0))::numeric, 1) AS total_precip_in,
    COUNT(*) FILTER (WHERE COALESCE(dw.precip_in, 0) > 0) AS rainy_days
FROM daily_weather dw
JOIN stations s ON s.station_id = dw.station_id
GROUP BY s.name, s.covers, EXTRACT(YEAR FROM dw.observation_date),
         EXTRACT(MONTH FROM dw.observation_date), TO_CHAR(dw.observation_date, 'Mon')
ORDER BY s.name, year, month_num;


-- ============================================================
-- 4. DATA QUALITY / COVERAGE AUDIT
--    generate_series to find gaps, coverage percentages
-- ============================================================
CREATE OR REPLACE VIEW v_data_quality AS
WITH date_range AS (
    SELECT generate_series(
        (SELECT MIN(observation_date) FROM daily_weather),
        (SELECT MAX(observation_date) FROM daily_weather),
        '1 day'::interval
    )::date AS expected_date
),
coverage AS (
    SELECT
        s.station_id,
        s.name AS station_name,
        s.covers,
        COUNT(DISTINCT dw.observation_date) AS days_with_data,
        (SELECT COUNT(*) FROM date_range) AS expected_days,
        ROUND(
            100.0 * COUNT(DISTINCT dw.observation_date) /
            NULLIF((SELECT COUNT(*) FROM date_range), 0), 1
        ) AS coverage_pct,
        COUNT(*) FILTER (WHERE dw.temp_max_f IS NULL) AS missing_temp,
        COUNT(*) FILTER (WHERE dw.precip_in IS NULL) AS missing_precip,
        COUNT(*) FILTER (WHERE dw.wind_max_mph IS NULL) AS missing_wind,
        MIN(dw.observation_date) AS first_date,
        MAX(dw.observation_date) AS last_date
    FROM stations s
    LEFT JOIN daily_weather dw ON dw.station_id = s.station_id
    GROUP BY s.station_id, s.name, s.covers
)
SELECT
    station_id,
    station_name,
    covers,
    days_with_data,
    expected_days,
    coverage_pct,
    missing_temp,
    missing_precip,
    missing_wind,
    first_date,
    last_date,
    expected_days - days_with_data AS gap_days
FROM coverage
ORDER BY coverage_pct ASC;


-- ============================================================
-- 5. MONTH-OVER-MONTH COMPARISON (SAME MONTH, DIFFERENT YEARS)
--    Self-join + window for year-over-year trends
-- ============================================================
CREATE OR REPLACE VIEW v_year_over_year AS
WITH monthly AS (
    SELECT
        station_id,
        EXTRACT(YEAR FROM observation_date) AS year,
        EXTRACT(MONTH FROM observation_date) AS month,
        ROUND(AVG(temp_mean_f)::numeric, 1) AS avg_temp,
        ROUND(SUM(COALESCE(precip_in, 0))::numeric, 2) AS total_precip,
        COUNT(*) FILTER (WHERE pour_score = 'green') AS green_days,
        COUNT(*) AS total_days
    FROM daily_weather
    WHERE temp_mean_f IS NOT NULL
    GROUP BY station_id, EXTRACT(YEAR FROM observation_date), EXTRACT(MONTH FROM observation_date)
)
SELECT
    m.station_id,
    s.name AS station_name,
    m.year,
    m.month,
    TO_CHAR(TO_DATE(m.month::text, 'MM'), 'Mon') AS month_name,
    m.avg_temp,
    m.total_precip,
    m.green_days,
    m.total_days,
    LAG(m.avg_temp) OVER (PARTITION BY m.station_id, m.month ORDER BY m.year) AS prev_year_avg_temp,
    m.avg_temp - LAG(m.avg_temp) OVER (PARTITION BY m.station_id, m.month ORDER BY m.year) AS temp_change_yoy,
    LAG(m.green_days) OVER (PARTITION BY m.station_id, m.month ORDER BY m.year) AS prev_year_green_days
FROM monthly m
JOIN stations s ON s.station_id = m.station_id
ORDER BY m.station_id, m.month, m.year;


-- ============================================================
-- 6. BEST WORK WEEKS — RANKED BY CONSECUTIVE GREEN DAYS
--    Sliding window + ranking
-- ============================================================
CREATE OR REPLACE VIEW v_best_work_weeks AS
WITH scored_days AS (
    SELECT
        station_id,
        observation_date,
        pour_score,
        temp_max_f,
        precip_in,
        CASE WHEN pour_score = 'green' THEN 1 ELSE 0 END AS is_green,
        SUM(CASE WHEN pour_score = 'green' THEN 1 ELSE 0 END) OVER (
            PARTITION BY station_id
            ORDER BY observation_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS green_in_5day,
        SUM(CASE WHEN pour_score = 'red' THEN 1 ELSE 0 END) OVER (
            PARTITION BY station_id
            ORDER BY observation_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS red_in_5day,
        ROUND(AVG(temp_max_f) OVER (
            PARTITION BY station_id
            ORDER BY observation_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        )::numeric, 1) AS avg_high_5day
    FROM daily_weather
    WHERE pour_score IS NOT NULL
),
weeks AS (
    SELECT
        station_id,
        observation_date AS week_ending,
        observation_date - 4 AS week_starting,
        green_in_5day,
        red_in_5day,
        avg_high_5day,
        EXTRACT(MONTH FROM observation_date) AS month
    FROM scored_days
    WHERE green_in_5day >= 3
)
SELECT
    w.station_id,
    s.name AS station_name,
    w.week_starting,
    w.week_ending,
    w.green_in_5day,
    w.red_in_5day,
    w.avg_high_5day,
    RANK() OVER (
        PARTITION BY w.station_id, EXTRACT(YEAR FROM w.week_ending)
        ORDER BY w.green_in_5day DESC, w.red_in_5day ASC
    ) AS year_rank
FROM weeks w
JOIN stations s ON s.station_id = w.station_id;


-- ============================================================
-- 7. STATION-TO-STATION WEATHER CORRELATION
--    Cross-join comparison showing microclimate differences
-- ============================================================
CREATE OR REPLACE VIEW v_station_comparison AS
WITH station_pairs AS (
    SELECT
        a.station_id AS station_a,
        b.station_id AS station_b,
        a.observation_date,
        a.temp_max_f AS temp_a,
        b.temp_max_f AS temp_b,
        a.precip_in AS precip_a,
        b.precip_in AS precip_b,
        a.pour_score AS score_a,
        b.pour_score AS score_b
    FROM daily_weather a
    JOIN daily_weather b
        ON a.observation_date = b.observation_date
        AND a.station_id < b.station_id
    WHERE a.temp_max_f IS NOT NULL AND b.temp_max_f IS NOT NULL
)
SELECT
    sa.name AS station_a_name,
    sb.name AS station_b_name,
    COUNT(*) AS compared_days,
    ROUND(AVG(ABS(sp.temp_a - sp.temp_b))::numeric, 1) AS avg_temp_diff_f,
    MAX(ABS(sp.temp_a - sp.temp_b))::numeric AS max_temp_diff_f,
    COUNT(*) FILTER (WHERE sp.score_a != sp.score_b) AS score_disagree_days,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE sp.score_a != sp.score_b) / NULLIF(COUNT(*), 0), 1
    ) AS pct_disagree,
    ROUND(CORR(sp.temp_a, sp.temp_b)::numeric, 3) AS temp_correlation
FROM station_pairs sp
JOIN stations sa ON sa.station_id = sp.station_a
JOIN stations sb ON sb.station_id = sp.station_b
GROUP BY sa.name, sb.name
ORDER BY pct_disagree DESC;


-- ============================================================
-- 8. CONCRETE SEASON BOUNDARIES
--    First/last viable pour date per year per station
-- ============================================================
CREATE OR REPLACE VIEW v_season_boundaries AS
WITH green_days AS (
    SELECT
        station_id,
        EXTRACT(YEAR FROM observation_date) AS year,
        observation_date,
        pour_score,
        ROW_NUMBER() OVER (
            PARTITION BY station_id, EXTRACT(YEAR FROM observation_date)
            ORDER BY observation_date
        ) AS first_rank,
        ROW_NUMBER() OVER (
            PARTITION BY station_id, EXTRACT(YEAR FROM observation_date)
            ORDER BY observation_date DESC
        ) AS last_rank
    FROM daily_weather
    WHERE pour_score IN ('green', 'yellow')
      AND EXTRACT(DOY FROM observation_date) BETWEEN 60 AND 340
)
SELECT
    gd.station_id,
    s.name AS station_name,
    gd.year,
    MIN(gd.observation_date) FILTER (WHERE first_rank <= 5) AS season_start_approx,
    MAX(gd.observation_date) FILTER (WHERE last_rank <= 5) AS season_end_approx,
    MAX(gd.observation_date) FILTER (WHERE last_rank <= 5) -
        MIN(gd.observation_date) FILTER (WHERE first_rank <= 5) AS season_length_days,
    COUNT(*) FILTER (WHERE pour_score = 'green') AS total_green_days,
    COUNT(*) FILTER (WHERE pour_score = 'yellow') AS total_yellow_days
FROM green_days gd
JOIN stations s ON s.station_id = gd.station_id
GROUP BY gd.station_id, s.name, gd.year
ORDER BY gd.station_id, gd.year;
