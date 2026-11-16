-- Every contract line needs the FX rate of its start month; without it the line silently drops out of ARR.
select l.contract_id, l.currency, l.start_date
from {{ ref('slv_contract_lines') }} l
left join {{ ref('slv_fx_monthly') }} fx
  on fx.currency = l.currency and fx.month_start = cast(date_trunc('month', l.start_date) as date)
where fx.local_per_usd is null
