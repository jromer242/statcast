-- One row per game (regular season and postseason): when and where it was played, who
-- played, and how it went.
--
-- Built on stg_mlb__games, which already keeps one row per game_pk (the makeup of a
-- postponed game, the resumption of a suspended one). Adds what the schedule doesn't
-- say directly: local start time, whether the park was a one-off neutral site, and
-- the team abbreviations Statcast uses (fct_plate_appearances.batting_team).

with games as (

    select * from {{ ref('stg_mlb__games') }}

),

venues as (

    select venue_id, season, time_zone from {{ ref('stg_mlb__venues') }}

),

-- Statcast's team abbreviations (NYY, LAD...) and pitch counts per game. Games
-- without pitches (cancelled) get nulls.
statcast as (

    select
        game_pk,
        any_value(home_team)    as home_team_abbrev,
        any_value(away_team)    as away_team_abbrev,
        count(*)                as pitches
    from {{ ref('stg_savant__pitches') }}
    group by game_pk

),

-- A venue's completed games that season. 20+ means it's a team's real home park; fewer
-- means a one-off neutral site (Tokyo, London, Williamsport...). Same threshold as the
-- assert_home_parks_* tests.
venue_games as (

    select season, venue_id, count(*) as completed_games
    from games
    where status in ('Final', 'Completed Early')
    group by season, venue_id

)

select
    -- keys
    g.game_pk,
    g.venue_id,
    g.home_team_id,
    g.away_team_id,

    -- when
    g.official_date,
    g.season,
    g.game_datetime_utc,
    -- Scheduled start in the park's local time. timezone('UTC', ...) reads the stored
    -- value as UTC, so the result doesn't depend on the machine's time zone.
    timezone(v.time_zone, timezone('UTC', g.game_datetime_utc))     as game_datetime_local,
    hour(timezone(v.time_zone, timezone('UTC', g.game_datetime_utc)))
                                                                    as local_start_hour,
    g.day_night,

    -- what kind of game
    g.game_type,
    g.game_type <> 'R'                                              as is_postseason,
    g.series_description,
    g.double_header,
    g.game_number,
    g.scheduled_innings,

    -- where and who
    g.venue_name,
    coalesce(vg.completed_games, 0) < 20                            as is_neutral_site,
    g.home_team_name,
    g.away_team_name,
    s.home_team_abbrev,
    s.away_team_abbrev,

    -- status
    g.status,
    g.status in ('Final', 'Completed Early')                        as is_completed,
    g.status_reason,
    g.resumed_from_utc is not null                                  as was_suspended,
    g.rescheduled_from_utc is not null                              as was_rescheduled,
    s.game_pk is not null                                           as has_pitch_data,
    coalesce(s.pitches, 0)                                          as pitches,

    -- outcome (post-game: never a pre-game feature)
    g.home_score,
    g.away_score

from games g
left join venues v
    on v.venue_id = g.venue_id and v.season = g.season
left join statcast s
    on s.game_pk = g.game_pk
left join venue_games vg
    on vg.venue_id = g.venue_id and vg.season = g.season
