-- One row per player per season: who they are (name, birth date, bats, throws) and how
-- they were listed that season (position, height, weight).
-- Dropped: currentTeam, currentAge and active. They describe the player on the day of
-- the pull, so on a past season's snapshot they'd be wrong without looking wrong.

with source as (

    select * from {{ source('mlb', 'players_raw') }}

)

select
    -- keys
    id                                          as player_id,
    cast(season as integer)                     as season,

    -- name
    fullName                                    as full_name,
    firstName                                   as first_name,
    lastName                                    as last_name,
    useName                                     as use_first_name,  -- the first name used day to day
    boxscoreName                                as boxscore_name,

    -- bio
    cast(birthDate as date)                     as birth_date,
    birthCountry                                as birth_country,
    cast(mlbDebutDate as date)                  as mlb_debut_date,
    draftYear                                   as draft_year,

    -- handedness: bats L, R or S (switch); throws L or R
    batSide.code                                as bats,
    pitchHand.code                              as throws,

    -- as listed that season
    primaryPosition.abbreviation                as primary_position,
    primaryPosition.type                        as position_type,
    -- height arrives as text like 6' 2": the first number is feet, the last is inches
    cast({{ regexp_capture('height', '^([0-9]+)') }} as integer) * 12
        + cast({{ regexp_capture('height', '([0-9]+)[^0-9]*$') }} as integer)
                                                as height_in,
    weight                                      as weight_lb,
    -- strike zone top and bottom (feet) the API uses for this player
    strikeZoneTop                               as strike_zone_top_ft,
    strikeZoneBottom                            as strike_zone_bottom_ft,

    -- lineage
    filename                                    as _source_file,
    _ingested_at

from source
