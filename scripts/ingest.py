"""Pull Statcast pitch-level data from Baseball Savant and save it as raw Parquet.

Examples:
    python scripts/ingest.py                                  # yesterday
    python scripts/ingest.py --start 2026-10-01 --end 2026-10-10
    python scripts/ingest.py --start 2025-03-01 --end 2025-11-05   # backfill a season

Raw files are written exactly as pulled, one file per season per run:
    data/raw/statcast/season=2026/statcast_2026-10-01_2026-10-10.parquet
"""

import argparse
import datetime as dt
import logging
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
from pybaseball import cache, statcast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "statcast"
LOG_DIR = PROJECT_ROOT / "logs"

log = logging.getLogger("ingest")

# pybaseball 2.2.7 triggers pandas deprecation warnings once per day it fetches.
# They come from inside the library, not this script; recheck after upgrading pandas.
warnings.filterwarnings("ignore", category=FutureWarning, module="pybaseball")


def setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logfile = logging.FileHandler(LOG_DIR / "ingest.log")
    logfile.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(console)
    root.addHandler(logfile)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    yesterday = dt.date.today() - dt.timedelta(days=1)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=dt.date.fromisoformat, default=None,
                   help="first game date, YYYY-MM-DD (default: same as --end)")
    p.add_argument("--end", type=dt.date.fromisoformat, default=yesterday,
                   help="last game date, YYYY-MM-DD (default: yesterday)")
    p.add_argument("--no-cache", action="store_true", help="disable pybaseball's local cache")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = p.parse_args(argv)

    args.start = args.start or args.end
    if args.start > args.end:
        p.error(f"--start {args.start} is after --end {args.end}")
    if args.end >= dt.date.today():
        p.error("--end must be before today; Savant publishes a day's games overnight")
    return args


def split_by_season(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Break a date range at calendar-year boundaries so each file belongs to one season."""
    windows = []
    for year in range(start.year, end.year + 1):
        windows.append((max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))))
    return windows


def fetch(start: dt.date, end: dt.date) -> pd.DataFrame:
    log.info("Fetching Statcast %s..%s", start, end)
    t0 = time.perf_counter()
    df = statcast(start.isoformat(), end.isoformat(), verbose=False)
    log.info("Fetched %s rows x %s cols in %.1fs", f"{len(df):,}", df.shape[1], time.perf_counter() - t0)
    return df


def write_raw(df: pd.DataFrame, start: dt.date, end: dt.date) -> Path:
    out_dir = RAW_DIR / f"season={start.year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"statcast_{start}_{end}.parquet"
    df.to_parquet(path, index=False)
    log.info("Wrote %s (%.1f MB)", path.relative_to(PROJECT_ROOT), path.stat().st_size / 1e6)
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    if not args.no_cache:
        cache.enable()

    log.info("Run started: %s..%s", args.start, args.end)
    total = 0
    for start, end in split_by_season(args.start, args.end):
        try:
            df = fetch(start, end)
        except Exception:
            log.exception("Fetch failed for %s..%s", start, end)
            return 1
        if df.empty:
            log.warning("No pitches for %s..%s (off day or off-season?)", start, end)
            continue
        write_raw(df, start, end)
        total += len(df)

    log.info("Run finished: %s rows total", f"{total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
