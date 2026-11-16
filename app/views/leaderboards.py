import altair as alt
import streamlit as st

from data_access import batter_seasons

st.title("Leaderboards")
st.caption("Regular season. Rate stats use completed plate appearances.")

df = batter_seasons()

c1, c2, c3 = st.columns([1, 1, 2])
season = c1.selectbox("Season", sorted(df["season"].unique(), reverse=True))
min_pa = c2.number_input("Minimum PA", min_value=0, max_value=700, value=300, step=50)
stat_labels = {
    "hr": "Home runs",
    "hr_per_pa": "HR per PA",
    "woba": "wOBA",
    "slugging": "Slugging",
    "avg_exit_velo": "Avg exit velocity",
    "hard_hit_rate": "Hard-hit rate",
    "pulled_fly_ball_rate": "Pulled fly ball rate",
    "longest_hr_ft": "Longest HR",
}
sort_by = c3.selectbox("Sort by", list(stat_labels), format_func=stat_labels.get)

board = (
    df[(df["season"] == season) & (df["pa"] >= min_pa)]
    .sort_values(sort_by, ascending=False)
    .reset_index(drop=True)
)
board.index += 1

st.dataframe(
    board[["batter_name", "team", "bats", "pa", "hr", "hr_per_pa", "batting_avg", "slugging",
           "woba", "strikeout_rate", "walk_rate", "avg_exit_velo", "hard_hit_rate",
           "pulled_fly_ball_rate", "longest_hr_ft"]],
    column_config={
        "batter_name": "Batter",
        "team": "Team",
        "bats": "Bats",
        "pa": "PA",
        "hr": "HR",
        "hr_per_pa": st.column_config.NumberColumn("HR/PA", format="%.3f"),
        "batting_avg": st.column_config.NumberColumn("AVG", format="%.3f"),
        "slugging": st.column_config.NumberColumn("SLG", format="%.3f"),
        "woba": st.column_config.NumberColumn("wOBA", format="%.3f"),
        "strikeout_rate": st.column_config.NumberColumn("K%", format="percent"),
        "walk_rate": st.column_config.NumberColumn("BB%", format="percent"),
        "avg_exit_velo": st.column_config.NumberColumn("Avg EV", format="%.1f"),
        "hard_hit_rate": st.column_config.NumberColumn("Hard-hit %", format="percent"),
        "pulled_fly_ball_rate": st.column_config.NumberColumn("Pulled FB %", format="percent"),
        "longest_hr_ft": st.column_config.NumberColumn("Longest HR (ft)", format="%d"),
    },
    height=420,
)

st.subheader("What goes with home runs?")
st.caption("Each dot is a hitter with the minimum PA. Hover for names.")
x_stat = st.selectbox(
    "Compare HR per PA with",
    ["pulled_fly_ball_rate", "hard_hit_rate", "avg_exit_velo", "strikeout_rate"],
    format_func=lambda s: {**stat_labels, "strikeout_rate": "Strikeout rate"}[s],
)
chart = (
    alt.Chart(board)
    .mark_circle(size=60, opacity=0.7)
    .encode(
        x=alt.X(x_stat, title={**stat_labels, "strikeout_rate": "Strikeout rate"}[x_stat],
                scale=alt.Scale(zero=False)),
        y=alt.Y("hr_per_pa", title="HR per PA"),
        tooltip=["batter_name", "team", "hr", alt.Tooltip("hr_per_pa", format=".3f"),
                 alt.Tooltip(x_stat, format=".3f")],
    )
    .properties(height=380)
)
st.altair_chart(chart, width="stretch")
