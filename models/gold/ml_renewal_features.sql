-- grain: one row per renewal (contract_id) with at least a full feature window of usage history.
-- Point in time: every feature uses only data that existed feature_lead_days before the renewal date,
-- the moment Customer Success would have to act. The label (churned) is the renewal outcome.
{% set lead = var('feature_lead_days') %}
{% set win = var('feature_window_weeks') %}

with renewals as (
    select r.*, r.renewal_date - interval {{ lead }} day as cutoff
    from {{ ref('fct_renewals') }} r
    where r.renewal_date - interval {{ lead }} day >= date '{{ var("horizon_start") }}' + interval {{ win * 7 }} day
),

usage as (
    select * from {{ ref('fct_usage_weekly') }}
),

window_usage as (
    -- weeks fully completed before the cutoff, last `win` weeks, split into two halves for a trend
    select r.contract_id,
           u.product_id = r.product_id                                         as same_product,
           u.week_start > r.cutoff - interval {{ (win // 2) * 7 + 7 }} day    as recent_half,
           u.licensed_seats, u.active_users, u.searches, u.documents_viewed, u.ai_prompts
    from renewals r
    join usage u
      on u.account_id = r.account_id
     and u.week_start + interval 7 day <= r.cutoff
     and u.week_start > r.cutoff - interval {{ win * 7 + 7 }} day
),

agg as (
    select contract_id,
        sum(active_users) filter (where same_product) * 1.0 / nullif(sum(licensed_seats) filter (where same_product), 0) as product_utilization,
        sum(active_users) filter (where same_product and recent_half) * 1.0
            / nullif(sum(licensed_seats) filter (where same_product and recent_half), 0)
          - sum(active_users) filter (where same_product and not recent_half) * 1.0
            / nullif(sum(licensed_seats) filter (where same_product and not recent_half), 0)                 as product_utilization_trend,
        sum(active_users) * 1.0 / nullif(sum(licensed_seats), 0)                                           as firm_utilization,
        sum(active_users) filter (where recent_half) * 1.0 / nullif(sum(licensed_seats) filter (where recent_half), 0)
          - sum(active_users) filter (where not recent_half) * 1.0 / nullif(sum(licensed_seats) filter (where not recent_half), 0) as firm_utilization_trend,
        sum(searches + documents_viewed) * 1.0 / nullif(sum(licensed_seats), 0)                           as firm_actions_per_seat_week,
        sum(ai_prompts) * 1.0 / nullif(sum(licensed_seats), 0)                                             as firm_ai_prompts_per_seat_week
    from window_usage
    group by contract_id
),

arr_at_cutoff as (
    select r.contract_id,
           max(case when a.product_id = 'P06' then 1 else 0 end)      as has_ai_assistant,
           count(distinct a.product_id)                                 as products_held,
           sum(a.arr_usd)                                               as firm_arr_usd
    from renewals r
    join {{ ref('fct_arr_monthly') }} a
      on a.account_id = r.account_id and a.month_end = last_day(cast(r.cutoff as date) - interval 1 month)
    group by r.contract_id
),

tenure as (
    select account_id, min(start_date) as first_start
    from {{ ref('slv_contract_lines') }}
    group by account_id
)

select
    r.contract_id,
    r.account_id,
    r.renewal_date,
    cast(r.cutoff as date)                                         as feature_cutoff,
    p.product_line,
    not p.is_core                                                  as is_addon,
    f.segment,
    f.region,
    r.term_months,
    r.arr_expiring_usd,
    {{ dbt.datediff("t.first_start", "cast(r.cutoff as date)", "month") }} as tenure_months,
    coalesce(c.has_ai_assistant, 0)                                as has_ai_assistant,
    coalesce(c.products_held, 0)                                   as products_held,
    coalesce(c.firm_arr_usd, 0)                                    as firm_arr_usd,
    g.product_utilization,
    g.product_utilization_trend,
    g.firm_utilization,
    g.firm_utilization_trend,
    g.firm_actions_per_seat_week,
    g.firm_ai_prompts_per_seat_week,
    case when r.outcome = 'churned' then 1 else 0 end              as churned
from renewals r
join {{ ref('dim_product') }} p on p.product_id = r.product_id
join {{ ref('dim_firm') }} f
  on f.account_id = r.account_id and f.valid_from_date <= cast(r.cutoff as date) and cast(r.cutoff as date) < f.valid_to_date
join tenure t on t.account_id = r.account_id
left join agg g on g.contract_id = r.contract_id
left join arr_at_cutoff c on c.contract_id = r.contract_id
