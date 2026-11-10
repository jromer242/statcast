-- Sanity check on wall_distance_at_spray_ft. A home run that cleared the fence should
-- land beyond the interpolated wall. On 2024-26 under 1% land short (by at most 18 ft:
-- tracking error, and walls that bend between the measured points). Fails when more
-- than 3% of a season's over-the-fence home runs land short, which means the
-- interpolation broke: swapped left/right, a wrong gap angle, or bad park dimensions.
--
-- dbt singular test: any row this query returns is a failure.

select
    season,
    count(*)                                            as over_fence_hrs,
    avg(case when distance_past_wall_ft < 0 then 1.0 else 0.0 end) as share_short_of_wall
from {{ ref('fct_batted_balls') }}
where is_over_fence_hr
  and distance_past_wall_ft is not null
group by season
having avg(case when distance_past_wall_ft < 0 then 1.0 else 0.0 end) > 0.03
