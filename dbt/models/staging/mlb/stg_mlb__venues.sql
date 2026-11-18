-- One row per venue per season: where a park is, which way it faces, and its posted
-- (painted-on-the-wall) dimensions. Measured distances and wall heights come from Savant
-- (stg_savant__park_dimensions).

with source as (

    select * from {{ source('mlb', 'venues_raw') }}

)

select
    -- keys
    id                                          as venue_id,
    cast(season as integer)                     as season,

    name                                        as venue_name,
    active                                      as is_active,

    -- location
    location.city                               as city,
    location.stateAbbrev                        as state,
    location.country                            as country,
    location.defaultCoordinates.latitude        as latitude,
    location.defaultCoordinates.longitude       as longitude,
    location.elevation                          as elevation_ft,
    -- Compass direction from home plate toward center field (0 = north, 90 = east).
    location.azimuthAngle                       as azimuth_deg,
    timeZone.id                                 as time_zone,

    -- field
    fieldInfo.roofType                          as roof_type,       -- Open, Retractable, Dome
    fieldInfo.turfType                          as turf_type,       -- Grass, Artificial Turf
    fieldInfo.capacity                          as capacity,

    -- Posted distances in feet. These are wall signs mapped into fixed slots, and the slots
    -- don't always line up (Fenway's 420 sign is listed as center). Use Savant's measured
    -- distances for modeling.
    fieldInfo.leftLine                          as posted_left_line_ft,
    fieldInfo.{{ adapter.quote('left') }}       as posted_left_ft,
    fieldInfo.leftCenter                        as posted_left_center_ft,
    fieldInfo.center                            as posted_center_ft,
    fieldInfo.rightCenter                       as posted_right_center_ft,
    fieldInfo.{{ adapter.quote('right') }}      as posted_right_ft,
    fieldInfo.rightLine                         as posted_right_line_ft,

    -- lineage
    filename                                    as _source_file,
    _ingested_at

from source
