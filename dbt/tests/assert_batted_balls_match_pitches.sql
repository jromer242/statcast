-- fct_batted_balls is incremental, so it can drift from its source: a re-pulled date
-- range older than the lookback window, or a pitch Savant deleted. Every in-play
-- regular-season or postseason pitch in stg_savant__pitches must be in the fact table
-- exactly once, and nothing else may be.
-- Fix: dbt build --full-refresh --select fct_batted_balls
--
-- dbt singular test: any row this query returns is a failure.

with expected as (

    select pitch_id
    from {{ ref('stg_savant__pitches') }}
    where pitch_result_type = 'X'
      and batted_ball_type is not null
      and game_type in ('R', 'F', 'D', 'L', 'W')

),

actual as (

    select pitch_id from {{ ref('fct_batted_balls') }}

)

select coalesce(e.pitch_id, a.pitch_id) as pitch_id,
       case when a.pitch_id is null then 'missing from fct_batted_balls'
            else 'not an in-play pitch in staging' end as problem
from expected e
full outer join actual a
    on a.pitch_id = e.pitch_id
where e.pitch_id is null or a.pitch_id is null
