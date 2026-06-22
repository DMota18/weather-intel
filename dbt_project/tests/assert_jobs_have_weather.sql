-- Every job should have at least one matching weather record
select
    j.job_id,
    j.start_date,
    j.station_id
from {{ ref('stg_jobs') }} j
left join {{ ref('stg_daily_weather') }} dw
    on dw.station_id = j.station_id
    and dw.observation_date = j.start_date
where dw.id is null
