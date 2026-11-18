"""Check that the BigQuery build matches the DuckDB build, model by model.

    export STATCAST_BQ_PROJECT=your-project-id
    python scripts/compare_warehouses.py                    # every model
    python scripts/compare_warehouses.py fct_batted_balls   # just some

Both warehouses run the same dbt models, so they should hold the same data. For each
model and column this compares a fingerprint computed inside each warehouse: the row
count, the non-null count, and for numbers and booleans the sum. Sums are compared with a
relative tolerance, since floating-point addition in a different order can differ in the
last digits. Any column that differs is printed; exit code 1 if anything does.

Fingerprints don't prove two tables are identical (two errors could cancel), but a
dropped row, a NULL handled differently, or a function that behaves differently almost
always shows up. Reads data/statcast.duckdb read-only.
"""

import argparse
import math
import os
import sys
from pathlib import Path

import duckdb
from google.cloud import bigquery

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "statcast.duckdb"
DATASET = "statcast"  # `dataset:` of the bq target in dbt/profiles.yml
MODELS = [
    "stg_savant__pitches", "stg_savant__park_dimensions", "stg_savant__park_factors",
    "stg_savant__park_environment", "stg_mlb__games", "stg_mlb__venues", "stg_mlb__players",
    "dim_venue_seasons", "dim_games", "dim_players", "fct_plate_appearances",
    "fct_batted_balls", "app_park_walls", "app_batted_balls", "app_batter_seasons",
]
# Lineage columns differ by design: file paths and load times.
SKIP_COLUMNS = {"_source_file", "_ingested_at"}
NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL")


def fingerprint_sql(table: str, columns: dict[str, str], bigquery_dialect: bool) -> str:
    """One row: n, then nonnull__<col> and sum__<col> for each column."""
    parts = ["count(*) as n"]
    for col, dtype in columns.items():
        q = f"`{col}`" if bigquery_dialect else f'"{col}"'
        parts.append(f"count({q}) as nonnull__{col}")
        if dtype.startswith(NUMERIC):
            parts.append(f"sum(cast({q} as {'float64' if bigquery_dialect else 'double'})) as sum__{col}")
        elif dtype == "BOOLEAN":
            parts.append(f"countif({q}) as sum__{col}" if bigquery_dialect
                         else f"count(*) filter (where {q}) as sum__{col}")
    return f"select {', '.join(parts)} from {table}"


def same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("models", nargs="*", default=MODELS)
    p.add_argument("--project", default=os.environ.get("STATCAST_BQ_PROJECT"))
    args = p.parse_args()
    if not args.project:
        p.error("set STATCAST_BQ_PROJECT or pass --project")

    duck = duckdb.connect(str(DB_PATH), read_only=True)
    bq = bigquery.Client(project=args.project)
    failures = 0
    for model in args.models:
        columns = {c: t for c, t in duck.sql(
            "select column_name, data_type from information_schema.columns "
            f"where table_name = '{model}' order by ordinal_position").fetchall()
            if c not in SKIP_COLUMNS}
        rel = duck.sql(fingerprint_sql(model, columns, False))
        d = dict(zip(rel.columns, rel.fetchone()))
        b = dict(next(iter(bq.query(fingerprint_sql(
            f"`{args.project}.{DATASET}.{model}`", columns, True)).result())))
        diffs = [(k, d[k], b[k]) for k in d if not same(d[k], b[k])]
        failures += bool(diffs)
        print(f"{model}: {int(d['n']):,} rows, {len(columns)} columns  "
              f"{'MATCH' if not diffs else f'{len(diffs)} DIFFERENCES'}")
        for k, dv, bv in diffs:
            print(f"    {k}: duckdb={dv}  bigquery={bv}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
