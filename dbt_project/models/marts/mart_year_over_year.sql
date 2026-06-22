with monthly as (
    select
        station_id,
        extract(year from observation_date) as year,
        extract(month from observation_date) as month,
        round(avg(temp_mean_f)::numeric, 1) as avg_temp,
        round(sum(coalesce(precip_in, 0))::numeric, 2) as total_precip,
        count(*) filter (where pour_score = 'green') as green_days,
        count(*) as total_days
    from {{ ref('stg_daily_weather') }}
    where temp_mean_f is not null
    group by station_id, extract(year from observation_date), extract(month from observation_date)
)

select
    m.station_id,
    s.station_name,
    m.year,
    m.month,
    to_char(to_date(m.month::text, 'MM'), 'Mon') as month_name,
    m.avg_temp,
    m.total_precip,
    m.green_days,
    m.total_days,
    lag(m.avg_temp) over (partition by m.station_id, m.month order by m.year) as prev_year_avg_temp,
    m.avg_temp - lag(m.avg_temp) over (partition by m.station_id, m.month order by m.year) as temp_change_yoy,
    lag(m.green_days) over (partition by m.station_id, m.month order by m.year) as prev_year_green_days
from monthly m
join {{ ref('stg_stations') }} s on s.station_id = m.station_id
