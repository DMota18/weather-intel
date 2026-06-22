select
    j.job_id,
    j.lead_name,
    j.address,
    j.job_type,
    j.concrete_type,
    j.start_date,
    j.completion_date,
    j.job_duration_days,
    j.final_revenue,
    j.square_footage,
    j.revenue_per_sqft,
    j.sealer_coats,
    s.station_name,
    round(avg(dw.temp_max_f)::numeric, 1) as avg_high,
    round(avg(dw.temp_min_f)::numeric, 1) as avg_low,
    round(sum(coalesce(dw.precip_in, 0))::numeric, 2) as total_precip_in,
    count(*) filter (where coalesce(dw.precip_in, 0) > 0) as rainy_days,
    count(*) filter (where dw.pour_score = 'green') as green_days,
    count(*) filter (where dw.pour_score = 'yellow') as yellow_days,
    count(*) filter (where dw.pour_score = 'red') as red_days,
    round(max(dw.wind_max_mph)::numeric, 1) as max_wind_mph,
    max(dw.temp_max_f) filter (where dw.observation_date = j.start_date) as pour_day_high,
    max(dw.precip_in) filter (where dw.observation_date = j.start_date) as pour_day_precip,
    max(dw.pour_score) filter (where dw.observation_date = j.start_date) as pour_day_score
from {{ ref('stg_jobs') }} j
join {{ ref('stg_stations') }} s on s.station_id = j.station_id
join {{ ref('stg_daily_weather') }} dw on dw.station_id = j.station_id
    and dw.observation_date between j.start_date and j.completion_date
group by j.job_id, j.lead_name, j.address, j.job_type, j.concrete_type,
         j.start_date, j.completion_date, j.job_duration_days, j.final_revenue,
         j.square_footage, j.revenue_per_sqft, j.sealer_coats, s.station_name
