{{ config(severity = 'warn') }}

-- Warning, not error: lists real home parks (20+ completed games) with no prior-season
-- 3-year park factor. Expected for a team's first seasons in a park (the A's in
-- Sacramento from 2025, the Rays at Steinbrenner Field in 2025). Anything else on this
-- list means ingest_park_factors.py wasn't run for the previous season.
--
-- dbt singular test: rows returned are reported as warnings.

with home_parks as (

    select season, venue_id, count(*) as games
    from {{ ref('stg_mlb__games') }}
    where status in ('Final', 'Completed Early')
    group by season, venue_id
    having count(*) >= 20

)

select h.season, h.venue_id, v.venue_name, h.games, v.prior_pf_hr_1yr
from home_parks h
join {{ ref('dim_venue_seasons') }} v using (venue_id, season)
where v.prior_pf_hr_3yr is null
