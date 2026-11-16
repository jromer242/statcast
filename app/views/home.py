import streamlit as st

from data_access import batted_balls, batter_seasons

st.title("Statcast HR explorer")
st.write(
    "Home runs depend on the park as much as the swing. A 380 ft fly ball is a home run "
    "down the short right field porch at Yankee Stadium and an out to center at Comerica. "
    "This app puts a hitter's fly balls and line drives on any park's walls, and ranks "
    "hitters by season."
)

balls = batted_balls()
seasons = batter_seasons()
c1, c2, c3 = st.columns(3)
c1.metric("Fly balls and line drives", f"{len(balls):,}")
c2.metric("Hitter seasons", f"{len(seasons):,}")
c3.metric("Data through", balls["game_date"].max().strftime("%b %-d"), help=str(balls["game_date"].max().year))

st.subheader("How it's built")
st.markdown(
    """
- **Data:** Baseball Savant (Statcast pitches, park dimensions and factors) and the MLB
  Stats API (schedule, venues, players), 2024 to 2026.
- **Pipeline:** Python ingest scripts write raw files; dbt and DuckDB turn them into
  tested tables with enforced contracts; CI rebuilds and tests everything on each push.
- **This app** reads three small extracts dbt builds for it (`app_park_walls`,
  `app_batted_balls`, `app_batter_seasons`), so it doesn't need the 1.2 GB database.

Source and docs: [github.com/jromer242/statcast](https://github.com/jromer242/statcast)
"""
)
