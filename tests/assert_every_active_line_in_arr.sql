-- Completeness: every customer contract line active on a month end in the horizon appears in fct_arr_monthly.
with expected as (
    select distinct d.month_end, l.account_id, l.product_id
    from {{ ref('dim_date') }} d
    join {{ ref('slv_contract_lines') }} l on l.start_date <= d.month_end and d.month_end < l.end_date
    join {{ ref('dim_firm') }} f on f.account_id = l.account_id
    where d.is_month_end and d.month_end between date '{{ var("horizon_start") }}' and date '{{ var("horizon_end") }}'
)
select e.*
from expected e
left join {{ ref('fct_arr_monthly') }} a
  on a.month_end = e.month_end and a.account_id = e.account_id and a.product_id = e.product_id
where a.account_id is null
