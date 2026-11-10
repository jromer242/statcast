-- One row per batted ball (a pitch put in play) in regular-season and postseason games,
-- with its park and where it went relative to that park's wall.
--
-- Grain: pitch_id. Built incrementally: each run rebuilds the last
-- `batted_balls_lookback_days` days before the newest game already loaded (Savant
-- corrects recent data for a few days). After loading park dimensions, re-pulling
-- older pitches, or changing this logic, run with --full-refresh.
--
-- Contact columns (launch speed, angle, distance, spray) describe what happened on the
-- pitch. They are model INPUTS for a batted-ball HR model, but never inputs for a model
-- predicting the plate appearance before the pitch.

{{
    config(
        materialized='incremental',
        unique_key='pitch_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

{% set gap = var('fence_gap_angle_deg') %}

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
          select max(game_date) - interval {{ var('batted_balls_lookback_days') }} day
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
        degrees(atan2(hc_x - 125.42, 198.27 - hc_y))   as spray_angle_deg
    from pitches

),

-- Wall distance and height at the ball's spray angle, linearly interpolated between
-- Savant's five measured points: lines (+-45), gaps (+-gap) and center (0).
-- Savant doesn't publish the gap angle. Choose it by how well distance past the wall
-- separates home runs from other fly balls and line drives (2024-26 AUC: 0.99699 at
-- 17.5, 0.99690 at 20, 0.99659 at 22.5, 0.99435 at 30; raw distance 0.9720). 17.5-22.5
-- are nearly tied; notebooks/06_wall_distance_auc.ipynb re-checks it with a
-- train/test split. Balls hooking past a line use the line's value.
walls as (

    select
        s.*,
        g.venue_id,
        -- DuckDB's least() skips NULLs (least(NULL, 45) = 45), so guard it: no hit
        -- coordinates means no spray angle and no wall.
        case when s.spray_angle_deg is not null
             then least(abs(s.spray_angle_deg), 45) end  as abs_angle,
        case when s.spray_angle_deg < 0 then v.distance_lf_gap_ft  else v.distance_rf_gap_ft  end as gap_distance,
        case when s.spray_angle_deg < 0 then v.distance_lf_line_ft else v.distance_rf_line_ft end as line_distance,
        case when s.spray_angle_deg < 0 then v.height_lf_gap_ft    else v.height_rf_gap_ft    end as gap_height,
        case when s.spray_angle_deg < 0 then v.height_lf_line_ft   else v.height_rf_line_ft   end as line_height,
        v.distance_cf_ft                                as center_distance,
        v.height_cf_ft                                  as center_height
    from spray s
    left join games g
        on g.game_pk = s.game_pk
    left join venues v
        on v.venue_id = g.venue_id
       and v.season = s.season

),

interpolated as (

    select
        *,
        case
            when abs_angle <= {{ gap }}
                then center_distance + (gap_distance - center_distance) * abs_angle / {{ gap }}
            else gap_distance + (line_distance - gap_distance) * (abs_angle - {{ gap }}) / (45 - {{ gap }})
        end                                             as wall_distance_at_spray_ft,
        case
            when abs_angle <= {{ gap }}
                then center_height + (gap_height - center_height) * abs_angle / {{ gap }}
            else gap_height + (line_height - gap_height) * (abs_angle - {{ gap }}) / (45 - {{ gap }})
        end                                             as wall_height_at_spray_ft
    from walls

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
        and play_description ilike '%inside-the-park%'  as is_inside_the_park_hr,
    pa_event = 'home_run'
        and play_description not ilike '%inside-the-park%' as is_over_fence_hr,

    -- Savant's expected stats from launch speed and angle (benchmarks to beat)
    xba,
    xslg,
    xwoba,

    -- lineage
    _ingested_at

from interpolated
