"""Pull MLB venue details (location, elevation, orientation, posted dimensions) from the
MLB Stats API as raw JSON, one snapshot per season.

Examples:
    python scripts/ingest_venues.py                          # current season
    python scripts/ingest_venues.py --season 2024 2025 2026  # backfill

Venue IDs come from that season's raw schedule file, so run ingest_schedule.py first.
Every venue that hosted a game is included, neutral sites too (Tokyo Dome, Bristol...).
Output, overwritten each run:
    data/raw/mlb/venues/season=2026/venues.jsonl

Venues change between seasons (walls moved, capacity, renamed parks), so each season
is its own snapshot keyed by (venue_id, season): a slowly changing dimension.
Measured distances and wall heights come from Savant instead: ingest_park_dimensions.py.
"""

import argparse
import datetime as dt
import json
import logging
import sys
import time

import requests

from common import PROJECT_ROOT, USER_AGENT, setup_logging, write_jsonl

SCHEDULE_DIR = PROJECT_ROOT / "data" / "raw" / "mlb" / "schedule"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "mlb" / "venues"

BASE_URL = "https://statsapi.mlb.com/api/v1"
# Without hydrate, the API returns only id, name and link.
HYDRATE = "fieldInfo,location,timezone"

log = logging.getLogger("ingest_venues")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", type=int, nargs="+", default=[dt.date.today().year],
                   help="one or more seasons, e.g. 2024 2025 (default: current year)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def venue_ids_from_schedule(season: int) -> list[int]:
    """Distinct venue IDs in a season's raw schedule file."""
    path = SCHEDULE_DIR / f"season={season}" / "schedule.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(PROJECT_ROOT)} not found; "
                                f"run: python scripts/ingest_schedule.py --season {season}")
    with path.open() as f:
        return sorted({json.loads(line)["venue"]["id"] for line in f})


def fetch_venues(session: requests.Session, season: int, venue_ids: list[int]) -> list[dict]:
    log.info("Fetching %s venues for %s", len(venue_ids), season)
    r = session.get(f"{BASE_URL}/venues",
                    params={"venueIds": ",".join(map(str, venue_ids)),
                            "hydrate": HYDRATE,
                            "season": season},
                    timeout=60)
    r.raise_for_status()
    venues = r.json().get("venues", [])

    missing = set(venue_ids) - {v["id"] for v in venues}
    if missing:
        log.warning("API returned no data for venue IDs %s", sorted(missing))
    return venues


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging("ingest_venues", args.verbose)
    log.info("Run started: seasons %s", args.season)

    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for i, season in enumerate(args.season):
            if i:
                time.sleep(1)  # be polite between requests
            try:
                venue_ids = venue_ids_from_schedule(season)
            except FileNotFoundError as e:
                log.error("%s", e)
                return 2
            try:
                venues = fetch_venues(session, season, venue_ids)
            except requests.RequestException:
                log.exception("Fetch failed for %s", season)
                return 1
            path = write_jsonl(venues, RAW_DIR / f"season={season}" / "venues.jsonl")
            log.info("Wrote %s venues to %s", len(venues), path.relative_to(PROJECT_ROOT))

    log.info("Run finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
