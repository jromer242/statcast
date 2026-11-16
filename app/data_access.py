"""Load the Parquet extracts in app/data/ (written by scripts/export_app_data.py).

Cached so each file is read once per server process, not on every widget change.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent / "data"


@st.cache_data
def park_walls() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "app_park_walls.parquet")


@st.cache_data
def batted_balls() -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "app_batted_balls.parquet")
    # Whole-degree angle to look up any park's wall in app_park_walls. Balls hooking past
    # a foul line use the line's value, as in the dbt macro.
    df["angle_deg"] = df["spray_angle_deg"].round().clip(-45, 45).astype(int)
    return df


@st.cache_data
def batter_seasons() -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / "app_batter_seasons.parquet")
