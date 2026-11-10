"""Pull the MLB schedule (regular season + postseason) from the MLB Stats API as raw JSON.

Examples:
    python scripts/ingest_schedule.py                          # current season
    python scripts/ingest_schedule.py --season 2024 2025 2026  # backfill

One request per season returns every game's current state (status, venue, reschedules),
so each run overwrites that season's file instead of appending:
    data/raw/mlb/schedule/season=2026/schedule.jsonl

Each line is one game object exactly as the API returned it, plus `_ingested_at`.
Refresh the current season daily (games get postponed, rescheduled, resumed);
finished seasons only need loading once.
"""

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "mlb" / "schedule"
LOG_DIR = PROJECT_ROOT / "logs"

BASE_URL = "https://statsapi.mlb.com/api/v1"
# R = regular season; F, D, L, W = wild card, division series, LCS, World Series.
# Matches the game types Statcast has pitches for.
GAME_TYPES = "R,F,D,L,W"

log = logging.getLogger("ingest_schedule")


def setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logfile = logging.FileHandler(LOG_DIR / "ingest_schedule.log")
    logfile.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(console)
    root.addHandler(logfile)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, nargs="+", default=[dt.date.today().year],
                   help="one or more seasons, e.g. 2024 2025 (default: current year)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def fetch_season(session: requests.Session, season: int) -> list[dict]:
    """Return every game in a season as a flat list (the API groups games by date)."""
    log.info("Fetching schedule for %s (gameType=%s)", season, GAME_TYPES)
    r = session.get(f"{BASE_URL}/schedule",
                    params={"sportId": 1, "season": season, "gameType": GAME_TYPES},
                    timeout=60)
    r.raise_for_status()
    body = r.json()
    games = [g for d in body.get("dates", []) for g in d["games"]]
    if len(games) != body.get("totalGames"):
        log.warning("Flattened %s games but API reported totalGames=%s", len(games), body.get("totalGames"))
    return games


def write_raw(games: list[dict], season: int) -> Path:
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    out_dir = RAW_DIR / f"season={season}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "schedule.jsonl"

    # Write to a temp file, then rename: a crash mid-write never leaves a half-written
    # file where dbt would read it. The rename replaces the old file in one step.
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for g in games:
            f.write(json.dumps({**g, "_ingested_at": ingested_at}) + "\n")
    tmp.replace(path)

    log.info("Wrote %s games to %s", f"{len(games):,}", path.relative_to(PROJECT_ROOT))
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    log.info("Run started: seasons %s", args.season)

    with requests.Session() as session:
        session.headers["User-Agent"] = "statcast-learning-project"
        for i, season in enumerate(args.season):
            if i:
                time.sleep(1)  # be polite between requests
            try:
                games = fetch_season(session, season)
            except requests.RequestException:
                log.exception("Fetch failed for %s", season)
                return 1
            if not games:
                log.warning("No games for %s (schedule not published yet?)", season)
                continue
            write_raw(games, season)

    log.info("Run finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
