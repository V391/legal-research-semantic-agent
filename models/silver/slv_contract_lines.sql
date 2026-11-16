-- grain: one row per contract line (contract_id). A renewal is a new line that points at the line it renews.
select
    contract_id,
    account_id,
    product_id,
    renews_contract_id,
    start_date,
    end_date,
    term_months,
    currency,
    seats                                            as initial_seats,
    -- TCV covers the whole term: a 36 month contract carries three years of value. Annualise it.
    cast(tcv_local * 12 / term_months as decimal(18, 2)) as initial_annual_value_local,
    event_ts                                         as booked_at
from {{ ref('slv_contract_events') }}
where event_type = 'contract_created'
