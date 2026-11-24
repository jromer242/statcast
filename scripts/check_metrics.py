"""Check the semantic layer's metrics against SQL written by hand.

    python scripts/check_metrics.py                 # MetricFlow on DuckDB
    python scripts/check_metrics.py --target bq     # MetricFlow on BigQuery

Queries every public metric through MetricFlow (`mf query`) by team, season and
regular season/postseason, computes the same numbers straight from the DuckDB marts
with independent SQL, and compares them. A metric definition that drifts from what it
claims to measure (a filter missed, a ratio built from the wrong parts) fails here.
With --target bq the metrics run on BigQuery, so it also checks that they compile to
the same answers on both warehouses.

Build the dev target first (cd dbt && dbt build); for bq, also the bq target and
STATCAST_BQ_PROJECT (see the BigQuery section of dbt/README.md).
"""

import argparse
import csv
import os
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = PROJECT_ROOT / "dbt"
DATABASE = PROJECT_ROOT / "data" / "statcast.duckdb"
MF = Path(sys.executable).with_name("mf")
DBT = Path(sys.executable).with_name("dbt")

# Plate appearances, by batting team. Hand-written from pa_event rather than the is_*
# flags the metrics use, so a wrong flag shows up too. Aggregates first (n_*), then
# every metric from them.
PA_AGGREGATES = {
    "n_pa": "count(*) filter (where pa_event <> 'truncated_pa')",
    "n_ab": """count(*) filter (where pa_event not in ('truncated_pa', 'walk', 'intent_walk',
        'hit_by_pitch', 'catcher_interf', 'sac_fly', 'sac_fly_double_play', 'sac_bunt',
        'sac_bunt_double_play'))""",
    "n_h": "count(*) filter (where pa_event in ('single', 'double', 'triple', 'home_run'))",
    "n_2b": "count(*) filter (where pa_event = 'double')",
    "n_3b": "count(*) filter (where pa_event = 'triple')",
    "n_hr": "count(*) filter (where pa_event = 'home_run')",
    "n_bb": "count(*) filter (where pa_event in ('walk', 'intent_walk'))",
    "n_k": "count(*) filter (where pa_event in ('strikeout', 'strikeout_double_play'))",
    "n_hbp": "count(*) filter (where pa_event = 'hit_by_pitch')",
    "n_sf": "count(*) filter (where pa_event in ('sac_fly', 'sac_fly_double_play'))",
    "n_tb": """sum(case pa_event when 'single' then 1 when 'double' then 2
        when 'triple' then 3 when 'home_run' then 4 else 0 end)""",
    "n_rv": "sum(run_value)",
    "n_woba": "sum(woba_value)",
    "n_woba_denom": "sum(woba_denom)",
}
OBP = "(n_h + n_bb + n_hbp) / (n_ab + n_bb + n_hbp + n_sf)"
PA_METRICS = {
    "plate_appearances": "n_pa",
    "at_bats": "n_ab",
    "hits": "n_h",
    "doubles": "n_2b",
    "triples": "n_3b",
    "home_runs": "n_hr",
    "walks": "n_bb",
    "strikeouts": "n_k",
    "hit_by_pitch": "n_hbp",
    "sacrifice_flies": "n_sf",
    "total_bases": "n_tb",
    "run_value": "n_rv",
    "batting_average": "n_h / n_ab",
    "on_base_percentage": OBP,
    "slugging_percentage": "n_tb / n_ab",
    "ops": f"{OBP} + n_tb / n_ab",
    "isolated_power": "(n_tb - n_h) / n_ab",
    "woba": "n_woba / n_woba_denom",
    "home_run_rate": "n_hr / n_pa",
    "strikeout_rate": "n_k / n_pa",
    "walk_rate": "n_bb / n_pa",
    "at_bats_per_home_run": "n_ab / nullif(n_hr, 0)",
}

# Batted balls, by batter side.
TRACKED = "launch_speed is not null and launch_angle is not null"
BB_AGGREGATES = {
    "n_bbe": f"count(*) filter (where {TRACKED})",
    "n_hard": f"count(*) filter (where {TRACKED} and launch_speed >= 95)",
    "n_sweet": f"count(*) filter (where {TRACKED} and launch_angle between 8 and 32)",
    "avg_ev": f"avg(launch_speed) filter (where {TRACKED})",
    "max_ev": f"max(launch_speed) filter (where {TRACKED})",
    "avg_la": f"avg(launch_angle) filter (where {TRACKED})",
    "avg_bat": "avg(bat_speed)",
    "avg_hr_dist": "avg(hit_distance) filter (where pa_event = 'home_run')",
    "avg_hr_clear": "avg(distance_past_wall_ft) filter (where is_over_fence_hr)",
}
BB_METRICS = {
    "batted_balls": "n_bbe",
    "avg_exit_velocity": "avg_ev",
    "max_exit_velocity": "max_ev",
    "avg_launch_angle": "avg_la",
    "avg_bat_speed": "avg_bat",
    "hard_hit_rate": "n_hard / n_bbe",
    "sweet_spot_rate": "n_sweet / n_bbe",
    "avg_home_run_distance": "avg_hr_dist",
    "avg_home_run_clearance": "avg_hr_clear",
}

PHASE = "case when game_type = 'R' then 'regular' else 'postseason' end"

CHECKS = [
    # (semantic model entity, mart, extra group by (mf name, SQL), aggregates, metrics)
    ("plate_appearance", "fct_plate_appearances", ("plate_appearance__batting_team", "batting_team"),
     PA_AGGREGATES, PA_METRICS),
    ("batted_ball", "fct_batted_balls", ("batted_ball__batter_stand", "batter_stand"),
     BB_AGGREGATES, BB_METRICS),
]


def hand_sql(mart: str, group_sql: str, aggregates: dict[str, str], metrics: dict[str, str]) -> str:
    aggs = ",\n  ".join(f"{expr} as {name}" for name, expr in aggregates.items())
    cols = ",\n  ".join(f"{expr} as {name}" for name, expr in metrics.items())
    return f"""
        with totals as (
            select season, {PHASE} as season_phase, {group_sql} as grp,
              {aggs}
            from main.{mart}
            group by 1, 2, 3
        )
        select season, season_phase, grp,
          {cols}
        from totals
    """


def dbt_parse(target: str) -> None:
    """Write the semantic manifest for a target: it holds each target's table names."""
    subprocess.run([str(DBT), "parse", "--quiet", "--target", target],
                   cwd=DBT_DIR, check=True)


def mf_query(target: str, entity: str, group_by: str, metrics: list[str], out: Path) -> list[dict]:
    group = [f"{entity}__season", f"{entity}__season_phase", group_by]
    subprocess.run(
        [str(MF), "query", "--metrics", ",".join(metrics), "--group-by", ",".join(group),
         "--csv", str(out), "--quiet"],
        # mf has no --target; dbt/profiles.yml takes its default target from DBT_TARGET.
        cwd=DBT_DIR, check=True, capture_output=True, text=True,
        env={**os.environ, "DBT_TARGET": target})
    with out.open() as f:
        return list(csv.DictReader(f))


def close(a, b) -> bool:
    if a in (None, "") or b is None:
        return a in (None, "") and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default="dev", choices=["dev", "bq"],
                   help="where MetricFlow runs the metrics (the hand-written SQL always reads DuckDB)")
    args = p.parse_args()

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        results = []
        # MetricFlow first: on DuckDB it opens the database for writing, and DuckDB
        # allows one writer or many readers, not both.
        dbt_parse(args.target)
        try:
            for entity, mart, (mf_group, sql_group), aggregates, metrics in CHECKS:
                rows = mf_query(args.target, entity, mf_group, list(metrics), Path(tmp) / f"{mart}.csv")
                results.append((entity, mart, mf_group, sql_group, aggregates, metrics, rows))
        finally:
            if args.target != "dev":
                dbt_parse("dev")  # leave dbt/target/ as plain `mf` and `dbt` expect it

        con = duckdb.connect(str(DATABASE), read_only=True)
        for entity, mart, mf_group, sql_group, aggregates, metrics, rows in results:
            expected = {
                (r["season"], r["season_phase"], r["grp"]): r
                for r in con.sql(hand_sql(mart, sql_group, aggregates, metrics)).df()
                .astype(object).where(lambda d: d.notna(), None).to_dict("records")
            }
            got = {(int(r[f"{entity}__season"]), r[f"{entity}__season_phase"], r[mf_group]): r
                   for r in rows}
            if set(got) != set(expected):
                print(f"{mart}: different groups, {len(got)} from MetricFlow vs {len(expected)} by hand")
                failures += 1
                continue
            for name in metrics:
                bad = [k for k in expected if not close(got[k][name], expected[k][name])]
                status = "ok" if not bad else f"MISMATCH in {len(bad)} groups, e.g. {bad[0]}: " \
                    f"{got[bad[0]][name]} vs {expected[bad[0]][name]}"
                failures += bool(bad)
                print(f"{mart:22} {name:24} {len(expected):>4} groups  {status}")
    print("all metrics match" if not failures else f"{failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
