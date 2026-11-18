{#
  SQL that differs between DuckDB (the dev and ci targets) and BigQuery (the bq target).
  Each macro is called as {{ name(...) }} and dispatched on the adapter: dbt runs
  duckdb__name or bigquery__name, falling back to default__name. Everything else in the
  models is SQL both warehouses already agree on.
#}


{#- Value of `value` on the row with the smallest `order_by` in the group, NULL included.
    DuckDB's plain arg_min skips rows where the value is NULL, so arg_min(runner_on_2b_id,
    pitch_number) returned a runner who reached second during the PA, not the first
    pitch's (null) runner. arg_min_null and BigQuery's MIN_BY keep the NULL. -#}
{% macro first_by(value, order_by) -%}
    {{ return(adapter.dispatch('first_by')(value, order_by)) }}
{%- endmacro %}

{% macro duckdb__first_by(value, order_by) -%}
    arg_min_null({{ value }}, {{ order_by }})
{%- endmacro %}

{% macro default__first_by(value, order_by) -%}
    min_by({{ value }}, {{ order_by }})
{%- endmacro %}


{#- Same, for the row with the largest `order_by`. -#}
{% macro last_by(value, order_by) -%}
    {{ return(adapter.dispatch('last_by')(value, order_by)) }}
{%- endmacro %}

{% macro duckdb__last_by(value, order_by) -%}
    arg_max_null({{ value }}, {{ order_by }})
{%- endmacro %}

{% macro default__last_by(value, order_by) -%}
    max_by({{ value }}, {{ order_by }})
{%- endmacro %}


{#- First capture group of a regular expression. BigQuery's third argument is a start
    position, not a group number, and it always returns the first group. Write patterns
    without backslashes or quotes ([0-9] rather than \d) so they mean the same in both. -#}
{% macro regexp_capture(value, pattern) -%}
    {{ return(adapter.dispatch('regexp_capture')(value, pattern)) }}
{%- endmacro %}

{% macro duckdb__regexp_capture(value, pattern) -%}
    regexp_extract({{ value }}, '{{ pattern }}', 1)
{%- endmacro %}

{% macro default__regexp_capture(value, pattern) -%}
    regexp_extract({{ value }}, '{{ pattern }}')
{%- endmacro %}


{#- A UTC time to the wall-clock time in an IANA zone (America/New_York), without a
    zone attached: a DuckDB TIMESTAMP, a BigQuery DATETIME. Doesn't depend on the
    session's time zone. -#}
{% macro utc_to_local(utc_value, time_zone) -%}
    {{ return(adapter.dispatch('utc_to_local')(utc_value, time_zone)) }}
{%- endmacro %}

{% macro duckdb__utc_to_local(utc_value, time_zone) -%}
    timezone({{ time_zone }}, timezone('UTC', {{ utc_value }}))
{%- endmacro %}

{% macro bigquery__utc_to_local(utc_value, time_zone) -%}
    datetime({{ utc_value }}, {{ time_zone }})
{%- endmacro %}


{#- A FROM item with one row per integer from `start` to `stop`, both included. -#}
{% macro integer_series(start, stop, column_name) -%}
    {{ return(adapter.dispatch('integer_series')(start, stop, column_name)) }}
{%- endmacro %}

{% macro duckdb__integer_series(start, stop, column_name) -%}
    range({{ start }}, {{ stop }} + 1) as t({{ column_name }})
{%- endmacro %}

{% macro bigquery__integer_series(start, stop, column_name) -%}
    unnest(generate_array({{ start }}, {{ stop }})) as {{ column_name }}
{%- endmacro %}


{#- 64-bit float. dbt.type_float() is FLOAT, which is 32-bit in DuckDB. -#}
{% macro type_double() -%}
    {{ return(adapter.dispatch('type_double')()) }}
{%- endmacro %}

{% macro duckdb__type_double() -%}double{%- endmacro %}

{% macro default__type_double() -%}float64{%- endmacro %}


{#- Radians to degrees. BigQuery has no degrees() (or radians(): write x * acos(-1) / 180). -#}
{% macro to_degrees(radians_value) -%}
    ({{ radians_value }}) * 180 / acos(-1)
{%- endmacro %}


{#- Partitioning and clustering config for the big tables, BigQuery only (DuckDB has no
    partitions, and dbt-duckdb would read partition_by as a file layout). Month, not day:
    a season's ~180 game days would make ~2,000-row partitions, far below the size where
    pruning pays for its overhead. Cluster on what the app and notebooks filter by. -#}
{% macro bq_partition_by(field) -%}
    {%- if target.type == 'bigquery' -%}
        {{ return({'field': field, 'data_type': 'date', 'granularity': 'month'}) }}
    {%- else -%}
        {{ return(none) }}
    {%- endif -%}
{%- endmacro %}

{% macro bq_cluster_by(columns) -%}
    {{ return(columns if target.type == 'bigquery' else none) }}
{%- endmacro %}


{#- Round to `digits` decimal places the same way on both warehouses: as a decimal, half
    away from zero, returned as a 64-bit float. Plain round() on a float can disagree on
    values like 7.85, stored in binary as 7.8499999999999996: BigQuery rounds that true
    value down (7.8), DuckDB scales it to exactly 78.5 first and rounds up (7.9). Rounding
    the decimal 7.85 gives 7.9 on both. Used where rounded numbers are shown to people. -#}
{% macro round_decimal(value, digits) -%}
    cast(round(cast({{ value }} as {{ 'numeric' if target.type == 'bigquery' else 'decimal(38, 9)' }}), {{ digits }}) as {{ type_double() }})
{%- endmacro %}
