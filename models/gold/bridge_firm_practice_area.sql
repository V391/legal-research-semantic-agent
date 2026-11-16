-- grain: one row per customer firm x practice area. Many to many: a firm works across several practice areas.
-- allocation_weight sums to exactly 1 per firm, so allocated measures add back up to the firm total.
-- Firms without a survey map to PA00 Unspecified with weight 1 instead of silently dropping out.
with firms as (
    select distinct account_id from {{ ref('dim_firm') }}
),

surveyed as (
    select account_id, practice_area_id, cast(focus_pct as decimal(9, 4)) / 100 as allocation_weight
    from {{ ref('slv_practice_focus') }}
)

select f.account_id, coalesce(s.practice_area_id, 'PA00') as practice_area_id,
       cast(coalesce(s.allocation_weight, 1) as decimal(9, 4)) as allocation_weight
from firms f
left join surveyed s on s.account_id = f.account_id
