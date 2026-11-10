# dbt project: statcast

Turns raw files from `scripts/` into clean, tested tables in `data/statcast.duckdb`.

```
scripts/ingest.py                  -> data/raw/statcast/season=YYYY/*.parquet            -> stg_savant__pitches
scripts/ingest_schedule.py         -> data/raw/mlb/schedule/season=YYYY/*.jsonl          -> stg_mlb__games
scripts/ingest_venues.py           -> data/raw/mlb/venues/season=YYYY/*.jsonl            -> stg_mlb__venues
scripts/ingest_park_dimensions.py  -> data/raw/savant/park_dimensions/season=YYYY/*.jsonl -> stg_savant__park_dimensions
scripts/ingest_park_factors.py     -> data/raw/savant/park_factors/season=YYYY/*.jsonl    -> stg_savant__park_factors
                                   -> data/raw/savant/park_environment/season=YYYY/*.jsonl -> stg_savant__park_environment
```

Two layers of models:

- **Staging** (`models/staging/<source>/`): one model per source table. Renames, fixes types,
  removes duplicates. No business logic.
- **Marts** (`models/marts/`): tables built for analysis and modeling, combining sources.
  `dim_venue_seasons` is one row per park per season with everything known about it
  *before* the season starts.

How they join:

```
stg_savant__pitches --game_pk--> stg_mlb__games --(venue_id, season)--> dim_venue_seasons
```

`dim_venue_seasons` is built from:

```
stg_mlb__venues               same season   location, orientation, roof, turf
stg_savant__park_dimensions   same season   measured distances, wall heights
stg_savant__park_factors      season - 1    park factor indexes (leakage rule below)
stg_savant__park_environment  season - 1    extra fly ball carry
```

Venues and parks are **snapshots per season** (walls move, capacity changes), so always join
on `(venue_id, season)`, never `venue_id` alone.

### Leakage rule

Park factors and environment are computed from a season's own batted balls. Giving a 2025
pitch the 2025 park factor would let a model see the outcomes it's predicting. So
`dim_venue_seasons` only uses values from **season - 1**: a 2025 row gets the 3-season window
2022–2024. Physical facts (dimensions, wall heights, roof) are known before the season and use
the same season. The rule lives in the mart, so every model that reads it gets the same safe
values. Staging keeps Savant's own labels.

## Loading a season

`ingest_venues.py` reads venue IDs from the raw schedule, so run the schedule first. From the
project root:

```bash
.venv/bin/python scripts/ingest.py --start 2025-03-01 --end 2025-11-05
.venv/bin/python scripts/ingest_schedule.py --season 2025
.venv/bin/python scripts/ingest_venues.py --season 2025
.venv/bin/python scripts/ingest_park_dimensions.py --season 2025   # 2015 or later
.venv/bin/python scripts/ingest_park_factors.py --season 2024 2025  # 2015 or later; include the prior season
```

Then `dbt build` from this folder. During the season, re-run the schedule daily (games get
postponed and resumed); venues and park data only change between seasons.

## Running it

Run from this `dbt/` folder with the project venv:

```bash
../.venv/bin/dbt build                          # build every model, then run every test
../.venv/bin/dbt build --select stg_mlb__games+  # one model, plus everything downstream of it
../.venv/bin/dbt test                           # tests only, against tables already built
../.venv/bin/dbt docs generate && ../.venv/bin/dbt docs serve   # browsable docs and lineage
```

`dbt build` runs each model's tests right after building it, and skips downstream models if a
test fails. Close any notebook connection to `statcast.duckdb` first. DuckDB allows only one
writer, so an open connection blocks dbt (see the databases README).

## Where tests live

| Kind | Where | What it is |
|---|---|---|
| Generic tests | `data_tests:` under a column in `models/**/_*__models.yml` and `seeds/_seeds.yml` | Built-in checks (`unique`, `not_null`, `accepted_values`) applied to one column |
| Singular tests | `tests/*.sql`, described in `tests/_tests.yml` | A custom SQL query. **Every row it returns is a failure.** |

Both kinds pass when the test query returns zero rows. A test configured with `severity = 'warn'`
reports its rows as a warning instead of failing the build. On failure, dbt prints the row count;
`dbt build --store-failures` saves the failing rows to a table so you can inspect them.

List every test: `../.venv/bin/dbt ls --resource-type test`

## Test catalog

### `stg_savant__pitches` (one row per pitch)

| Test | Why it matters |
|---|---|
| `pitch_id` unique, not null | The table's key (`game_pk-at_bat_number-pitch_number`). A duplicate means the raw-file dedupe broke and pitches would be double counted. |
| `game_pk`, `game_date`, `batter_id`, `pitcher_id`, `pitch_result_type` not null | Columns every downstream model joins or filters on. |
| `game_type` in R, F, D, L, W, S, E, A | Catches a new or misread game type before it leaks into "regular season" filters. |
| `inning_topbot` in Top, Bot; `batter_stand`, `pitcher_throws` in L, R | Catches encoding changes from Savant. |
| `pitch_result_type` in B, S, X | Ball, strike, in play. Anything else means the column's meaning changed. |

### `stg_mlb__games` (one row per game)

| Test | Why it matters |
|---|---|
| `game_pk` unique, not null | Postponed and suspended games appear twice in the raw schedule. If the dedupe fails, every pitch join to games would fan out (duplicate pitches). |
| `venue_id`, `home_team_id`, `away_team_id`, `official_date` not null | `venue_id` is the bridge to park data; a null strands that game's pitches. |
| `game_type` in R, F, D, L, W | Matches what `ingest_schedule.py` requests. Anything else means the request changed. |
| `double_header` in N, Y, S | Not, traditional, split. Catches API encoding changes. |

### `stg_mlb__venues` (one row per venue per season)

| Test | Why it matters |
|---|---|
| `venue_id || '-' || season` unique | One snapshot per venue per season. A duplicate would fan out every game joined to it. |
| `venue_id`, `season`, `venue_name` not null | Join keys and a readable label. |
| `roof_type` in Open, Retractable, Dome; `turf_type` in Grass, Artificial Turf | Catches API encoding changes before they split a feature into two spellings. |

### `stg_savant__park_dimensions` (one row per home park per season)

| Test | Why it matters |
|---|---|
| `venue_id || '-' || season` unique | One measurement per park per season. |
| `venue_id`, `season`, `distance_cf_ft`, `height_highest_ft` not null | A park row without measurements is as bad as no row. |

### `stg_savant__park_factors` (one row per park, season, window and batter side)

| Test | Why it matters |
|---|---|
| `venue_id-season-rolling_years-bat_side` unique | One index per combination; a duplicate would fan out the mart's pivot. |
| `rolling_years` in 1, 3; `bat_side` in All, L, R | Matches what `ingest_park_factors.py` requests. |
| `venue_id`, `season`, `n_pa`, `pf_hr`, `pf_runs` not null | Every row carries an index and its sample size. |

### `stg_savant__park_environment` (one row per park per season)

| Test | Why it matters |
|---|---|
| `venue_id || '-' || season` unique; `venue_id`, `season`, `extra_distance_ft` not null | One measurement per park per season. |

### `dim_venue_seasons` (mart: one row per venue per season)

| Test | Why it matters |
|---|---|
| `venue_id || '-' || season` unique; `venue_id`, `season`, `venue_name` not null | Pitches join here through games. A duplicate would double count pitches. |

### `savant_field_dictionary` (seed)

| Test | Why it matters |
|---|---|
| `field` unique, not null; `stg_column` unique | One dictionary entry per raw column, and no two raw columns renamed to the same staging name. |
| `description` not null; `source` in savant, manual | Every column is documented and its origin is known. |

### Cross-model (singular) tests

| Test | Why it matters |
|---|---|
| `assert_statcast_games_have_one_schedule_row` | **Join coverage.** Every regular-season and postseason Statcast game must match exactly one `stg_mlb__games` row on the same date. Catches a season loaded by `ingest.py` but not `ingest_schedule.py`, a broken schedule dedupe, or a date mismatch. Spring training is excluded because the schedule ingest doesn't pull it. Verified to fail (2,477 rows) with the 2025 schedule file removed. |
| `assert_game_has_one_venue` | A suspended game resumed in a different park would get a single `venue_id` (the dedupe keeps the latest row), so day-one pitches would get the wrong park. Checks the raw schedule, ignoring Postponed and Cancelled rows (no pitches thrown). Never happened in 2024–2026; if it fails, venues must be assigned per part of the game, not per `game_pk`. |
| `assert_every_game_has_venue_season` | Every game has a `stg_mlb__venues` row for its venue **and season**. Catches a season loaded by `ingest_schedule.py` but not `ingest_venues.py`. Verified to fail (2,473 rows) with the 2024 venues file removed. |
| `assert_park_factor_window_ends_in_season` | Every Savant window ends in its labeled season and spans `rolling_years` seasons. The leakage rule (use season - 1) is only safe if this holds; if Savant changed its labels, the mart would quietly use future data. |
| `assert_home_parks_have_prior_park_factors` | **Warning only.** Lists home parks (20+ games) with no 3-year park factor from the previous season. Expected for a team's first seasons in a park (A's in Sacramento 2025–26, Rays at Steinbrenner Field 2025 and back at Tropicana Field 2026); anything else means a season of park factors wasn't loaded. |
| `assert_home_parks_have_dimensions` | Every venue with 20+ completed games in a season (a real home park) has Savant measured dimensions that season. One-off neutral sites (Tokyo, London, Mexico City, Seoul, Williamsport) are expected to be missing: about 0.1–0.3% of pitches per season. Verified to fail (30 parks) with the 2026 file removed. |

## Adding a test

- **One column, standard rule:** add it under `data_tests:` in the model's YAML and add a row above.
- **Anything across rows or tables:** write `tests/assert_<what_must_be_true>.sql` returning the bad
  rows, describe it in `tests/_tests.yml`, add a row above, and **make it fail once on purpose**
  to prove it can.
