with source as (
    select * from {{ source('raw', 'stations') }}
)

select
    station_id,
    name as station_name,
    covers as coverage_area,
    state,
    latitude,
    longitude,
    elevation_m
from source
