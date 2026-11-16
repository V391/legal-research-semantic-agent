-- grain: one row per customer firm x product x month end, for every month end in the reporting horizon.
-- Periodic snapshot. firm_sk is the firm version in force on that month end (as-was, not as-is).
-- ARR policy: annual contract value in local currency, converted at the FX rate of the contract's start month
-- (constant currency for the life of a contract, so FX moves never show up as churn or expansion).
with months as (
    select distinct month_end
    from {{ ref('dim_date') }}
    where month_end between date '{{ var("horizon_start") }}' and date '{{ var("horizon_end") }}'
),

active as (
    select m.month_end, l.account_id, l.product_id, l.contract_id, l.currency, l.start_date,
           v.seats, v.annual_value_local
    from months m
    join {{ ref('slv_contract_lines') }} l
      on l.start_date <= m.month_end and m.month_end < l.end_date
    join {{ ref('slv_contract_line_versions') }} v
      on v.contract_id = l.contract_id and v.valid_from <= m.month_end and m.month_end < v.valid_to
),

priced as (
    select a.*, a.annual_value_local / fx.local_per_usd as arr_usd
    from active a
    join {{ ref('slv_fx_monthly') }} fx
      on fx.currency = a.currency and fx.month_start = cast(date_trunc('month', a.start_date) as date)
)

select
    cast(strftime(p.month_end, '%Y%m%d') as integer)  as month_end_key,
    p.month_end,
    f.firm_sk,
    p.account_id,
    p.product_id,
    cast(sum(p.seats) as integer)                     as seats,
    cast(sum(p.arr_usd) as decimal(18, 2))            as arr_usd
from priced p
join {{ ref('dim_firm') }} f
  on f.account_id = p.account_id and f.valid_from_date <= p.month_end and p.month_end < f.valid_to_date
group by all
