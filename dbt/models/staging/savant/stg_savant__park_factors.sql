-- One row per park per season per rolling window (1 or 3 seasons) per batter side.
-- Indexes: 100 = league average; 125 = 25% more of that stat than an average park.
--
-- These are computed from the season's own batted balls (the 3-season window ending in
-- `season`), so they describe the past. dim_venue_seasons shifts them to the next season
-- for modeling; don't join this table to pitches on the same season.

with source as (

    select * from {{ source('savant', 'park_factors_raw') }}

)

select
    -- keys
    cast(venue_id as integer)                   as venue_id,
    cast(key_year as integer)                   as season,
    cast(key_num_years_rolling as integer)      as rolling_years,   -- 1 or 3
    key_bat_side                                as bat_side,        -- All, L, R

    venue_name,
    cast(main_team_id as integer)               as home_team_id,
    -- seasons in the window, e.g. '2023-2025' for a 3-season window ending in 2025
    cast({{ dbt.split_part('year_range', "'-'", 1) }} as integer)          as window_first_season,
    cast(coalesce(nullif({{ dbt.split_part('year_range', "'-'", 2) }}, ''),
                  {{ dbt.split_part('year_range', "'-'", 1) }}) as integer) as window_last_season,
    cast(n_pa as integer)                       as n_pa,           -- sample size: plate appearances

    -- indexes
    cast(index_runs     as integer)             as pf_runs,
    cast(index_hits     as integer)             as pf_hits,
    cast(index_1b       as integer)             as pf_1b,
    cast(index_2b       as integer)             as pf_2b,
    cast(index_3b       as integer)             as pf_3b,
    cast(index_hr       as integer)             as pf_hr,
    cast(index_bb       as integer)             as pf_bb,
    cast(index_so       as integer)             as pf_so,
    cast(index_obp      as integer)             as pf_obp,
    cast(index_woba     as integer)             as pf_woba,
    cast(index_wobacon  as integer)             as pf_wobacon,     -- wOBA on contact
    cast(index_xwobacon as integer)             as pf_xwobacon,    -- expected wOBA on contact
    cast(index_bacon    as integer)             as pf_bacon,       -- batting average on contact
    cast(index_xbacon   as integer)             as pf_xbacon,
    cast(index_hardhit  as integer)             as pf_hardhit,     -- 95+ mph exit velocity rate
    cast(index_wobatto  as integer)             as pf_wobatto,

    -- lineage
    filename                                    as _source_file,
    _ingested_at

from source
