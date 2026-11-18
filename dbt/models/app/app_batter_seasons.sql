-- One row per batter per regular season: the leaderboard. Rates use completed plate
-- appearances only (truncated PAs excluded). Postseason is left out, as in official
-- season stats. For the Streamlit app (see _app__exposures.yml).

with pas as (

    select *
    from {{ ref('fct_plate_appearances') }}
    where game_type = 'R'
      and is_completed_pa

),

-- The team with most of their PAs (a traded player's latest team can differ). Ties go
-- to the alphabetically first team, so the answer is the same on every run and warehouse.
main_team as (

    select batter_id, season, batting_team as team
    from pas
    group by batter_id, season, batting_team
    qualify row_number() over (
        partition by batter_id, season order by count(*) desc, batting_team
    ) = 1

),

batting as (

    select
        batter_id,
        season,
        count(*)                                                as pa,
        count(case when is_at_bat then 1 end)                   as ab,
        count(case when is_hit then 1 end)                      as hits,
        count(case when is_home_run then 1 end)                 as hr,
        count(case when is_strikeout then 1 end)                as so,
        count(case when is_walk then 1 end)                     as bb,
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
        max(case when is_home_run then hit_distance end)        as longest_hr_ft
    from {{ ref('fct_batted_balls') }}
    where game_type = 'R'
    group by batter_id, season

)

select
    b.batter_id,
    b.season,
    p.full_name                                             as batter_name,
    p.bats,
    t.team,
    b.pa,
    b.ab,
    b.hits,
    b.hr,
    b.so,
    b.bb,
    {{ round_decimal('b.hr / b.pa', 4) }}                                   as hr_per_pa,
    {{ round_decimal('b.hits / nullif(b.ab, 0)', 3) }}                      as batting_avg,
    {{ round_decimal('b.total_bases / nullif(b.ab, 0)', 3) }}               as slugging,
    {{ round_decimal('b.so / b.pa', 3) }}                                   as strikeout_rate,
    {{ round_decimal('b.bb / b.pa', 3) }}                                   as walk_rate,
    {{ round_decimal('b.woba_value / nullif(b.woba_denom, 0)', 3) }}        as woba,
    c.batted_balls,
    {{ round_decimal('c.avg_exit_velo', 1) }}                               as avg_exit_velo,
    {{ round_decimal('c.hard_hit_rate', 3) }}                               as hard_hit_rate,
    {{ round_decimal('c.pulled_fly_ball_rate', 3) }}                        as pulled_fly_ball_rate,
    c.longest_hr_ft
from batting b
join main_team t
    on t.batter_id = b.batter_id and t.season = b.season
join {{ ref('dim_players') }} p
    on p.player_id = b.batter_id
left join contact c
    on c.batter_id = b.batter_id and c.season = b.season
