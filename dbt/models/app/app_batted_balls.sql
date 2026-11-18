-- Fly balls and line drives with a distance and a direction: the balls that can be home
-- runs, trimmed to the columns the app draws. Regular season and postseason.
-- For the Streamlit app (see _app__exposures.yml).

select
    b.pitch_id,
    b.batter_id,
    b.season,
    b.game_date,
    b.game_type,
    b.venue_id,
    b.batted_ball_type,
    b.launch_speed,
    b.launch_angle,
    b.hit_distance,
    {{ round_decimal('b.spray_angle_deg', 1) }}                             as spray_angle_deg,
    {{ round_decimal('b.hit_distance * sin(b.spray_angle_deg * acos(-1) / 180)', 1) }}  as x_ft,
    {{ round_decimal('b.hit_distance * cos(b.spray_angle_deg * acos(-1) / 180)', 1) }}  as y_ft,
    b.is_home_run,
    b.is_over_fence_hr,
    b.pa_event
from {{ ref('fct_batted_balls') }} b
where b.batted_ball_type in ('fly_ball', 'line_drive')
  and b.hit_distance is not null
  and b.spray_angle_deg is not null
