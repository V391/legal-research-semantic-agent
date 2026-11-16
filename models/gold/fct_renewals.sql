-- grain: one row per contract line that reached its end date (the renewal moment) on or before the horizon end.
-- Accumulating snapshot of the renewal decision: renewed if a later line names this one in renews_contract_id.
with lines as (
    select * from {{ ref('slv_contract_lines') }}
),

versions as (
    select * from {{ ref('slv_contract_line_versions') }}
),

fx as (
    select * from {{ ref('slv_fx_monthly') }}
),

expiring as (
    select l.contract_id, l.account_id, l.product_id, l.end_date as renewal_date, l.term_months,
           v.seats as seats_expiring,
           v.annual_value_local / fx.local_per_usd as arr_expiring_usd
    from lines l
    join versions v on v.contract_id = l.contract_id and v.valid_to = l.end_date
    join fx on fx.currency = l.currency and fx.month_start = cast(date_trunc('month', l.start_date) as date)
    where l.end_date <= date '{{ var("horizon_end") }}'
),

successor as (
    select s.renews_contract_id, s.contract_id as successor_contract_id,
           s.initial_annual_value_local / fx.local_per_usd as arr_renewed_usd
    from lines s
    join fx on fx.currency = s.currency and fx.month_start = cast(date_trunc('month', s.start_date) as date)
    where s.renews_contract_id is not null
)

select
    e.contract_id,
    f.firm_sk,
    e.account_id,
    e.product_id,
    e.renewal_date,
    e.term_months,
    e.seats_expiring,
    cast(e.arr_expiring_usd as decimal(18, 2))                              as arr_expiring_usd,
    case when s.successor_contract_id is null then 'churned' else 'renewed' end as outcome,
    s.successor_contract_id,
    cast(coalesce(s.arr_renewed_usd, 0) as decimal(18, 2))                  as arr_renewed_usd
from expiring e
left join successor s on s.renews_contract_id = e.contract_id
join {{ ref('dim_firm') }} f
  on f.account_id = e.account_id and f.valid_from_date <= e.renewal_date and e.renewal_date < f.valid_to_date
