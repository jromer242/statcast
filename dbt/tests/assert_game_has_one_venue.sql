-- A suspended game finished in a different park would get one venue_id in stg_mlb__games
-- (the dedupe keeps the latest row), so day-one pitches would get the wrong park.
-- Checks the raw schedule, because staging has already dropped the earlier row.
--
-- Postponed and cancelled rows are excluded: no pitches were thrown, so a makeup at a
-- different park is harmless.
-- dbt singular test: any row this query returns is a failure.

select
    gamePk                                  as game_pk,
    count(distinct venue.id)                as venues,
    list(distinct venue.name)               as venue_names
from {{ source('mlb', 'schedule_raw') }}
where status.detailedState not in ('Postponed', 'Cancelled')
group by gamePk
having count(distinct venue.id) > 1
