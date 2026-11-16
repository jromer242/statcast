"""Compare outfield fence distances from the two sources, live, park by park.

    python scripts/check_park_dimensions.py              # 2026, every park
    python scripts/check_park_dimensions.py --season 2025 --park daikin

Two sources publish fence distances:
  - Stats API  /api/v1/venues?hydrate=fieldInfo  -> leftLine, leftCenter, center, ...
    The posted signs on the wall: whole feet, sometimes years out of date.
  - Savant     /leaderboard/statcast-park-factors?type=dimensions
    Measured by Statcast each season, to fractions of a foot, plus wall heights.
The pipeline uses Savant (stg_savant__park_dimensions -> dim_venue_seasons ->
wall_at_angle). The Stats API's fieldInfo is ingested but only used for roof and turf.

If data/statcast.duckdb exists, the "ours" column shows what dim_venue_seasons holds,
so you can confirm the pipeline matches the live Savant numbers.
"""

import argparse
import sys

import duckdb
import requests

from common import PROJECT_ROOT, USER_AGENT, extract_savant_data

DB_PATH = PROJECT_ROOT / "data" / "statcast.duckdb"
POINTS = [  # (label, Stats API field, Savant field)
    ("LF line", "leftLine", "distance_lf_line"),
    ("LF gap", "leftCenter", "distance_lf_gap"),
    ("CF", "center", "distance_cf"),
    ("RF gap", "rightCenter", "distance_rf_gap"),
    ("RF line", "rightLine", "distance_rf_line"),
]


def savant_rows(session: requests.Session, season: int) -> list[dict]:
    r = session.get("https://baseballsavant.mlb.com/leaderboard/statcast-park-factors",
                    params={"type": "dimensions", "year": season}, timeout=60)
    r.raise_for_status()
    return extract_savant_data(r.text)


def statsapi_fields(session: requests.Session, season: int, venue_ids: list[int]) -> dict[int, dict]:
    r = session.get("https://statsapi.mlb.com/api/v1/venues",
                    params={"venueIds": ",".join(map(str, venue_ids)),
                            "hydrate": "fieldInfo", "season": season}, timeout=60)
    r.raise_for_status()
    return {v["id"]: v.get("fieldInfo", {}) for v in r.json().get("venues", [])}


def ours(season: int) -> dict[int, dict]:
    if not DB_PATH.exists():
        return {}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cols = ", ".join(f"{f}_ft as {f}" for _, _, f in POINTS)
    df = con.sql(f"select venue_id, {cols} from dim_venue_seasons where season = {season}").df()
    con.close()
    return {int(r.venue_id): r._asdict() for r in df.itertuples(index=False)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, default=2026)
    p.add_argument("--park", help="part of a park name, e.g. daikin (case-insensitive)")
    p.add_argument("--min-diff", type=float, default=0,
                   help="only print parks where Savant and the Stats API differ by at least this many feet")
    args = p.parse_args()

    with requests.Session() as s:
        s.headers["User-Agent"] = USER_AGENT
        savant = savant_rows(s, args.season)
        if args.park:
            savant = [r for r in savant if args.park.lower() in r["venue_name_short"].lower()]
        if not savant:
            print("No matching parks", file=sys.stderr)
            return 1
        api = statsapi_fields(s, args.season, [r["venue_id"] for r in savant])
    db = ours(args.season)

    for row in sorted(savant, key=lambda r: r["venue_name_short"]):
        vid = row["venue_id"]
        lines, worst = [], 0.0
        for label, api_key, sav_key in POINTS:
            posted, measured = api.get(vid, {}).get(api_key), row.get(sav_key)
            mine = db.get(vid, {}).get(sav_key)
            diff = measured - posted if posted is not None and measured is not None else None
            worst = max(worst, abs(diff or 0))
            lines.append(f"  {label:8} {posted if posted is not None else '-':>8} "
                         f"{measured:>9.1f} {(f'{diff:+.1f}' if diff is not None else '-'):>7} "
                         f"{(f'{mine:.1f}' if mine is not None else '-'):>8}")
        if worst < args.min_diff:
            continue
        print(f"\n{row['venue_name_short']} (venue_id {vid}, {args.season})")
        print(f"  {'':8} {'StatsAPI':>8} {'Savant':>9} {'diff':>7} {'ours':>8}")
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
