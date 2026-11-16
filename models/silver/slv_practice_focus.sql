-- grain: one row per account per practice area, from the account's latest survey only.
with latest as (
    select account_id, max(surveyed_at) as surveyed_at
    from {{ source('bronze', 'crm_practice_focus') }}
    group by account_id
)

select p.account_id, p.practice_area_id, p.focus_pct, p.surveyed_at
from {{ source('bronze', 'crm_practice_focus') }} p
join latest l on l.account_id = p.account_id and l.surveyed_at = p.surveyed_at
