# dbt project: statcast

Turns raw files from `scripts/` into clean, tested tables in `data/statcast.duckdb`.

```
scripts/ingest.py                  -> data/raw/statcast/season=YYYY/*.parquet            -> stg_savant__pitches
scripts/ingest_schedule.py         -> data/raw/mlb/schedule/season=YYYY/*.jsonl          -> stg_mlb__games
scripts/ingest_venues.py           -> data/raw/mlb/venues/season=YYYY/*.jsonl            -> stg_mlb__venues
scripts/ingest_players.py          -> data/raw/mlb/players/season=YYYY/*.jsonl           -> stg_mlb__players
scripts/ingest_park_dimensions.py  -> data/raw/savant/park_dimensions/season=YYYY/*.jsonl -> stg_savant__park_dimensions
scripts/ingest_park_factors.py     -> data/raw/savant/park_factors/season=YYYY/*.jsonl    -> stg_savant__park_factors
                                   -> data/raw/savant/park_environment/season=YYYY/*.jsonl -> stg_savant__park_environment
```

Three layers of models:

- **Staging** (`models/staging/<source>/`): one model per source table. Renames, fixes types,
  removes duplicates. No business logic.
- **Marts** (`models/marts/`): tables built for analysis and modeling, combining sources.
  `dim_venue_seasons` is one row per park per season with everything known about it
  *before* the season starts. `fct_batted_balls` is one row per ball in play, with its
  spray angle and the park's wall in that direction. `fct_plate_appearances` is one row per
  plate appearance, `dim_players` one row per player, and `dim_games` one row per game.
  Every mart has an enforced contract (see below).
- **App** (`models/app/`): small extracts for the Streamlit app (`app_park_walls`,
  `app_batted_balls`, `app_batter_seasons`), declared as a dbt **exposure** in
  `_app__exposures.yml` so lineage shows what the app depends on.
  `scripts/export_app_data.py` writes them to `app/data/` as Parquet.

The wall interpolation (wall distance and height at any spray angle) lives in one macro,
`macros/wall_at_angle.sql`. `fct_batted_balls` uses it for the park a ball was hit in,
and `app_park_walls` for every park's outline, so they can't disagree. Moving the
formula into the macro changed none of the 380,179 wall values (checked row by row).

How they join:

```
stg_savant__pitches --game_pk--> dim_games --(venue_id, season)--> dim_venue_seasons
          \_____________________________________________________________________/
                                         |
                                  fct_batted_balls
                                         ^
                                         | batted_ball_pitch_id = pitch_id
dim_players <--batter_id, pitcher_id-- fct_plate_appearances --(venue_id, season)--> dim_venue_seasons
```

`fct_plate_appearances` rolls pitches up to one row per Savant at-bat. The situation
(inning, outs, runners, score) comes from the first pitch and the result from the last.
About 0.2% of at-bats aren't real plate appearances: the inning ended while the batter
was up (caught stealing, pickoff), and the batter led off the next inning with a fresh count.
Savant labels those `truncated_pa` or leaves the event empty. They stay in the table
with `is_completed_pa = false`.

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
.venv/bin/python scripts/ingest_players.py --season 2025
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

`fct_batted_balls` is **incremental**: a normal build only rebuilds the last
`batted_balls_lookback_days` (7) days before the newest game it already has. Rebuild it
from scratch after loading park dimensions, re-pulling older Statcast dates, or changing
the model:

```bash
../.venv/bin/dbt build --full-refresh --select fct_batted_balls
```

`dbt build` runs each model's tests right after building it, and skips downstream models if a
test fails. Close any notebook connection to `statcast.duckdb` first. DuckDB allows only one
writer, so an open connection blocks dbt (see the databases README).

## CI

[`.github/workflows/dbt-ci.yml`](../.github/workflows/dbt-ci.yml) runs on every push to
`main` and every pull request: `dbt parse`, a full `dbt build`, then a second build of
`fct_batted_balls+` so the incremental branch runs too.

CI has no access to `data/raw/` (it's gitignored and ~340 MB), so it builds from
`ci/fixtures/raw/`: about 4 MB, committed, with the same folder layout and file formats.
It holds pitches and schedule rows for about 40 games across 2024–2026, plus every
venue and park file. [`scripts/make_ci_fixtures.py`](../scripts/make_ci_fixtures.py)
cuts it from the real raw files. It always includes the cases staging has to handle: a
postponed game (two schedule rows for one `game_pk`), a suspended-and-resumed game, a
rescheduled game, a neutral site with no measured dimensions, and a postseason game.
The rest are regular-season games picked by a fixed hash of `game_pk`.

`--target ci` switches both ends: sources read `raw_dir_ci` instead of `raw_dir`, and
dbt writes to `ci/statcast_ci.duckdb` instead of `data/statcast.duckdb`. So fixture data
can't end up in the dev database. To run CI locally:

```bash
../.venv/bin/dbt build --target ci
```

Re-run `python scripts/make_ci_fixtures.py` and commit the result after adding a raw
column that staging reads, so the sample has it too.

Limits: on about 40 games, the tests that count home parks (20+ games) have nothing to
check, and the season-level checks on spray angle and wall distance use small samples.
Those tests still run in full on the local build.

## Where tests live

| Kind | Where | What it is |
|---|---|---|
| Generic tests | `data_tests:` under a column in `models/**/*.yml` and `seeds/_seeds.yml` | Built-in checks (`unique`, `not_null`, `accepted_values`) applied to one column |
| Singular tests | `tests/*.sql`, described in `tests/_tests.yml` | A custom SQL query. **Every row it returns is a failure.** |
| Constraints | `constraints:` in `models/marts/<model>.yml` | Primary keys and `not_null`, enforced by DuckDB when the table is written (see contracts below). |

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

### `stg_mlb__players` (one row per player per season)

| Test | Why it matters |
|---|---|
| `player_id || '-' || season` unique; `player_id`, `season`, `full_name`, `height_in` not null | One snapshot per player per season; `height_in` not null proves the text parse (`6' 2"`) worked. |

### Marts: contracts and constraints

Every mart has an **enforced contract**: its YAML (`models/marts/<model>.yml`) lists every
column with its data type, and dbt checks the model's SQL against that list *before*
building. A renamed, dropped, added or retyped column fails the build with a table of
mismatches, instead of quietly breaking whatever reads the mart. Primary keys and key
`not_null` columns are **constraints**: DuckDB creates the table with them and refuses a
violating row as it's written, so they replace the `unique`/`not_null` tests the marts
used to have. Both were proven by breaking them on purpose: a `weight_lb` typed
`integer` in the contract failed with `BIGINT` vs `INTEGER`, and a duplicated player row
failed with `duplicate key "664056"`.

| Mart (grain) | Primary key | Other checks and why |
|---|---|---|
| `dim_venue_seasons` (venue per season) | `(venue_id, season)` | `venue_name` not null. Pitches join here through games; a duplicate would double count them. |
| `dim_games` (game) | `game_pk` | `day_night` in day, night; `game_type` in R, F, D, L, W; `is_neutral_site`, `is_completed`, `has_pitch_data` not null. |
| `dim_players` (player) | `player_id` | `bats` in L, R, S; `throws` in L, R, S. `S` for throws looked like a bad value, but it's real: Carlos Cortes and Anthony Seigler are listed as ambidextrous throwers. The test caught them on its first run. |
| `fct_batted_balls` (ball in play) | `pitch_id` | `game_pk` in `dim_games`; `batter_id` in `dim_players`; `batter_stand`, `batted_ball_type`, `spray_direction` in fixed lists (catches encoding changes before they split a feature). The key catches a broken incremental delete+insert. |
| `fct_plate_appearances` (plate appearance) | `pa_id` (`game_pk-at_bat_number`) | `game_pk` in `dim_games`; `batter_id`, `pitcher_id` in `dim_players` (catches a season loaded by `ingest.py` but not `ingest_players.py`); `batted_ball_pitch_id` unique and in `fct_batted_balls`; `pa_event` in a fixed list, so a new Savant event fails the build instead of quietly counting as an out; `outs_at_start` in 0, 1, 2. |

`season` is an `integer` everywhere. It used to be `bigint` in the facts (from Savant's
`game_year`) and `integer` in the dimensions; writing the contracts surfaced it, and
`stg_savant__pitches` now casts it once.

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
| `assert_batted_balls_match_pitches` | **Incremental drift.** Every in-play regular-season or postseason pitch in staging is in `fct_batted_balls` exactly once, and nothing else is. Verified to fail (756 rows) by deleting one day from 2024: the incremental run didn't restore it, because that day is outside the lookback window. Fix with `--full-refresh`. |
| `assert_spray_angle_sign_matches_fielders` | Balls caught by the left fielder average a negative spray angle and by the right fielder a positive one, every season. `pull_angle_deg` and the wall interpolation depend on this sign convention. Verified to fail (6 rows) with the sign flipped. |
| `assert_over_fence_hrs_reach_the_wall` | No more than 3% of a season's over-the-fence home runs land short of the interpolated wall (under 1% on 2024–26). Catches a broken interpolation. Verified to fail with left and right swapped, though only for 2 of 3 seasons, since swapping sides only matters in lopsided parks. The spray test above is the stronger guard for that. |
| `assert_wall_needs_spray_angle` | Wall distance and height are null whenever the spray angle is null. Written after a real bug: DuckDB's `least(NULL, 45)` returns 45, so 154 balls without hit coordinates were given the right field line's distance. Notebook 06's reconciliation check found it. Verified to fail (154 rows) on the unfixed model. |

| `assert_pa_home_runs_match_batted_balls` | Home runs per season agree between `fct_plate_appearances` and `fct_batted_balls`. Catches the two facts' filters drifting apart, or a stale incremental batted-ball table. On 2024–26 both have 5,551 / 5,763 / 5,643, and 2024's regular season (5,453) matches MLB's official total. |
| `assert_truncated_pas_end_the_half_inning` | Every at-bat treated as cut short (no event, or `truncated_pa`) is followed by one in the other half-inning. That's the evidence for not counting them as PAs. Holds for all 1,315 on 2024–26. If Savant ever leaves the event off a real PA, this fails instead of PAs quietly disappearing. |

## Adding a test

- **One column, standard rule:** add it under `data_tests:` in the model's YAML and add a row above.
- **Anything across rows or tables:** write `tests/assert_<what_must_be_true>.sql` returning the bad
  rows, describe it in `tests/_tests.yml`, add a row above, and **make it fail once on purpose**
  to prove it can.
