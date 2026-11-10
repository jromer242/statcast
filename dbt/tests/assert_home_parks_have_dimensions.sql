-- Every venue that hosted 20+ completed games in a season (a team's real home park) must
-- have Savant measured dimensions for that season. One-off neutral sites (Tokyo, London,
-- Williamsport...) host a game or two and are expected to be missing.
-- Usual cause of failure: ingest_park_dimensions.py not run for that season.
--
-- dbt singular test: any row this query returns is a failure.

with home_parks as (

    select season, venue_id, any_value(venue_name) as venue_name, count(*) as games
    from {{ ref('stg_mlb__games') }}
    where status in ('Final', 'Completed Early')
    group by season, venue_id
    having count(*) >= 20

)

select h.*
from home_parks h
left join {{ ref('stg_savant__park_dimensions') }} d
    on h.venue_id = d.venue_id
   and h.season = d.season
where d.venue_id is null
