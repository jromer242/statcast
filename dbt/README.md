# dbt project: statcast

Turns raw files from `scripts/` into clean, tested tables in `data/statcast.duckdb`.

```
scripts/ingest.py           -> data/raw/statcast/season=YYYY/*.parquet      -> stg_savant__pitches
scripts/ingest_schedule.py  -> data/raw/mlb/schedule/season=YYYY/*.jsonl    -> stg_mlb__games
```

Pitches join to games on `game_pk`, and games carry the `venue_id` that park data will join on.

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

Both kinds pass when the test query returns zero rows. On failure, dbt prints the row count;
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

## Adding a test

- **One column, standard rule:** add it under `data_tests:` in the model's YAML and add a row above.
- **Anything across rows or tables:** write `tests/assert_<what_must_be_true>.sql` returning the bad
  rows, describe it in `tests/_tests.yml`, add a row above, and **make it fail once on purpose**
  to prove it can.
