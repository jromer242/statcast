-- One row per day, which MetricFlow needs to roll metrics up by week, month or season
-- and to fill days with no games. Covers the seasons loaded (2024 on) with room for
-- the next few. dbt.date_spine stops the day before the end date.

select cast(date_day as date) as date_day
from (
    {{ dbt.date_spine('day', "cast('2024-01-01' as date)", "cast('2030-01-01' as date)") }}
) as spine
