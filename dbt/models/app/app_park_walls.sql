-- One row per park, season and spray angle (whole degrees, -45 to 45): the wall's
-- distance and height there, plus x/y feet from home plate for drawing the outline.
-- Uses the same wall_at_angle macro as fct_batted_balls. Only teams' home parks that
-- Savant measured: one-off neutral sites (Williamsport, Rickwood, Bristol, Field of
-- Dreams, Las Vegas) are left out, since nobody plays a season there.
-- For the Streamlit app (see _app__exposures.yml).

-- A team's home that season: hosted games that weren't at a neutral site (20+ games,
-- the same rule as dim_games.is_neutral_site).
with home_parks as (

    select distinct venue_id, season
    from {{ ref('dim_games') }}
    where not is_neutral_site

),

parks as (

    select p.*
    from {{ ref('dim_venue_seasons') }} p
    join home_parks h using (venue_id, season)
    where p.has_measured_dimensions

),

angles as (

    select cast(a as double) as angle_deg from range(-45, 46) t(a)

),

walls as (

    select
        p.venue_id,
        p.season,
        p.venue_name,
        a.angle_deg,
        {{ wall_at_angle('a.angle_deg', 'distance', 'p.') }}   as wall_distance_ft,
        {{ wall_at_angle('a.angle_deg', 'height', 'p.') }}     as wall_height_ft
    from parks p
    cross join angles a

)

select
    venue_id,
    season,
    venue_name,
    cast(angle_deg as integer)                              as angle_deg,
    round(wall_distance_ft, 1)                              as wall_distance_ft,
    round(wall_height_ft, 1)                                as wall_height_ft,
    -- negative x is left field, y points from home plate to center field
    round(wall_distance_ft * sin(radians(angle_deg)), 1)    as x_ft,
    round(wall_distance_ft * cos(radians(angle_deg)), 1)    as y_ft
from walls
