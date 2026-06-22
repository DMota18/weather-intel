-- Temperatures in Massachusetts should never be below -40°F or above 120°F
-- If any records fall outside this range, the unit conversion is broken
select
    station_id,
    observation_date,
    temp_max_f,
    temp_min_f
from {{ ref('stg_daily_weather') }}
where (temp_max_f is not null and (temp_max_f < -40 or temp_max_f > 120))
   or (temp_min_f is not null and (temp_min_f < -40 or temp_min_f > 120))
