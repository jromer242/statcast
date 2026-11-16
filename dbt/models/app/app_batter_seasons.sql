-- One row per batter per regular season: the leaderboard. Rates use completed plate
-- appearances only (truncated PAs excluded). Postseason is left out, as in official
-- season stats. For the Streamlit app (see _app__exposures.yml).

with pas as (

    select *
    from {{ ref('fct_plate_appearances') }}
    where game_type = 'R'
      and is_completed_pa

),

batting as (

    select
        batter_id,
        season,
        -- the team with most of their PAs (a traded player's latest team can differ)
        mode(batting_team)                                      as team,
        count(*)                                                as pa,
        count(*) filter (where is_at_bat)                       as ab,
        count(*) filter (where is_hit)                          as hits,
        count(*) filter (where is_home_run)                     as hr,
        count(*) filter (where is_strikeout)                    as so,
        count(*) filter (where is_walk)                         as bb,
        sum(total_bases)                                        as total_bases,
        sum(woba_value)                                         as woba_value,
        sum(woba_denom)                                         as woba_denom
    from pas
    group by batter_id, season

),

contact as (

    select
        batter_id,
        season,
        count(*)                                                as batted_balls,
        avg(launch_speed)                                       as avg_exit_velo,
        avg(case when launch_speed >= 95 then 1.0 else 0.0 end) as hard_hit_rate,
        avg(case when batted_ball_type = 'fly_ball'
                  and spray_direction = 'pull' then 1.0 else 0.0 end)
                                                                as pulled_fly_ball_rate,
        max(hit_distance) filter (where is_home_run)            as longest_hr_ft
    from {{ ref('fct_batted_balls') }}
    where game_type = 'R'
    group by batter_id, season

)

select
    b.batter_id,
    b.season,
    p.full_name                                             as batter_name,
    p.bats,
    b.team,
    b.pa,
    b.ab,
    b.hits,
    b.hr,
    b.so,
    b.bb,
    round(b.hr / b.pa, 4)                                   as hr_per_pa,
    round(b.hits / nullif(b.ab, 0), 3)                      as batting_avg,
    round(b.total_bases / nullif(b.ab, 0), 3)               as slugging,
    round(b.so / b.pa, 3)                                   as strikeout_rate,
    round(b.bb / b.pa, 3)                                   as walk_rate,
    round(b.woba_value / nullif(b.woba_denom, 0), 3)        as woba,
    c.batted_balls,
    round(c.avg_exit_velo, 1)                               as avg_exit_velo,
    round(c.hard_hit_rate, 3)                               as hard_hit_rate,
    round(c.pulled_fly_ball_rate, 3)                        as pulled_fly_ball_rate,
    c.longest_hr_ft
from batting b
join {{ ref('dim_players') }} p
    on p.player_id = b.batter_id
left join contact c
    on c.batter_id = b.batter_id and c.season = b.season
