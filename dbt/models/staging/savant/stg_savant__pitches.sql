-- One row per pitch, cleaned and deduplicated.
-- Staging rules: rename, cast, drop dead columns, dedupe. No joins, no business logic.

-- The biggest table, so on BigQuery it's partitioned by month of game_date (queries for
-- a date range read only those months) and clustered by game_pk (the PA and batted-ball
-- models group by it). No-ops on DuckDB: see macros/cross_db.sql.
{{
    config(
        partition_by=bq_partition_by('game_date'),
        cluster_by=bq_cluster_by(['game_pk'])
    )
}}

with source as (

    select * from {{ source('savant', 'statcast_raw') }}

),

deduped as (

    -- The same pitch can be in several files when date ranges were re-pulled.
    -- Keep the most recently ingested copy; files from before _ingested_at existed sort last.
    select *
    from source
    qualify row_number() over (
        partition by game_pk, at_bat_number, pitch_number
        order by _ingested_at desc nulls last, filename desc
    ) = 1

),

renamed as (

    select
        -- keys
        cast(game_pk as string) || '-' || cast(at_bat_number as string)
            || '-' || cast(pitch_number as string)  as pitch_id,
        game_pk,
        at_bat_number,
        pitch_number,

        -- game context
        cast(game_date as date)                 as game_date,
        cast(game_year as integer)              as season,
        game_type,
        home_team,
        away_team,
        inning,
        inning_topbot,
        outs_when_up,
        balls,
        strikes,
        on_1b                                   as runner_on_1b_id,
        on_2b                                   as runner_on_2b_id,
        on_3b                                   as runner_on_3b_id,
        home_score,
        away_score,
        bat_score,
        fld_score,
        home_score_diff,
        bat_score_diff,
        if_fielding_alignment,
        of_fielding_alignment,

        -- players
        batter                                  as batter_id,
        pitcher                                 as pitcher_id,
        player_name                             as pitcher_name,  -- Savant names the pitcher here, not the batter
        stand                                   as batter_stand,
        p_throws                                as pitcher_throws,
        age_bat                                 as batter_age,
        age_pit                                 as pitcher_age,
        fielder_2                               as catcher_id,
        fielder_3                               as first_base_id,
        fielder_4                               as second_base_id,
        fielder_5                               as third_base_id,
        fielder_6                               as shortstop_id,
        fielder_7                               as left_field_id,
        fielder_8                               as center_field_id,
        fielder_9                               as right_field_id,
        n_thruorder_pitcher                     as pitcher_times_through_order,
        n_priorpa_thisgame_player_at_bat        as batter_prior_pa_this_game,
        pitcher_days_since_prev_game,
        batter_days_since_prev_game,

        -- pitch
        pitch_type,
        pitch_name,
        release_speed,
        effective_speed,
        release_spin_rate,
        spin_axis,
        release_extension,
        release_pos_x,
        release_pos_y,
        release_pos_z,
        arm_angle,
        pfx_x,
        pfx_z,
        api_break_z_with_gravity                as break_z_with_gravity,
        api_break_x_arm                         as break_x_arm_side,
        api_break_x_batter_in                   as break_x_batter_in,
        vx0,
        vy0,
        vz0,
        ax,
        ay,
        az,
        plate_x,
        plate_z,
        sz_top,
        sz_bot,
        zone,

        -- swing (bat tracking; null before 2023 and on takes)
        bat_speed,
        swing_length,
        swing_path_tilt,
        attack_angle,
        attack_direction,
        miss_distance,
        intercept_ball_minus_batter_pos_x_inches as intercept_x_inches,
        intercept_ball_minus_batter_pos_y_inches as intercept_y_inches,

        -- result of the pitch
        type                                    as pitch_result_type,  -- B ball, S strike, X in play
        description                             as pitch_description,
        events                                  as pa_event,           -- set only on the last pitch of a PA
        des                                     as play_description,
        bb_type                                 as batted_ball_type,
        hit_location,
        hc_x,
        hc_y,
        launch_speed,
        launch_angle,
        launch_speed_angle,
        hit_distance_sc                         as hit_distance,
        hyper_speed,
        estimated_ba_using_speedangle           as xba,
        estimated_slg_using_speedangle          as xslg,
        estimated_woba_using_speedangle         as xwoba,
        woba_value,
        woba_denom,
        babip_value,
        iso_value,

        -- outcomes known only after the pitch: never use as model inputs for this pitch
        post_home_score,
        post_away_score,
        post_bat_score,
        post_fld_score,
        delta_run_exp,
        delta_pitcher_run_exp,
        delta_home_win_exp,
        home_win_exp,
        bat_win_exp,
        pitcher_days_until_next_game,
        batter_days_until_next_game,

        -- lineage
        filename                                as _source_file,
        _ingested_at

        -- dropped: spin_dir, spin_rate_deprecated, break_angle_deprecated,
        -- break_length_deprecated, tfs_deprecated, tfs_zulu_deprecated, umpire, sv_id
        -- (always null), age_pit_legacy, age_bat_legacy (superseded by age_pit/age_bat),
        -- season (hive folder; duplicates game_year)

    from deduped

)

select * from renamed
