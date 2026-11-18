"""Show BigQuery row-level security on fct_plate_appearances: one query, two readers.

    export STATCAST_BQ_PROJECT=your-project-id
    python scripts/demo_row_access.py

Runs the same query as you (granted the all_rows policy) and as the demo service account
statcast-hou-analyst (granted team_hou), by impersonating it. Then queries
app_batter_seasons as the analyst: it's built from the protected table but has no policy
of its own, so the analyst sees every team. Policies don't follow data into derived
tables. See dbt/macros/row_access_policies.sql and the BigQuery section of dbt/README.md.

Needs: the bq build run with STATCAST_BQ_FULL_ACCESS and STATCAST_BQ_TEAM_ANALYST set, and
roles/iam.serviceAccountTokenCreator for you on the service account.
"""

import os
import sys

import google.auth
from google.auth import impersonated_credentials
from google.cloud import bigquery

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def main() -> int:
    project = os.environ.get("STATCAST_BQ_PROJECT")
    if not project:
        print("set STATCAST_BQ_PROJECT", file=sys.stderr)
        return 1
    analyst_email = f"statcast-hou-analyst@{project}.iam.gserviceaccount.com"

    # quota_project_id: bill the API calls to this project, whatever project your
    # gcloud application-default login was set up with.
    me, _ = google.auth.default(scopes=SCOPES, quota_project_id=project)
    analyst = impersonated_credentials.Credentials(
        source_credentials=me, target_principal=analyst_email, target_scopes=SCOPES)

    sql = f"""
        select count(*) as plate_appearances,
               count(distinct batting_team) as teams,
               countif(is_home_run) as home_runs
        from `{project}.statcast.fct_plate_appearances`
        where season = 2026
    """
    print("fct_plate_appearances, 2026 (has row access policies)")
    for who, creds in [("you", me), ("statcast-hou-analyst", analyst)]:
        row = next(iter(bigquery.Client(project=project, credentials=creds).query(sql).result()))
        print(f"  {who:22} {row.plate_appearances:>8,} PAs  {row.teams:>2} teams  {row.home_runs:>5,} HR")

    sql = f"""
        select count(distinct team) as teams, count(*) as batters
        from `{project}.statcast.app_batter_seasons`
        where season = 2026
    """
    row = next(iter(bigquery.Client(project=project, credentials=analyst).query(sql).result()))
    print("app_batter_seasons, 2026 (built from it, no policy of its own)")
    print(f"  {'statcast-hou-analyst':22} {row.batters:>8,} batters {row.teams:>2} teams  <- every team")
    return 0


if __name__ == "__main__":
    sys.exit(main())
