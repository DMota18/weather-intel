with source as (
    select * from {{ source('raw', 'daily_weather') }}
)

select
    id,
    station_id,
    observation_date,
    temp_max_f,
    temp_min_f,
    temp_mean_f,
    precip_in,
    snow_in,
    snow_depth_in,
    wind_avg_mph,
    wind_max_mph,
    pour_score,
    sealer_score,
    score_details,
    case
        when temp_max_f is null and temp_min_f is null and precip_in is null
            then true
        else false
    end as is_incomplete_record
from source
where observation_date is not null
