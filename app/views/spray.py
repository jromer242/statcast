import altair as alt
import pandas as pd
import streamlit as st

from data_access import batted_balls, batter_seasons, park_walls

st.title("Spray vs park walls")
st.caption(
    "A hitter's regular-season fly balls and line drives, drawn on any park's walls. A ball 'clears' a "
    "park when its distance beats that park's wall distance in the direction it went. "
    "Rough on purpose: it ignores wall height and how far balls carry in each park. "
    "The park-fit model (notebook 07) does that properly."
)

balls = batted_balls()
walls = park_walls()
seasons = batter_seasons()

c1, c2, c3 = st.columns([1, 2, 2])
season = c1.selectbox("Season", sorted(balls["season"].unique(), reverse=True))

hitters = seasons[(seasons["season"] == season) & (seasons["batted_balls"] >= 100)]
hitters = hitters.sort_values("hr", ascending=False)
# Label -> id. Plain string options keep the widget simple (and testable).
labels = dict(zip(hitters["batter_name"] + " (" + hitters["team"] + ")", hitters["batter_id"]))
default_label = next((lbl for lbl in labels if lbl.startswith("Jazz Chisholm")), next(iter(labels)))
batter_id = labels[c2.selectbox("Hitter", list(labels), index=list(labels).index(default_label))]

season_walls = walls[walls["season"] == season]
park_names = sorted(season_walls["venue_name"].unique())
default_park = "Yankee Stadium" if "Yankee Stadium" in park_names else park_names[0]
park = c3.selectbox("Draw on park", park_names, index=park_names.index(default_park))

# Regular season, to match the leaderboards and official season totals.
hitter_balls = balls[(balls["batter_id"] == batter_id) & (balls["season"] == season)
                     & (balls["game_type"] == "R")]
outline = season_walls[season_walls["venue_name"] == park].sort_values("angle_deg")

# Would each ball clear this park's wall? Look up the wall at the ball's angle.
scored = hitter_balls.merge(
    outline[["angle_deg", "wall_distance_ft"]], on="angle_deg", how="left"
)
scored["clears"] = scored["hit_distance"] > scored["wall_distance_ft"]
scored["clears_label"] = scored["clears"].map({True: "Clears", False: "Short"})
scored["actual_label"] = scored["is_over_fence_hr"].map({True: "Home run", False: "Not a HR"})
scored["result"] = scored.apply(
    lambda r: ("Home run" if r["is_over_fence_hr"] else "Out or hit") + " · "
    + ("clears " + park if r["clears"] else "short of " + park),
    axis=1,
)

m1, m2, m3 = st.columns(3)
m1.metric("Actual over-the-fence HR", int(hitter_balls["is_over_fence_hr"].sum()))
m2.metric(f"Would clear {park}", int(scored["clears"].sum()),
          delta=int(scored["clears"].sum() - hitter_balls["is_over_fence_hr"].sum()))
m3.metric("Fly balls and line drives", len(hitter_balls))

# Field: wall outline plus foul lines. Width and height are in the same ratio as the
# x and y domains, so a foot is the same length both ways and the park isn't stretched.
lim = 480
plot_height = 520
foul_lines = pd.DataFrame({
    "x_ft": [outline["x_ft"].iloc[0], 0, outline["x_ft"].iloc[-1]],
    "y_ft": [outline["y_ft"].iloc[0], 0, outline["y_ft"].iloc[-1]],
    "order": [0, 1, 2],
})
x_scale = alt.Scale(domain=[-lim * 0.75, lim * 0.75])
y_scale = alt.Scale(domain=[0, lim])

wall_line = alt.Chart(outline).mark_line(strokeWidth=3, color="#2f6f3e").encode(
    x=alt.X("x_ft", scale=x_scale, title="Feet (left field ← → right field)"),
    y=alt.Y("y_ft", scale=y_scale, title="Feet from home plate"),
    order="angle_deg",
    tooltip=[alt.Tooltip("angle_deg", title="Angle"),
             alt.Tooltip("wall_distance_ft", title="Wall (ft)"),
             alt.Tooltip("wall_height_ft", title="Height (ft)")],
)
foul = alt.Chart(foul_lines).mark_line(color="#999999", strokeDash=[4, 4]).encode(
    x=alt.X("x_ft", scale=x_scale), y=alt.Y("y_ft", scale=y_scale), order="order"
)
dots = alt.Chart(scored).mark_point(filled=True, size=55, opacity=0.8).encode(
    x=alt.X("x_ft", scale=x_scale),
    y=alt.Y("y_ft", scale=y_scale),
    color=alt.Color("clears_label:N", title=park,
                    scale=alt.Scale(domain=["Clears", "Short"], range=["#d1495b", "#8a8f98"])),
    shape=alt.Shape("actual_label:N", title="Where it was hit",
                    scale=alt.Scale(domain=["Home run", "Not a HR"], range=["diamond", "circle"]),
                    legend=alt.Legend(symbolFillColor="#8a8f98", symbolStrokeColor="#8a8f98")),
    tooltip=[alt.Tooltip("game_date", title="Date"),
             alt.Tooltip("pa_event", title="Result"),
             alt.Tooltip("hit_distance", title="Distance (ft)"),
             alt.Tooltip("launch_speed", title="Exit velo"),
             alt.Tooltip("launch_angle", title="Launch angle"),
             alt.Tooltip("wall_distance_ft", title=f"{park} wall (ft)")],
)
field = (
    (wall_line + foul + dots)
    .properties(width=plot_height * 1.5, height=plot_height)
    .configure_legend(orient="bottom", direction="horizontal")
)
st.altair_chart(field, width="content")

# The same balls in every park: a rough preview of park fit.
st.subheader(f"Which park fits this hitter best? ({season})")
st.caption("Count of this hitter's balls that would clear each park's wall, same rough rule.")
all_parks = hitter_balls.merge(
    season_walls[["venue_name", "angle_deg", "wall_distance_ft"]], on="angle_deg"
)
fit = (
    all_parks.assign(clears=all_parks["hit_distance"] > all_parks["wall_distance_ft"])
    .groupby("venue_name", as_index=False)["clears"].sum()
    .rename(columns={"clears": "would_clear"})
    .sort_values("would_clear", ascending=False)
)
bars = alt.Chart(fit).mark_bar().encode(
    x=alt.X("would_clear:Q", title="Balls that would clear"),
    y=alt.Y("venue_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
    color=alt.condition(alt.datum.venue_name == park, alt.value("#d1495b"), alt.value("#5b7fa6")),
    tooltip=["venue_name", "would_clear"],
)
st.altair_chart(bars.properties(height=24 * len(fit)), width="stretch")
