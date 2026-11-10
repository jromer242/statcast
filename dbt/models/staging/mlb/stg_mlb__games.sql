-- One row per game_pk: the bridge from Statcast pitches (game_pk) to a venue.

with source as (

    select * from {{ source('mlb', 'schedule_raw') }}

),

-- A game_pk repeats when a game is postponed (Postponed row + makeup row) or suspended
-- (start row + resumption row). Rule from the 05 EDA notebook: keep the row with the
-- latest start time. That's the makeup (Final) or the resumption (Final, same venue).
-- Checked on 2024-2026: every kept duplicate is Final.
deduped as (

    select *
    from source
    qualify row_number() over (
        partition by gamePk
        order by gameDate desc, _ingested_at desc
    ) = 1

)

select
    -- keys
    gamePk                                  as game_pk,
    venue.id                                as venue_id,
    teams.home.team.id                      as home_team_id,
    teams.away.team.id                      as away_team_id,

    -- dates: official_date matches Statcast's game_date. game_datetime_utc is the
    -- scheduled start in UTC, so night games in the Americas fall on the next UTC day.
    officialDate                            as official_date,
    gameDate                                as game_datetime_utc,
    cast(season as integer)                 as season,

    -- game info
    gameType                                as game_type,
    status.detailedState                    as status,
    status.reason                           as status_reason,
    doubleHeader                            as double_header,   -- N, Y = traditional, S = split
    gameNumber                              as game_number,
    dayNight                                as day_night,
    scheduledInnings                        as scheduled_innings,
    description,
    venue.name                              as venue_name,
    teams.home.team.name                    as home_team_name,
    teams.away.team.name                    as away_team_name,
    seriesDescription                       as series_description,

    -- suspended / rescheduled history (from the kept row)
    resumedFrom                             as resumed_from_utc,
    rescheduledFrom                         as rescheduled_from_utc,

    -- outcome (post-game: never use as a pre-game feature)
    teams.home.score                        as home_score,
    teams.away.score                        as away_score,

    -- lineage
    filename                                as _source_file,
    _ingested_at

from deduped
