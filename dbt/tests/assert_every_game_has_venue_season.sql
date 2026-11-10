-- Every game in stg_mlb__games must find its venue in stg_mlb__venues for the same season.
-- Venues are snapshots per season, so a game whose (venue_id, season) is missing would get
-- no park data. Usual cause: ingest_venues.py not run for a season ingest_schedule.py loaded.
--
-- dbt singular test: any row this query returns is a failure.

select
    g.game_pk,
    g.season,
    g.venue_id,
    g.venue_name
from {{ ref('stg_mlb__games') }} g
left join {{ ref('stg_mlb__venues') }} v
    on g.venue_id = v.venue_id
   and g.season = v.season
where v.venue_id is null
