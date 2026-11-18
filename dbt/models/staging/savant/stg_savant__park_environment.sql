-- One row per park per season (2016+): how many extra feet a fly ball carries in this park
-- compared with an average park, and why. Savant splits the total into elevation,
-- temperature, roof and other environment (wind, humidity...).
--
-- Computed from the season's own batted balls and weather: dim_venue_seasons uses the
-- previous season's values for modeling.

with source as (

    select * from {{ source('savant', 'park_environment_raw') }}

)

select
    -- keys
    cast(venue_id as integer)                       as venue_id,
    cast(year as integer)                           as season,

    venue_name,
    cast(main_team_id as integer)                   as home_team_id,
    cast(n as integer)                              as n_games,
    cast(elevation_feet as integer)                 as elevation_ft,

    -- conditions over the season
    cast(avg_roof as {{ type_double() }})                        as pct_games_roof_closed,
    cast(avg_daytime as {{ type_double() }})                     as pct_games_daytime,
    cast(avg_temperature as {{ type_double() }})                 as avg_temperature_f,

    -- extra carry in feet; the four parts add up to the total
    cast(extra_distance as {{ type_double() }})                  as extra_distance_ft,
    cast(elevation_extra_distance as {{ type_double() }})        as elevation_extra_distance_ft,
    cast(temperature_extra_distance as {{ type_double() }})      as temperature_extra_distance_ft,
    cast(roof_extra_distance as {{ type_double() }})             as roof_extra_distance_ft,
    cast(environment_extra_distance as {{ type_double() }})      as environment_extra_distance_ft,

    -- lineage
    filename                                        as _source_file,
    _ingested_at

from source
