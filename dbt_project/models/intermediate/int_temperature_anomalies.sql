with daily as (
    select
        dw.station_id,
        s.station_name,
        dw.observation_date,
        dw.temp_mean_f,
        dw.precip_in,
        avg(dw.temp_mean_f) over (
            partition by dw.station_id
            order by dw.observation_date
            rows between 6 preceding and current row
        ) as temp_7d_avg,
        stddev(dw.temp_mean_f) over (
            partition by dw.station_id
            order by dw.observation_date
            rows between 29 preceding and current row
        ) as temp_30d_stddev
    from {{ ref('stg_daily_weather') }} dw
    join {{ ref('stg_stations') }} s on s.station_id = dw.station_id
    where dw.temp_mean_f is not null
)

select
    station_id,
    station_name,
    observation_date,
    temp_mean_f,
    round(temp_7d_avg::numeric, 1) as temp_7d_avg,
    round((temp_mean_f - temp_7d_avg)::numeric, 1) as temp_anomaly,
    round(temp_30d_stddev::numeric, 1) as temp_30d_stddev,
    case
        when abs(temp_mean_f - temp_7d_avg) > 2 * coalesce(temp_30d_stddev, 10)
            then 'EXTREME'
        when abs(temp_mean_f - temp_7d_avg) > coalesce(temp_30d_stddev, 10)
            then 'MODERATE'
        else 'NORMAL'
    end as anomaly_flag
from daily
