"""Pull every player who appeared in MLB in a season from the MLB Stats API as raw JSON,
one snapshot per season.

Examples:
    python scripts/ingest_players.py                          # current season
    python scripts/ingest_players.py --season 2024 2025 2026  # backfill

One request per season (/sports/1/players?season=YYYY, ~1,500 players). Output,
overwritten each run:
    data/raw/mlb/players/season=2026/players.jsonl

Biographical fields (name, birth date, bats, throws, debut) rarely change, but height,
weight and listed position can, so each season is kept as its own snapshot keyed by
(player_id, season). Fields like currentTeam, currentAge and active describe the player
on the day of the pull, not in that season; staging drops them.
"""

import argparse
import datetime as dt
import logging
import sys
import time

import requests

from common import PROJECT_ROOT, USER_AGENT, setup_logging, write_jsonl

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "mlb" / "players"
BASE_URL = "https://statsapi.mlb.com/api/v1"
SPORT_ID_MLB = 1

log = logging.getLogger("ingest_players")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, nargs="+", default=[dt.date.today().year],
                   help="one or more seasons, e.g. 2024 2025 (default: current year)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def fetch_players(session: requests.Session, season: int) -> list[dict]:
    log.info("Fetching MLB players for %s", season)
    r = session.get(f"{BASE_URL}/sports/{SPORT_ID_MLB}/players",
                    params={"season": season}, timeout=60)
    r.raise_for_status()
    return r.json().get("people", [])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging("ingest_players", args.verbose)
    log.info("Run started: seasons %s", args.season)

    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for i, season in enumerate(args.season):
            if i:
                time.sleep(1)  # be polite between requests
            try:
                players = fetch_players(session, season)
            except requests.RequestException:
                log.exception("Fetch failed for %s", season)
                return 1
            if not players:
                log.error("API returned no players for %s", season)
                return 1
            path = write_jsonl(players, RAW_DIR / f"season={season}" / "players.jsonl")
            log.info("Wrote %s players to %s", len(players), path.relative_to(PROJECT_ROOT))

    log.info("Run finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
