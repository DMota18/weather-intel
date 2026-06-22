with date_range as (
    select generate_series(
        (select min(observation_date) from {{ ref('stg_daily_weather') }}),
        (select max(observation_date) from {{ ref('stg_daily_weather') }}),
        '1 day'::interval
    )::date as expected_date
),

coverage as (
    select
        s.station_id,
        s.station_name,
        s.coverage_area,
        count(distinct dw.observation_date) as days_with_data,
        (select count(*) from date_range) as expected_days,
        round(
            100.0 * count(distinct dw.observation_date) /
            nullif((select count(*) from date_range), 0), 1
        ) as coverage_pct,
        count(*) filter (where dw.temp_max_f is null) as missing_temp,
        count(*) filter (where dw.precip_in is null) as missing_precip,
        count(*) filter (where dw.wind_max_mph is null) as missing_wind,
        min(dw.observation_date) as first_date,
        max(dw.observation_date) as last_date
    from {{ ref('stg_stations') }} s
    left join {{ ref('stg_daily_weather') }} dw on dw.station_id = s.station_id
    group by s.station_id, s.station_name, s.coverage_area
)

select
    *,
    expected_days - days_with_data as gap_days
from coverage
