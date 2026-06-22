with source as (
    select * from {{ source('raw', 'jobs') }}
)

select
    job_id,
    start_date,
    completion_date,
    completion_date - start_date as job_duration_days,
    final_revenue,
    lead_name,
    address,
    job_type,
    concrete_type,
    lead_status,
    square_footage,
    concrete_company,
    sealer_coats,
    admixture_type,
    station_id,
    case
        when square_footage > 0
            then round(final_revenue / square_footage, 2)
        else null
    end as revenue_per_sqft
from source
where start_date is not null
