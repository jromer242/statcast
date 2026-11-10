"""Helpers shared by the ingest scripts. Scripts import this as `from common import ...`
(running `python scripts/x.py` puts scripts/ on the import path)."""

import datetime as dt
import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
USER_AGENT = "statcast-learning-project"


def setup_logging(log_name: str, verbose: bool) -> None:
    """Log to stdout and to logs/<log_name>.log."""
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logfile = logging.FileHandler(LOG_DIR / f"{log_name}.log")
    logfile.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(console)
    root.addHandler(logfile)


def write_jsonl(records: list[dict], path: Path) -> Path:
    """Write one JSON object per line, each with `_ingested_at`, replacing `path` safely.

    Writes a temp file, then renames it: a crash mid-write never leaves a half-written
    file where dbt would read it. The rename replaces the old file in one step.
    """
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps({**r, "_ingested_at": ingested_at}) + "\n")
    tmp.replace(path)
    return path


def extract_savant_data(html: str) -> list[dict]:
    """Return the `var data = [...]` array embedded in a Baseball Savant leaderboard page.

    Savant's leaderboards have no JSON endpoint; the page's data sits in a <script> tag.
    """
    match = re.search(r"var data\s*=\s*", html)
    if match is None:
        raise ValueError("`var data =` not found; Savant may have changed the page layout")
    # raw_decode reads exactly one JSON value starting at that position and ignores the rest
    data, _ = json.JSONDecoder().raw_decode(html, match.end())
    return data
