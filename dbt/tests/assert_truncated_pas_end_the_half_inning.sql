-- fct_plate_appearances calls an encounter with no event (or truncated_pa) a PA cut
-- short by the third out on the bases. That's only true if the next encounter in the
-- game is in a different half-inning. On 2024-26 it holds for all ~1,300 of them; a
-- failure means Savant started leaving events off real PAs, which would undercount
-- PAs and outcomes.
--
-- dbt singular test: any row this query returns is a failure.

with pas as (

    select
        pa_id,
        game_pk,
        at_bat_number,
        inning,
        inning_topbot,
        is_completed_pa,
        lead(inning) over w         as next_inning,
        lead(inning_topbot) over w  as next_inning_topbot
    from {{ ref('fct_plate_appearances') }}
    window w as (partition by game_pk order by at_bat_number)

)

select pa_id, inning, inning_topbot, next_inning, next_inning_topbot
from pas
where not is_completed_pa
  and next_inning = inning
  and next_inning_topbot = inning_topbot
