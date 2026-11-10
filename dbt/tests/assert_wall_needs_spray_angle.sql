-- The wall columns depend on the ball's direction, so they must be null whenever
-- spray_angle_deg is null (no hit coordinates). Written after DuckDB's least(), which
-- skips NULLs, gave 130 such balls the right field line's distance.
--
-- dbt singular test: any row this query returns is a failure.

select pitch_id, spray_angle_deg, wall_distance_at_spray_ft, wall_height_at_spray_ft
from {{ ref('fct_batted_balls') }}
where spray_angle_deg is null
  and (wall_distance_at_spray_ft is not null or wall_height_at_spray_ft is not null)
