-- grain: one row per CPQ event (event_id). Redeliveries removed, money converted from minor units once, here.
with ranked as (
    select
        *,
        row_number() over (partition by event_id order by _loaded_at) as delivery_n
    from {{ source('bronze', 'cpq_contract_events') }}
)

select
    event_id,
    event_type,
    contract_id,
    account_id,
    product_id,
    renews_contract_id,
    cast(start_date as date)                         as start_date,
    cast(end_date as date)                           as end_date,
    term_months,
    seats,
    seat_delta,
    cast(effective_date as date)                     as effective_date,
    currency,
    cast(tcv_minor / 100 as decimal(18, 2))          as tcv_local,
    cast(tcv_delta_minor / 100 as decimal(18, 2))    as tcv_delta_local,
    event_ts,
    _loaded_at
from ranked
where delivery_n = 1
