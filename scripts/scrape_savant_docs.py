"""Scrape Baseball Savant's CSV field docs into a data dictionary.

    python scripts/scrape_savant_docs.py

Writes dbt/seeds/savant_field_dictionary.csv with one row per raw Savant column:
    field        raw column name, as it appears in the Parquet files
    stg_column   name in stg_savant__pitches (empty if staging drops the column)
    description  Savant's definition, or ours where Savant has none
    source       "savant" (scraped) or "manual" (MANUAL_DESCRIPTIONS below)

Load it into DuckDB with `dbt seed` from the dbt/ folder. Re-run when Savant adds or
changes columns, or when the staging model renames something; the git diff shows what changed.
"""

import re
import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

DOCS_URL = "https://baseballsavant.mlb.com/csv-docs"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "dbt" / "seeds" / "savant_field_dictionary.csv"
STAGING_SQL = PROJECT_ROOT / "dbt" / "models" / "staging" / "savant" / "stg_savant__pitches.sql"

# The docs page uses a different name than the actual CSV column for these.
DOC_NAME_FIXES = {
    "hit_distance": "hit_distance_sc",
    "release_spin": "release_spin_rate",
}

# Columns in the data that the docs page doesn't cover (checked 2026-11-08).
MANUAL_DESCRIPTIONS = {
    "vz0": "The velocity of the pitch, in feet per second, in z-dimension, determined at y=50 feet.",
    "estimated_slg_using_speedangle": "Estimated slugging percentage based on launch angle and exit velocity.",
    "post_fld_score": "Post-pitch field team score",
    "delta_pitcher_run_exp": "Change in run expectancy from the pitcher's side (the negative of delta_run_exp).",
    "bat_speed": "Speed of the sweet spot of the bat, in MPH, at the point of contact (or closest approach on a miss). Swings only; 2023+.",
    "swing_length": "Total distance, in feet, travelled by the head of the bat from the start of tracking until contact. Swings only; 2023+.",
    "miss_distance": "On a swing and miss, how far the bat missed the ball, in inches.",
}


def clean(text: str) -> str:
    """Collapse whitespace/newlines into single spaces."""
    return " ".join(text.split())


def fetch_html(url: str = DOCS_URL) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.text


def parse_fields(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    data_dict: dict[str, str] = {}

    # Each field is a <div class="savant-docs-card">: name in <h3>, description in <p> / <li>
    for card in soup.select("div.savant-docs-card"):
        h3 = card.find("h3")
        if h3 is None:
            continue
        field_name = h3.get_text(strip=True)

        lines = []
        for el in card.find_all(["p", "li"]):
            if el.name == "p":
                if el.find_parent("li"):
                    continue
                # Some <p> tags wrap an <ol> (e.g. launch_speed_angle) -
                # take only the paragraph's own text so list items aren't duplicated
                text = clean(" ".join(
                    s for s in el.find_all(string=True) if not s.find_parent("li")
                ))
            else:
                text = clean(el.get_text(" ", strip=True))
            if text:
                lines.append(text)

        # The page repeats a few entries (pitcher, fielder_2); keep the first
        field_name = DOC_NAME_FIXES.get(field_name, field_name)
        data_dict.setdefault(field_name, " | ".join(lines))

    return pd.DataFrame(list(data_dict.items()), columns=["field", "description"])


def staging_renames(sql_path: Path = STAGING_SQL) -> dict[str, str]:
    """Map raw column -> staging column from the `renamed` CTE of the staging model.

    Matches lines like `pitch_type,`, `batter  as batter_id,` and
    `cast(game_date as date)  as game_date,`. Derived columns (pitch_id) are skipped.
    """
    body = sql_path.read_text().split("renamed as (")[1].split("from deduped")[0]
    line_re = re.compile(r"^\s*(?:cast\()?(\w+)(?:\s+as\s+\w+\))?(?:\s+as\s+(\w+))?\s*,?\s*(?:--.*)?$")
    renames = {}
    for line in body.splitlines():
        m = line_re.match(line)
        if m and m.group(1) != "select":
            raw, alias = m.groups()
            renames[raw] = alias or raw
    return renames


def main() -> int:
    df = parse_fields(fetch_html())
    if df.empty:
        print(f"No fields found at {DOCS_URL}; the page layout may have changed.", file=sys.stderr)
        return 1
    df["source"] = "savant"

    manual = pd.DataFrame(
        [(f, d, "manual") for f, d in MANUAL_DESCRIPTIONS.items() if f not in set(df["field"])],
        columns=["field", "description", "source"],
    )
    df = pd.concat([df, manual], ignore_index=True)

    df["stg_column"] = df["field"].map(staging_renames())
    df = df[["field", "stg_column", "description", "source"]]

    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df)} fields to {OUT_PATH.relative_to(PROJECT_ROOT)} "
          f"({len(manual)} manual, {df['stg_column'].isna().sum()} not in staging)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
