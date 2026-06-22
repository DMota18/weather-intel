-- No observation dates should be in the future
select
    station_id,
    observation_date
from {{ ref('stg_daily_weather') }}
where observation_date > current_date + interval '1 day'
