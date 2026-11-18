{#
  BigQuery row-level security on fct_plate_appearances (a post-hook in its config).

  Once a table has any row access policy, every reader, its owner included, sees only
  the rows of the policies they're granted. So two policies:
    all_rows        everything, for the account that builds and tests the project
    team_<abbrev>   only that team's plate appearances (batting_team), for a team analyst

  Principals come from environment variables so no email lands in git:
    STATCAST_BQ_FULL_ACCESS   e.g. user:you@example.com
    STATCAST_BQ_TEAM_ANALYST  e.g. serviceAccount:hou-analyst@<project>.iam.gserviceaccount.com
    STATCAST_BQ_ANALYST_TEAM  Statcast team abbreviation, default HOU

  Without STATCAST_BQ_FULL_ACCESS it creates nothing: a team policy alone would hide
  every row from the builder, and dbt's own tests would fail.

  `create or replace table` (how dbt rebuilds a table) drops its policies, which is why
  this runs after every build instead of once. And policies don't follow the data: a
  model built from this table (app_batter_seasons) is a new table with no policy, so
  anyone who can read it sees all teams. Row-level security has to be on every table
  that exposes the rows.
#}
{% macro row_access_policies() %}
    {%- if target.type != 'bigquery' -%}
        {{ return('') }}
    {%- endif -%}

    {%- set full_access = env_var('STATCAST_BQ_FULL_ACCESS', '') -%}
    {%- set analyst = env_var('STATCAST_BQ_TEAM_ANALYST', '') -%}
    {%- set team = env_var('STATCAST_BQ_ANALYST_TEAM', 'HOU') -%}

    {%- if not full_access -%}
        {{ log("STATCAST_BQ_FULL_ACCESS not set: no row access policies on " ~ this, info=true) }}
        {{ return('') }}
    {%- endif -%}

    drop all row access policies on {{ this }};

    create row access policy all_rows
    on {{ this }}
    grant to ('{{ full_access }}')
    filter using (true);

    {%- if analyst %}

    create row access policy team_{{ team | lower }}
    on {{ this }}
    grant to ('{{ analyst }}')
    filter using (batting_team = '{{ team }}');
    {%- endif %}
{% endmacro %}
