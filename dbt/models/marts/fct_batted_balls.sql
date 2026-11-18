-- One row per batted ball (a pitch put in play) in regular-season and postseason games,
-- with its park and where it went relative to that park's wall.
--
-- Grain: pitch_id. Built incrementally: each run rebuilds from the start of the month
-- that holds the day `batted_balls_lookback_days` before the newest game already loaded
-- (Savant corrects recent data for a few days). After loading park dimensions,
-- re-pulling older pitches, or changing this logic, run with --full-refresh.
--
-- Whole months because of BigQuery: there the table is partitioned by month and an
-- incremental run replaces whole partitions (insert_overwrite), so the rows selected
-- must cover every month they touch, or the rest of that month would be deleted.
-- DuckDB has no partitions and replaces the selected rows by pitch_id (delete+insert).
--
-- Contact columns (launch speed, angle, distance, spray) describe what happened on the
-- pitch. They are model INPUTS for a batted-ball HR model, but never inputs for a model
-- predicting the plate appearance before the pitch.

{{
    config(
        materialized='incremental',
        unique_key='pitch_id',
        incremental_strategy='insert_overwrite' if target.type == 'bigquery' else 'delete+insert',
        partition_by=bq_partition_by('game_date'),
        cluster_by=bq_cluster_by(['batter_id', 'venue_id']),
        on_schema_change='fail'
    )
}}

with pitches as (

    select *
    from {{ ref('stg_savant__pitches') }}
    -- In play with a batted ball type. Drops 9 catcher-interference rows Savant marks as
    -- strikes and 5 in-play rows with no batted ball.
    where pitch_result_type = 'X'
      and batted_ball_type is not null
      -- Spring training has no schedule rows, so no park.
      and game_type in ('R', 'F', 'D', 'L', 'W')

    {% if is_incremental() %}
      and game_date >= (
          select cast({{ dbt.date_trunc('month',
                     dbt.dateadd('day', -var('batted_balls_lookback_days'), 'max(game_date)')) }} as date)
          from {{ this }}
      )
    {% endif %}

),

games as (

    select game_pk, venue_id from {{ ref('stg_mlb__games') }}

),

venues as (

    select * from {{ ref('dim_venue_seasons') }}

),

-- Spray angle from Savant's hit coordinates. The coordinates are pixels on a field
-- diagram with home plate near (125.42, 198.27) and y growing toward home, so the
-- angle is 0 to dead center, negative toward left field, positive toward right field.
-- The foul lines are at -45 and +45.
spray as (

    select
        *,
        {{ to_degrees('atan2(hc_x - 125.42, 198.27 - hc_y)') }}  as spray_angle_deg
    from pitches

),

-- Wall distance and height at the ball's spray angle, interpolated between Savant's five
-- measured points by the wall_at_angle macro (macros/wall_at_angle.sql), which
-- app_park_walls also uses. Savant doesn't publish the gap angle. Choose it by how well
-- distance past the wall separates home runs from other fly balls and line drives
-- (2024-26 AUC: 0.99699 at 17.5, 0.99690 at 20, 0.99659 at 22.5, 0.99435 at 30; raw
-- distance 0.9720). 17.5-22.5 are nearly tied; notebooks/06_wall_distance_auc.ipynb
-- re-checks it with a train/test split.
interpolated as (

    select
        s.*,
        g.venue_id,
        {{ wall_at_angle('s.spray_angle_deg', 'distance', 'v.') }}  as wall_distance_at_spray_ft,
        {{ wall_at_angle('s.spray_angle_deg', 'height', 'v.') }}    as wall_height_at_spray_ft
    from spray s
    left join games g
        on g.game_pk = s.game_pk
    left join venues v
        on v.venue_id = g.venue_id
       and v.season = s.season

)

select
    -- keys
    pitch_id,
    game_pk,
    at_bat_number,
    pitch_number,
    game_date,
    season,
    game_type,
    venue_id,

    -- players
    batter_id,
    pitcher_id,
    batter_stand,
    pitcher_throws,

    -- situation before the pitch
    inning,
    inning_topbot,
    outs_when_up,
    balls,
    strikes,

    -- pitch
    pitch_type,
    release_speed,
    plate_x,
    plate_z,

    -- swing (bat tracking; 2023 onward)
    bat_speed,
    swing_length,
    attack_angle,

    -- contact (outcome of the pitch: inputs for a batted-ball model only)
    batted_ball_type,
    launch_speed,
    launch_angle,
    hit_distance,
    hc_x,
    hc_y,
    launch_speed is not null and launch_angle is not null  as has_launch_data,
    hc_x is not null and hc_y is not null                  as has_hit_coordinates,

    -- direction. pull_angle_deg flips the sign for right-handed batters so positive
    -- always means the batter's pull side (left field for a righty).
    spray_angle_deg,
    case batter_stand when 'R' then -spray_angle_deg else spray_angle_deg end
                                                        as pull_angle_deg,
    case
        when spray_angle_deg is null then null
        when (case batter_stand when 'R' then -spray_angle_deg else spray_angle_deg end) > 15 then 'pull'
        when (case batter_stand when 'R' then -spray_angle_deg else spray_angle_deg end) < -15 then 'oppo'
        else 'center'
    end                                                 as spray_direction,

    -- the park's wall where the ball went. Null at neutral sites without measured
    -- dimensions, or without hit coordinates.
    wall_distance_at_spray_ft,
    wall_height_at_spray_ft,
    hit_distance - wall_distance_at_spray_ft            as distance_past_wall_ft,

    -- labels
    pa_event,
    pa_event = 'home_run'                               as is_home_run,
    pa_event = 'home_run'
        and lower(play_description) like '%inside-the-park%'      as is_inside_the_park_hr,
    pa_event = 'home_run'
        and lower(play_description) not like '%inside-the-park%'  as is_over_fence_hr,

    -- Savant's expected stats from launch speed and angle (benchmarks to beat)
    xba,
    xslg,
    xwoba,

    -- lineage
    _ingested_at

from interpolated
