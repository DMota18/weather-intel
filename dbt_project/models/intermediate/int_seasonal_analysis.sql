select
    s.station_name,
    s.coverage_area,
    s.station_id,
    extract(year from dw.observation_date) as year,
    extract(month from dw.observation_date) as month_num,
    to_char(dw.observation_date, 'Mon') as month_name,
    count(*) as total_days,
    count(*) filter (where dw.pour_score = 'green') as pour_green,
    count(*) filter (where dw.pour_score = 'yellow') as pour_yellow,
    count(*) filter (where dw.pour_score = 'red') as pour_red,
    round(100.0 * count(*) filter (where dw.pour_score = 'green') / nullif(count(*), 0), 1) as pct_pour_green,
    count(*) filter (where dw.sealer_score = 'green') as sealer_green,
    round(100.0 * count(*) filter (where dw.sealer_score = 'green') / nullif(count(*), 0), 1) as pct_sealer_green,
    round(avg(dw.temp_max_f)::numeric, 1) as avg_high,
    round(avg(dw.temp_min_f)::numeric, 1) as avg_low,
    round(sum(coalesce(dw.precip_in, 0))::numeric, 1) as total_precip_in,
    count(*) filter (where coalesce(dw.precip_in, 0) > 0) as rainy_days
from {{ ref('stg_daily_weather') }} dw
join {{ ref('stg_stations') }} s on s.station_id = dw.station_id
group by s.station_name, s.coverage_area, s.station_id,
         extract(year from dw.observation_date),
         extract(month from dw.observation_date),
         to_char(dw.observation_date, 'Mon')
