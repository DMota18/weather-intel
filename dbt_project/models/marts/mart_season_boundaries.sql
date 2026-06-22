with viable_days as (
    select
        dw.station_id,
        s.station_name,
        extract(year from dw.observation_date) as year,
        dw.observation_date,
        dw.pour_score,
        row_number() over (
            partition by dw.station_id, extract(year from dw.observation_date)
            order by dw.observation_date
        ) as first_rank,
        row_number() over (
            partition by dw.station_id, extract(year from dw.observation_date)
            order by dw.observation_date desc
        ) as last_rank
    from {{ ref('stg_daily_weather') }} dw
    join {{ ref('stg_stations') }} s on s.station_id = dw.station_id
    where dw.pour_score in ('green', 'yellow')
      and extract(doy from dw.observation_date) between 60 and 340
)

select
    station_id,
    station_name,
    year,
    min(observation_date) filter (where first_rank <= 5) as season_start_approx,
    max(observation_date) filter (where last_rank <= 5) as season_end_approx,
    max(observation_date) filter (where last_rank <= 5) -
        min(observation_date) filter (where first_rank <= 5) as season_length_days,
    count(*) filter (where pour_score = 'green') as total_green_days,
    count(*) filter (where pour_score = 'yellow') as total_yellow_days
from viable_days
group by station_id, station_name, year
