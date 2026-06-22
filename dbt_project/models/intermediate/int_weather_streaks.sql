with rain_flag as (
    select
        station_id,
        observation_date,
        precip_in,
        case when coalesce(precip_in, 0) > 0 then 1 else 0 end as is_rain,
        observation_date - (row_number() over (
            partition by station_id, case when coalesce(precip_in, 0) > 0 then 1 else 0 end
            order by observation_date
        ))::int as streak_group
    from {{ ref('stg_daily_weather') }}
),

streaks as (
    select
        station_id,
        is_rain,
        min(observation_date) as streak_start,
        max(observation_date) as streak_end,
        count(*) as streak_days,
        round(sum(coalesce(precip_in, 0))::numeric, 2) as total_precip_in
    from rain_flag
    group by station_id, streak_group, is_rain
)

select
    str.station_id,
    s.station_name,
    case when str.is_rain = 0 then 'DRY' else 'WET' end as streak_type,
    str.streak_start,
    str.streak_end,
    str.streak_days,
    str.total_precip_in,
    rank() over (
        partition by str.station_id, str.is_rain
        order by str.streak_days desc
    ) as streak_rank
from streaks str
join {{ ref('stg_stations') }} s on s.station_id = str.station_id
where str.streak_days >= 3
