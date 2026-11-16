"""Cut a small, committed sample of data/raw/ into ci/fixtures/raw/ for CI.

CI can't run the ingest scripts (slow, and it would hit Savant and the MLB API on every
push), and data/raw/ is ~340 MB and gitignored. So CI runs `dbt build` against this
sample instead: the same folder layout and file formats, a few games per season.

What's in the sample, and why:
- Statcast pitches and schedule rows for a handful of games per season, chosen so the
  edge cases staging handles are present: a postponed game (two schedule rows for one
  game_pk), a suspended-and-resumed game, a rescheduled game, a neutral site with no
  measured dimensions, and a postseason game. The rest are regular-season games picked
  by a fixed hash of game_pk, so the sample is the same on every run.
- Venues, park dimensions, park factors and park environment in full (~2 MB). They're
  small, and dim_venue_seasons needs earlier seasons for its prior-season factors.

Re-run after changing a raw format or staging a new raw column:
    python scripts/make_ci_fixtures.py
"""

import argparse
import shutil
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
OUT = PROJECT_ROOT / "ci" / "fixtures" / "raw"

# Copied whole: small, and needed for every season's park lookups.
FULL_COPY = [
    "mlb/venues",
    "savant/park_dimensions",
    "savant/park_factors",
    "savant/park_environment",
]

SCHEDULE_GLOB = (RAW / "mlb/schedule/**/*.jsonl").as_posix()
STATCAST_GLOB = (RAW / "statcast/**/*.parquet").as_posix()


def pick_games(con: duckdb.DuckDBPyConnection, regular_per_season: int) -> list[int]:
    """Return the game_pks to keep: edge cases first, then hash-picked regular games."""
    con.sql(f"""
        create or replace temp table schedule as
        select *, cast(season as integer) as season_int
        from read_json('{SCHEDULE_GLOB}', format = 'newline_delimited',
                       hive_partitioning = true, union_by_name = true, sample_size = -1)
    """)
    con.sql(f"""
        create or replace temp table park_dimensions as
        select cast(venue_id as integer) as venue_id, cast(season_id as integer) as season_id
        from read_json('{(RAW / "savant/park_dimensions/**/*.jsonl").as_posix()}',
                       format = 'newline_delimited', union_by_name = true)
    """)
    # Games Statcast has pitches for (spring training etc. aren't in the schedule pull).
    con.sql(f"""
        create or replace temp table statcast_games as
        select distinct game_pk
        from read_parquet('{STATCAST_GLOB}', union_by_name = true)
    """)
    picked = con.sql(f"""
        with played as (
            select s.*
            from schedule s
            join statcast_games g on g.game_pk = s.gamePk
        ),
        edge_cases as (
            -- one of each per season; min(gamePk) keeps the choice stable
            select season_int, 'postponed' as why, min(gamePk) as game_pk
            from played
            where gamePk in (select gamePk from schedule
                             where status.detailedState = 'Postponed')
            group by season_int
            union all
            select season_int, 'resumed', min(gamePk)
            from played where resumedFrom is not null group by season_int
            union all
            select season_int, 'rescheduled', min(gamePk)
            from played where rescheduledFrom is not null group by season_int
            union all
            select season_int, 'postseason', min(gamePk)
            from played where gameType in ('F', 'D', 'L', 'W') group by season_int
            union all
            -- a neutral site: no measured dimensions that season, so wall columns are null
            select season_int, 'neutral_site', min(gamePk)
            from played p
            where not exists (
                select 1 from park_dimensions d
                where d.venue_id = p.venue.id and d.season_id = p.season_int)
            group by season_int
        ),
        regular as (
            select season_int, 'regular' as why, gamePk as game_pk
            from played
            where gameType = 'R' and status.detailedState = 'Final'
            qualify row_number() over (
                partition by season_int order by hash(gamePk)) <= {regular_per_season}
        )
        select distinct game_pk from (
            select * from edge_cases union all select * from regular)
        order by game_pk
    """).fetchall()
    return [row[0] for row in picked]


def write_schedule(con: duckdb.DuckDBPyConnection, game_pks: list[int]) -> None:
    """Every schedule row for the picked games, one season file each, columns unchanged."""
    for season_dir in sorted((RAW / "mlb/schedule").glob("season=*")):
        src = (season_dir / "schedule.jsonl").as_posix()
        dest = OUT / "mlb/schedule" / season_dir.name / "schedule.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Filter line by line on the raw text so each kept line is byte-for-byte what the
        # API returned (no re-serialization that could change types or key order).
        keep = set(game_pks)
        with open(src) as f_in, open(dest, "w") as f_out:
            for line in f_in:
                # gamePk is the first key in every line: {"gamePk": 778563, ...
                pk = int(line.split(",", 1)[0].split(":", 1)[1])
                if pk in keep:
                    f_out.write(line)


def write_statcast(con: duckdb.DuckDBPyConnection, game_pks: list[int]) -> None:
    """Pitches for the picked games, one Parquet file per season, raw schema unchanged."""
    con.sql("create or replace temp table keep as select unnest($pks) as game_pk",
            params={"pks": game_pks})
    for season_dir in sorted((RAW / "statcast").glob("season=*")):
        dest = OUT / "statcast" / season_dir.name / "statcast_ci_sample.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = (season_dir / "*.parquet").as_posix()
        # No hive_partitioning here, so `season` isn't added as a column: dbt adds it
        # back from the folder name, exactly as it does for the real files.
        con.sql(f"""
            copy (
                select * from read_parquet('{src}', union_by_name = true)
                where game_pk in (select game_pk from keep)
                order by game_pk, at_bat_number, pitch_number
            ) to '{dest.as_posix()}' (format parquet, compression zstd)
        """)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regular-per-season", type=int, default=10,
                        help="hash-picked regular-season games per season (default 10)")
    args = parser.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)

    con = duckdb.connect()
    game_pks = pick_games(con, args.regular_per_season)
    write_schedule(con, game_pks)
    write_statcast(con, game_pks)
    for rel in FULL_COPY:
        shutil.copytree(RAW / rel, OUT / rel)

    size_mb = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1e6
    print(f"{len(game_pks)} games, {size_mb:.1f} MB written to {OUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
