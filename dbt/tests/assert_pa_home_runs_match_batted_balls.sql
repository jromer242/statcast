-- The two facts must agree on home runs: every PA ending in a home run has a batted ball
-- in fct_batted_balls marked is_home_run, and vice versa, per season. A mismatch means
-- one mart's filter drifted (game types, the in-play rule) or the incremental batted
-- ball table is stale.
--
-- dbt singular test: any row this query returns is a failure.

with pa as (

    select season, count(*) as home_runs
    from {{ ref('fct_plate_appearances') }}
    where is_home_run
    group by season

),

bb as (

    select season, count(*) as home_runs
    from {{ ref('fct_batted_balls') }}
    where is_home_run
    group by season

)

select
    coalesce(pa.season, bb.season)  as season,
    pa.home_runs                    as pa_home_runs,
    bb.home_runs                    as batted_ball_home_runs
from pa
full outer join bb using (season)
where pa.home_runs is distinct from bb.home_runs
