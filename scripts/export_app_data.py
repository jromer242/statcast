"""Export the dbt app_* models to Parquet in app/data/ for the Streamlit app.

The deployed app can't reach data/statcast.duckdb (1.2 GB, gitignored), so it reads
these small files instead (~5 MB, committed). Run after `dbt build` and commit the result:

    python scripts/export_app_data.py

Reads the dev database read-only, so it won't block or change it.
"""

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "statcast.duckdb"
OUT_DIR = PROJECT_ROOT / "app" / "data"

# The models declared in dbt/models/app/_app__exposures.yml.
TABLES = ["app_park_walls", "app_batted_balls", "app_batter_seasons"]


def main() -> int:
    if not DB_PATH.exists():
        print(f"{DB_PATH.relative_to(PROJECT_ROOT)} not found; run dbt build first", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    for table in TABLES:
        dest = OUT_DIR / f"{table}.parquet"
        rows = con.sql(f"select count(*) from {table}").fetchone()[0]
        con.sql(f"copy {table} to '{dest.as_posix()}' (format parquet, compression zstd)")
        print(f"{table}: {rows:,} rows, {dest.stat().st_size / 1e6:.1f} MB")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
