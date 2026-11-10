-- Join coverage: every regular-season and postseason Statcast game must match exactly one
-- schedule row, on the same date. This is the pitch -> game_pk -> venue_id bridge; if it
-- breaks, pitches silently lose their park.
--
-- dbt singular test: any row this query returns is a failure.
-- Spring training (S) and other types are excluded: ingest_schedule.py doesn't pull them.

with statcast_games as (

    select distinct game_pk, game_date, game_type
    from {{ ref('stg_savant__pitches') }}
    where game_type in ('R', 'F', 'D', 'L', 'W')

),

schedule_matches as (

    select
        s.game_pk,
        s.game_date,
        s.game_type,
        count(g.game_pk)        as schedule_rows,
        min(g.official_date)    as official_date
    from statcast_games s
    left join {{ ref('stg_mlb__games') }} g using (game_pk)
    group by all

)

select
    *,
    case
        when schedule_rows = 0 then 'no schedule row'
        when schedule_rows > 1 then 'duplicate schedule rows (join would fan out)'
        else 'date mismatch'
    end as failure_reason
from schedule_matches
where schedule_rows <> 1
   or official_date <> game_date
