"""Load the raw files in data/raw/ into BigQuery, for the dbt `bq` target.

    export STATCAST_BQ_PROJECT=your-project-id
    python scripts/load_bigquery.py                         # all seven raw tables
    python scripts/load_bigquery.py --tables schedule_raw   # just some

This is the "EL" in ELT, the job a tool like Fivetran does: copy source data into the
warehouse untouched, and let dbt do every transformation. Each dbt source becomes one
table in the statcast_raw dataset, replaced on every run (WRITE_TRUNCATE), the same full
refresh the DuckDB target gets by reading the files directly.

The files are read with each source's own external_location from the dbt project (the
read_parquet / read_json call in models/staging/*/_*__sources.yml), so BigQuery gets
exactly the rows and columns DuckDB sees, including the hive `season` and `filename`
columns. DuckDB writes them to a temporary Parquet file, and a BigQuery load job reads
that. Load jobs are free; only storage and queries count against the free tier.

Signs in with your gcloud login: gcloud auth application-default login
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import duckdb
from dbt.cli.main import dbtRunner
from google.cloud import bigquery

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = PROJECT_ROOT / "dbt"
DATASET = "statcast_raw"  # must match `schema:` in the dbt source files
LOCATION = "US"           # must match `location:` of the bq target in dbt/profiles.yml


def source_locations() -> dict[str, str]:
    """{table name: the DuckDB expression that reads its raw files}, from dbt's parse."""
    result = dbtRunner().invoke(["parse", "--quiet", "--target", "dev",
                                 "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)])
    if not result.success:
        raise SystemExit(f"dbt parse failed: {result.exception}")
    return {s.name: s.config.get("external_location")
            for s in result.result.sources.values() if s.config.get("external_location")}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default=os.environ.get("STATCAST_BQ_PROJECT"),
                   help="Google Cloud project ID (default: $STATCAST_BQ_PROJECT)")
    p.add_argument("--tables", nargs="+", help="only these source tables (default: all)")
    args = p.parse_args()
    if not args.project:
        p.error("set STATCAST_BQ_PROJECT or pass --project")

    locations = source_locations()
    tables = args.tables or sorted(locations)
    unknown = set(tables) - set(locations)
    if unknown:
        p.error(f"not dbt sources: {sorted(unknown)}; choose from {sorted(locations)}")

    client = bigquery.Client(project=args.project, location=LOCATION)
    dataset = bigquery.Dataset(f"{args.project}.{DATASET}")
    dataset.location = LOCATION
    dataset.description = "Raw files from data/raw/, loaded by scripts/load_bigquery.py. dbt reads these as sources."
    client.create_dataset(dataset, exists_ok=True)

    # The source expressions use paths relative to dbt/, as dbt runs them.
    os.chdir(DBT_DIR)
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        for name in tables:
            path = Path(tmp) / f"{name}.parquet"
            raw = con.sql(f"select * from {locations[name]}")
            rows = con.sql(f"select count(*) from {locations[name]}").fetchone()[0]
            # pybaseball saves game_date with nanosecond precision, which BigQuery's Parquet
            # loader can't read as a time: it loads the raw INT64 instead. Microseconds is
            # BigQuery's precision, and DuckDB's default.
            nanos = [c for c, t in zip(raw.columns, raw.types) if str(t) == "TIMESTAMP_NS"]
            select = "select *" + (
                " replace (" + ", ".join(f'cast("{c}" as timestamp) as "{c}"' for c in nanos) + ")"
                if nanos else "")
            con.sql(f"copy ({select} from {locations[name]}) to '{path.as_posix()}' "
                    "(format parquet, compression zstd)")

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                # Read Parquet lists as ARRAY columns, not as a struct wrapping a list.
                parquet_options=bigquery.ParquetOptions.from_api_repr({"enableListInference": True}),
            )
            table_id = f"{args.project}.{DATASET}.{name}"
            with path.open("rb") as f:
                client.load_table_from_file(f, table_id, job_config=job_config).result()

            loaded = client.get_table(table_id).num_rows
            status = "ok" if loaded == rows else f"MISMATCH (DuckDB read {rows:,})"
            print(f"{name}: {loaded:,} rows, {path.stat().st_size / 1e6:.1f} MB  {status}")
            if loaded != rows:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
