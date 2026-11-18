-- One row per venue per season: everything known about a park *before* that season starts.
-- Pitches reach it through stg_mlb__games on (venue_id, season).
--
-- Leakage rule: park factors and environment are computed from a season's own batted
-- balls, so a season's row only gets values from the previous season
-- (park_factor_season = season - 1). The 3-season window used here therefore covers
-- S-3..S-1. Physical facts (location, dimensions, wall heights) are known before the
-- season, so they use the same season.

with venues as (

    select * from {{ ref('stg_mlb__venues') }}

),

dimensions as (

    select * from {{ ref('stg_savant__park_dimensions') }}

),

-- One row per (venue_id, season) with the factors we use, pivoted out of the
-- rolling_years x bat_side rows.
factors as (

    select
        venue_id,
        season,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_runs end)        as pf_runs_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_hr end)          as pf_hr_3yr,
        max(case when rolling_years = 3 and bat_side = 'L' then pf_hr end)            as pf_hr_3yr_lhb,
        max(case when rolling_years = 3 and bat_side = 'R' then pf_hr end)            as pf_hr_3yr_rhb,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_hits end)        as pf_hits_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_2b end)          as pf_2b_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_3b end)          as pf_3b_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_bb end)          as pf_bb_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_so end)          as pf_so_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_woba end)        as pf_woba_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then pf_hardhit end)     as pf_hardhit_3yr,
        max(case when rolling_years = 3 and bat_side = 'All' then n_pa end)           as pf_n_pa_3yr,
        max(case when rolling_years = 1 and bat_side = 'All' then pf_runs end)        as pf_runs_1yr,
        max(case when rolling_years = 1 and bat_side = 'All' then pf_hr end)          as pf_hr_1yr,
        max(case when rolling_years = 1 and bat_side = 'All' then n_pa end)           as pf_n_pa_1yr
    from {{ ref('stg_savant__park_factors') }}
    group by venue_id, season

),

environment as (

    select * from {{ ref('stg_savant__park_environment') }}

)

select
    -- keys
    v.venue_id,
    v.season,
    v.venue_name,

    -- location and orientation (from the Stats API)
    v.city,
    v.state,
    v.country,
    v.latitude,
    v.longitude,
    v.elevation_ft,
    v.azimuth_deg,
    v.time_zone,
    v.roof_type,
    v.turf_type,

    -- measured dimensions, same season (from Savant). Null for one-off neutral sites.
    d.venue_id is not null                      as has_measured_dimensions,
    d.walls_changed,
    d.distance_lf_line_ft,
    d.distance_lf_gap_ft,
    d.distance_cf_ft,
    d.distance_rf_gap_ft,
    d.distance_rf_line_ft,
    d.distance_deepest_ft,
    d.avg_fence_distance_ft,
    d.height_lf_line_ft,
    d.height_lf_gap_ft,
    d.height_cf_ft,
    d.height_rf_gap_ft,
    d.height_rf_line_ft,
    d.height_highest_ft,
    d.avg_fence_height_ft,
    d.fair_area_sqft,

    -- park factors from the PREVIOUS season (leakage rule above). Null when the park had
    -- no qualifying sample then: neutral sites, or a team's first season in a park.
    v.season - 1                                as park_factor_season,
    f.venue_id is not null                      as has_prior_park_factors,
    f.pf_runs_3yr                               as prior_pf_runs_3yr,
    f.pf_hr_3yr                                 as prior_pf_hr_3yr,
    f.pf_hr_3yr_lhb                             as prior_pf_hr_3yr_lhb,
    f.pf_hr_3yr_rhb                             as prior_pf_hr_3yr_rhb,
    f.pf_hits_3yr                               as prior_pf_hits_3yr,
    f.pf_2b_3yr                                 as prior_pf_2b_3yr,
    f.pf_3b_3yr                                 as prior_pf_3b_3yr,
    f.pf_bb_3yr                                 as prior_pf_bb_3yr,
    f.pf_so_3yr                                 as prior_pf_so_3yr,
    f.pf_woba_3yr                               as prior_pf_woba_3yr,
    f.pf_hardhit_3yr                            as prior_pf_hardhit_3yr,
    f.pf_n_pa_3yr                               as prior_pf_n_pa_3yr,
    f.pf_runs_1yr                               as prior_pf_runs_1yr,
    f.pf_hr_1yr                                 as prior_pf_hr_1yr,
    f.pf_n_pa_1yr                               as prior_pf_n_pa_1yr,

    -- fly ball carry from the PREVIOUS season, feet versus an average park
    e.extra_distance_ft                         as prior_extra_distance_ft,
    e.elevation_extra_distance_ft               as prior_elevation_extra_distance_ft,
    e.temperature_extra_distance_ft             as prior_temperature_extra_distance_ft,
    e.roof_extra_distance_ft                    as prior_roof_extra_distance_ft,
    e.environment_extra_distance_ft             as prior_environment_extra_distance_ft

from venues v
left join dimensions d
    on d.venue_id = v.venue_id and d.season = v.season
left join factors f
    on f.venue_id = v.venue_id and f.season = v.season - 1
left join environment e
    on e.venue_id = v.venue_id and e.season = v.season - 1
