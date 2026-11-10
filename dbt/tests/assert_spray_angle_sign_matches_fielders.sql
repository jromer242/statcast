-- Guards the spray angle sign convention (negative = left field, positive = right field)
-- that pull_angle_deg and the wall interpolation depend on. Balls fielded by the left
-- fielder (hit_location 7) must average well left of center, and right fielder (9) balls
-- well right, in every season. Fails if Savant flips or rescales its hit coordinates.
--
-- dbt singular test: any row this query returns is a failure.

with by_fielder as (

    select
        f.season,
        p.hit_location,
        avg(f.spray_angle_deg) as avg_spray_angle_deg
    from {{ ref('fct_batted_balls') }} f
    join {{ ref('stg_savant__pitches') }} p
        on p.pitch_id = f.pitch_id
    where p.hit_location in (7, 9)
    group by f.season, p.hit_location

)

select *
from by_fielder
where (hit_location = 7 and not avg_spray_angle_deg < -15)
   or (hit_location = 9 and not avg_spray_angle_deg > 15)
