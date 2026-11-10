"""Pull park factors and park environment from Baseball Savant as raw JSON, one snapshot
per season.

Examples:
    python scripts/ingest_park_factors.py                          # current season
    python scripts/ingest_park_factors.py --season 2015 2016 2017  # backfill

Two views of Savant's park factors leaderboard:

  Park factors (type=year): indexes where 100 = league average, for runs, hits, 1B, 2B,
  3B, HR, BB, SO, wOBA, hard-hit rate... Pulled for every combination of
      rolling window: 1 season, or 3 seasons ending with this one
      batter side:    All, L, R
  so 6 requests per season, all saved to one file:
      data/raw/savant/park_factors/season=2026/park_factors.jsonl

  Environment (type=distance, 2016+): how many extra feet a fly ball carries in each
  park, split into elevation, temperature, roof and other environment:
      data/raw/savant/park_environment/season=2026/park_environment.jsonl

Both are computed from that season's batted balls: they describe the past. A model
predicting season S must only use values from season S-1 or earlier (see the
dim_venue_seasons mart).
"""

import argparse
import datetime as dt
import logging
import sys
import time

import requests

from common import PROJECT_ROOT, USER_AGENT, extract_savant_data, setup_logging, write_jsonl

FACTORS_DIR = PROJECT_ROOT / "data" / "raw" / "savant" / "park_factors"
ENVIRONMENT_DIR = PROJECT_ROOT / "data" / "raw" / "savant" / "park_environment"
URL = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"

FIRST_SEASON = 2015              # park factors
FIRST_ENVIRONMENT_SEASON = 2016  # environment returns no rows for 2015
ROLLING_WINDOWS = (1, 3)
BAT_SIDES = ("", "L", "R")       # "" = all batters; Savant labels it "All"

log = logging.getLogger("ingest_park_factors")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, nargs="+", default=[dt.date.today().year],
                   help=f"one or more seasons, {FIRST_SEASON} or later (default: current year)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = p.parse_args(argv)
    early = [s for s in args.season if s < FIRST_SEASON]
    if early:
        p.error(f"Savant has no park factors before {FIRST_SEASON}: {early}")
    return args


def fetch(session: requests.Session, **params) -> list[dict]:
    time.sleep(1)  # be polite: this script makes several requests per season
    r = session.get(URL, params=params, timeout=60)
    r.raise_for_status()
    return extract_savant_data(r.text)


def fetch_factors(session: requests.Session, season: int) -> list[dict]:
    """All rolling-window x batter-side combinations for one season."""
    rows = []
    for rolling in ROLLING_WINDOWS:
        for bat_side in BAT_SIDES:
            batch = fetch(session, type="year", year=season, rolling=rolling, batSide=bat_side)
            # Savant labels each row with what it computed; check it matches what we asked
            # for, so a silently ignored parameter can't mislabel data.
            expected = (str(season), str(rolling), bat_side or "All")
            got = {(r["key_year"], r["key_num_years_rolling"], r["key_bat_side"]) for r in batch}
            if got - {expected}:
                raise ValueError(f"asked for {expected}, got {sorted(got)}")
            log.debug("%s rolling=%s batSide=%s: %s parks", season, rolling, bat_side or "All", len(batch))
            rows.extend(batch)
    return rows


def fetch_environment(session: requests.Session, season: int) -> list[dict]:
    rows = fetch(session, type="distance", year=season)
    other = {r["year"] for r in rows} - {str(season)}
    if other:
        raise ValueError(f"asked for {season}, got environment rows for {sorted(other)}")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging("ingest_park_factors", args.verbose)
    log.info("Run started: seasons %s", args.season)

    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for season in args.season:
            try:
                log.info("Fetching park factors for %s", season)
                factors = fetch_factors(session, season)
                environment = []
                if season >= FIRST_ENVIRONMENT_SEASON:
                    log.info("Fetching park environment for %s", season)
                    environment = fetch_environment(session, season)
            except (requests.RequestException, ValueError):
                log.exception("Fetch failed for %s", season)
                return 1

            if factors:
                path = write_jsonl(factors, FACTORS_DIR / f"season={season}" / "park_factors.jsonl")
                log.info("Wrote %s park factor rows to %s", len(factors), path.relative_to(PROJECT_ROOT))
            else:
                log.warning("No park factors for %s (not published yet?)", season)
            if environment:
                path = write_jsonl(environment, ENVIRONMENT_DIR / f"season={season}" / "park_environment.jsonl")
                log.info("Wrote %s environment rows to %s", len(environment), path.relative_to(PROJECT_ROOT))

    log.info("Run finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
