-- grain: one row per currency per month start. Latest delivery wins.
select currency, cast(month_start as date) as month_start, local_per_usd
from {{ source('bronze', 'fx_rates_monthly') }}
qualify row_number() over (partition by currency, month_start order by _loaded_at desc) = 1
