-- One row per MLB home park per season: Savant's measured fence distances and wall heights.
-- Join to games on (venue_id, season). Neutral sites have no row here.

with source as (

    select * from {{ source('savant', 'park_dimensions_raw') }}

)

select
    -- keys
    venue_id,
    season_id                                   as season,
    team_id                                     as home_team_id,
    venue_name_short                            as venue_name,  -- current name, even for past seasons

    -- 1 when the park's walls changed from the previous season (e.g. Camden Yards 2025).
    -- The *_diff fields hold the size of the change; dropped here because lag() over
    -- season gives the same answer from this table.
    is_diff_configuration = 1                   as walls_changed,

    -- measured fence distance from home plate, feet
    distance_lf_line                            as distance_lf_line_ft,
    distance_lf_gap                             as distance_lf_gap_ft,
    distance_cf                                 as distance_cf_ft,
    distance_rf_gap                             as distance_rf_gap_ft,
    distance_rf_line                            as distance_rf_line_ft,
    distance_deepest                            as distance_deepest_ft,
    avg_fence_distance                          as avg_fence_distance_ft,

    -- wall height, feet
    height_lf_line                              as height_lf_line_ft,
    height_lf_gap                               as height_lf_gap_ft,
    height_cf                                   as height_cf_ft,
    height_rf_gap                               as height_rf_gap_ft,
    height_rf_line                              as height_rf_line_ft,
    height_highest                              as height_highest_ft,
    avg_fence_height                            as avg_fence_height_ft,

    -- fair territory area, square feet
    fence_area                                  as fair_area_sqft,

    -- outcome: average distance of home runs hit in this park this season.
    -- Built from the same season's batted balls, so it leaks; use prior seasons only.
    avg_hr_distance                             as avg_hr_distance_ft,

    -- lineage
    filename                                    as _source_file,
    _ingested_at

from source
