"""Pull measured park dimensions (fence distances and wall heights) from Baseball Savant
as raw JSON, one snapshot per season.

Examples:
    python scripts/ingest_park_dimensions.py                          # current season
    python scripts/ingest_park_dimensions.py --season 2024 2025 2026  # backfill (2015+)

Source: the "dimensions" view of Savant's park factors leaderboard. The page has no JSON
endpoint; the data sits in the HTML as `var data = [...]`, which this script extracts.
One request returns every MLB home park for the season. One-off neutral sites (Tokyo,
London, Williamsport...) aren't included. Output, overwritten each run:
    data/raw/savant/park_dimensions/season=2026/park_dimensions.jsonl

Distances are measured the same way in every park (lines, gaps, center), unlike the
posted wall signs from the Stats API. `*_diff` fields are the change from the previous season,
and `is_diff_configuration` flags parks whose walls moved (e.g. Camden Yards in 2025).
"""

import argparse
import datetime as dt
import json
import logging
import re
import sys
import time

import requests

from common import PROJECT_ROOT, USER_AGENT, setup_logging, write_jsonl

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "savant" / "park_dimensions"
URL = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
FIRST_SEASON = 2015  # Statcast tracking starts here; earlier seasons return no rows

log = logging.getLogger("ingest_park_dimensions")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, nargs="+", default=[dt.date.today().year],
                   help=f"one or more seasons, {FIRST_SEASON} or later (default: current year)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = p.parse_args(argv)
    early = [s for s in args.season if s < FIRST_SEASON]
    if early:
        p.error(f"Savant has no park dimensions before {FIRST_SEASON}: {early}")
    return args


def extract_data(html: str) -> list[dict]:
    """Return the `var data = [...]` array embedded in a Savant leaderboard page."""
    match = re.search(r"var data\s*=\s*", html)
    if match is None:
        raise ValueError("`var data =` not found; Savant may have changed the page layout")
    # raw_decode reads exactly one JSON value starting at that position and ignores the rest
    data, _ = json.JSONDecoder().raw_decode(html, match.end())
    return data


def fetch_season(session: requests.Session, season: int) -> list[dict]:
    log.info("Fetching park dimensions for %s", season)
    r = session.get(URL, params={"type": "dimensions", "year": season}, timeout=60)
    r.raise_for_status()
    rows = extract_data(r.text)

    other_seasons = {row.get("season_id") for row in rows} - {season}
    if other_seasons:
        raise ValueError(f"asked for {season} but got rows for {sorted(other_seasons)}")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging("ingest_park_dimensions", args.verbose)
    log.info("Run started: seasons %s", args.season)

    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for i, season in enumerate(args.season):
            if i:
                time.sleep(1)  # be polite between requests
            try:
                rows = fetch_season(session, season)
            except (requests.RequestException, ValueError):
                log.exception("Fetch failed for %s", season)
                return 1
            if not rows:
                log.warning("No park dimensions for %s (not published yet?)", season)
                continue
            path = write_jsonl(rows, RAW_DIR / f"season={season}" / "park_dimensions.jsonl")
            log.info("Wrote %s parks to %s", len(rows), path.relative_to(PROJECT_ROOT))

    log.info("Run finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
