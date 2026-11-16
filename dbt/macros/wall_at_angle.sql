{#
  Wall distance or height at a spray angle, linearly interpolated between Savant's five
  measured points: the lines (+-45), the gaps (+-fence_gap_angle_deg) and center (0).

    angle    SQL expression for the spray angle in degrees (negative = left field).
    measure  'distance' or 'height'.
    prefix   table alias plus dot for the park columns (distance_lf_gap_ft...), or ''.

  The one place this formula lives: fct_batted_balls uses it for the park a ball was hit
  in, and app_park_walls for every park's outline, so the two can't disagree.

  Balls hooking past a line use the line's value. A null angle (no hit coordinates)
  gives null: DuckDB's least() skips NULLs (least(NULL, 45) = 45), so it's guarded.
  The gap angle comes from notebooks/06_wall_distance_auc.ipynb.
#}
{% macro wall_at_angle(angle, measure, prefix='') -%}
    {%- set gap = var('fence_gap_angle_deg') -%}
    {%- set m = 'distance' if measure == 'distance' else 'height' -%}
    {%- set abs_angle -%}
        (case when {{ angle }} is not null then least(abs({{ angle }}), 45) end)
    {%- endset -%}
    {%- set gap_value -%}
        (case when {{ angle }} < 0 then {{ prefix }}{{ m }}_lf_gap_ft else {{ prefix }}{{ m }}_rf_gap_ft end)
    {%- endset -%}
    {%- set line_value -%}
        (case when {{ angle }} < 0 then {{ prefix }}{{ m }}_lf_line_ft else {{ prefix }}{{ m }}_rf_line_ft end)
    {%- endset -%}
    {%- set center_value = prefix ~ m ~ '_cf_ft' -%}
    case
        when {{ abs_angle }} <= {{ gap }}
            then {{ center_value }} + ({{ gap_value }} - {{ center_value }}) * {{ abs_angle }} / {{ gap }}
        else {{ gap_value }} + ({{ line_value }} - {{ gap_value }}) * ({{ abs_angle }} - {{ gap }}) / (45 - {{ gap }})
    end
{%- endmacro %}
