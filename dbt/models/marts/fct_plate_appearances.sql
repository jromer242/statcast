-- One row per plate appearance in regular-season and postseason games: who faced whom,
-- the situation when it started, and how it ended.
--
-- Grain: pa_id (game_pk-at_bat_number). Savant's at_bat_number counts batter-pitcher
-- encounters within a game, and its event is always on the encounter's last pitch.
--
-- Not every encounter is a plate appearance. When the inning ends while the batter is
-- still up (caught stealing, pickoff), Savant either labels the last pitch
-- `truncated_pa` or leaves it with no event at all (~1,300 of 560k on 2024-26). The
-- batter leads off the next inning with a new at_bat_number and a fresh count. Those
-- rows stay here (pitches were thrown) with is_completed_pa = false and pa_event =
-- 'truncated_pa'; filter on is_completed_pa for anything that counts PAs.
--
-- Situation columns (inning, outs, runners, score) are from the first pitch, so they're
-- known before the PA starts. Result columns are outcomes: never model inputs for this PA.
-- first_by / last_by (macros/cross_db.sql) read a column on the PA's first or last pitch,
-- keeping NULLs: a runner who reaches second during the PA isn't "on second at the start".
--
-- On BigQuery: partitioned by month, clustered by batter and pitcher, and the post-hook
-- adds row-level security (macros/row_access_policies.sql). All three are no-ops on DuckDB.

{{
    config(
        partition_by=bq_partition_by('game_date'),
        cluster_by=bq_cluster_by(['batter_id', 'pitcher_id']),
        post_hook="{{ row_access_policies() }}"
    )
}}

with pitches as (

    select *
    from {{ ref('stg_savant__pitches') }}
    -- Spring training has no schedule rows, so no park.
    where game_type in ('R', 'F', 'D', 'L', 'W')

),

encounters as (

    select
        game_pk,
        at_bat_number,

        -- situation at the first pitch
        {{ first_by('inning', 'pitch_number') }}                        as inning,
        {{ first_by('inning_topbot', 'pitch_number') }}                 as inning_topbot,
        {{ first_by('outs_when_up', 'pitch_number') }}                  as outs_at_start,
        {{ first_by('runner_on_1b_id', 'pitch_number') }} is not null   as runner_on_1b_at_start,
        {{ first_by('runner_on_2b_id', 'pitch_number') }} is not null   as runner_on_2b_at_start,
        {{ first_by('runner_on_3b_id', 'pitch_number') }} is not null   as runner_on_3b_at_start,
        {{ first_by('bat_score_diff', 'pitch_number') }}                as bat_score_diff_at_start,
        {{ first_by('pitcher_times_through_order', 'pitch_number') }}   as pitcher_times_through_order,

        -- players: the last pitch's batter and pitcher are the ones the result is
        -- charged to in the common case (a mid-PA pitching change is rare)
        {{ last_by('batter_id', 'pitch_number') }}                      as batter_id,
        {{ last_by('pitcher_id', 'pitch_number') }}                     as pitcher_id,
        {{ last_by('batter_stand', 'pitch_number') }}                   as batter_stand,
        {{ last_by('pitcher_throws', 'pitch_number') }}                 as pitcher_throws,
        count(distinct pitcher_id)                                      as pitchers_in_pa,

        -- result, from the last pitch
        count(*)                                                        as pitches,
        {{ last_by('balls', 'pitch_number') }}                          as final_balls,
        {{ last_by('strikes', 'pitch_number') }}                        as final_strikes,
        {{ last_by('pa_event', 'pitch_number') }}                       as raw_pa_event,
        {{ last_by('pitch_result_type', 'pitch_number') }}              as last_pitch_result_type,
        {{ last_by('batted_ball_type', 'pitch_number') }}               as last_pitch_batted_ball_type,
        {{ last_by('pitch_id', 'pitch_number') }}                       as last_pitch_id,
        {{ last_by('woba_value', 'pitch_number') }}                     as woba_value,
        {{ last_by('woba_denom', 'pitch_number') }}                     as woba_denom,
        sum(delta_run_exp)                                              as run_value,

        -- game context (same on every pitch)
        any_value(game_date)                                            as game_date,
        any_value(season)                                               as season,
        any_value(game_type)                                            as game_type,
        any_value(home_team)                                            as home_team,
        any_value(away_team)                                            as away_team

    from pitches
    group by game_pk, at_bat_number

),

games as (

    select game_pk, venue_id from {{ ref('stg_mlb__games') }}

),

labeled as (

    select
        *,
        coalesce(raw_pa_event, 'truncated_pa')              as pa_event
    from encounters

)

select
    -- keys
    cast(l.game_pk as string) || '-' || cast(l.at_bat_number as string)  as pa_id,
    l.game_pk,
    l.at_bat_number,
    g.venue_id,
    l.batter_id,
    l.pitcher_id,

    -- game
    l.game_date,
    l.season,
    l.game_type,
    l.home_team,
    l.away_team,
    case l.inning_topbot when 'Top' then l.away_team else l.home_team end  as batting_team,
    case l.inning_topbot when 'Top' then l.home_team else l.away_team end  as fielding_team,

    -- situation at the start (known before the PA)
    l.inning,
    l.inning_topbot,
    l.outs_at_start,
    l.runner_on_1b_at_start,
    l.runner_on_2b_at_start,
    l.runner_on_3b_at_start,
    l.bat_score_diff_at_start,
    l.pitcher_times_through_order,
    l.batter_stand,
    l.pitcher_throws,
    l.batter_stand = l.pitcher_throws                       as is_same_handed,
    l.pitchers_in_pa,

    -- result (outcomes: never inputs for predicting this PA)
    l.pa_event,
    l.pa_event <> 'truncated_pa'                            as is_completed_pa,
    l.pitches,
    l.final_balls,
    l.final_strikes,
    l.pa_event in ('single', 'double', 'triple', 'home_run')               as is_hit,
    l.pa_event = 'home_run'                                 as is_home_run,
    l.pa_event in ('strikeout', 'strikeout_double_play')    as is_strikeout,
    l.pa_event in ('walk', 'intent_walk')                   as is_walk,
    l.pa_event = 'hit_by_pitch'                             as is_hit_by_pitch,
    -- Official at bat: a completed PA minus walks, HBP, sacrifices and interference.
    l.pa_event not in (
        'truncated_pa', 'walk', 'intent_walk', 'hit_by_pitch', 'catcher_interf',
        'sac_fly', 'sac_fly_double_play', 'sac_bunt', 'sac_bunt_double_play'
    )                                                       as is_at_bat,
    case l.pa_event
        when 'single' then 1 when 'double' then 2
        when 'triple' then 3 when 'home_run' then 4 else 0
    end                                                     as total_bases,
    -- The ball in play that ended the PA, if any. Joins to fct_batted_balls.pitch_id.
    case when l.last_pitch_result_type = 'X' and l.last_pitch_batted_ball_type is not null
         then l.last_pitch_id end                           as batted_ball_pitch_id,
    l.woba_value,
    l.woba_denom,
    l.run_value

from labeled l
left join games g using (game_pk)
