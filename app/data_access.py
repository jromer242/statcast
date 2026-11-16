"""Load the Parquet extracts in app/data/ (written by scripts/export_app_data.py).

Cached so each file is read once per server process, not on every widget change. The
cache key includes the file's modification time: st.cache_data only watches a function's
code and arguments, so without it a running app (like the deployed one, which pulls new
commits without restarting) would keep serving the old data after a refresh.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent / "data"


@st.cache_data
def _read(name: str, modified_ns: int) -> pd.DataFrame:
    # modified_ns isn't used here; it's part of the cache key.
    return pd.read_parquet(DATA_DIR / f"{name}.parquet")


def _load(name: str) -> pd.DataFrame:
    path = DATA_DIR / f"{name}.parquet"
    return _read(name, path.stat().st_mtime_ns)


def park_walls() -> pd.DataFrame:
    return _load("app_park_walls")


def batted_balls() -> pd.DataFrame:
    df = _load("app_batted_balls").copy()
    # Whole-degree angle to look up any park's wall in app_park_walls. Balls hooking past
    # a foul line use the line's value, as in the dbt macro.
    df["angle_deg"] = df["spray_angle_deg"].round().clip(-45, 45).astype(int)
    return df


def batter_seasons() -> pd.DataFrame:
    return _load("app_batter_seasons")
