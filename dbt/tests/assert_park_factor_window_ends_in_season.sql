-- The leakage rule in dim_venue_seasons ("use season - 1") is only safe if every Savant
-- window ends in its labeled season: a 3-season window labeled 2024 must cover 2022-2024,
-- never 2023-2025. If Savant ever labeled windows by their first season, the mart would
-- quietly use future data.
--
-- dbt singular test: any row this query returns is a failure.

select venue_id, season, rolling_years, bat_side, window_first_season, window_last_season
from {{ ref('stg_savant__park_factors') }}
where window_last_season <> season
   or window_last_season - window_first_season + 1 <> rolling_years
