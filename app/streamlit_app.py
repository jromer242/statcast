"""Statcast HR explorer: entry point. Run locally with `streamlit run app/streamlit_app.py`."""

import streamlit as st

st.set_page_config(page_title="Statcast HR explorer", page_icon="⚾", layout="wide")

pages = st.navigation([
    st.Page("views/home.py", title="About", icon=":material/info:", default=True),
    st.Page("views/spray.py", title="Spray vs park walls", icon=":material/sports_baseball:"),
    st.Page("views/leaderboards.py", title="Leaderboards", icon=":material/leaderboard:"),
])
pages.run()
