-- grain: one row per contract line per value interval [valid_from, valid_to).
-- Amendments carry a prorated TCV delta for the rest of the term; annualise it over the remaining months.
with lines as (
    select * from {{ ref('slv_contract_lines') }}
),

changes as (
    select contract_id, start_date as effective_date, initial_seats as seat_change,
           initial_annual_value_local as annual_change
    from lines
    union all
    select e.contract_id, e.effective_date, e.seat_delta,
           cast(e.tcv_delta_local * 12 / {{ dbt.datediff("e.effective_date", "l.end_date", "month") }} as decimal(18, 2))
    from {{ ref('slv_contract_events') }} e
    join lines l on l.contract_id = e.contract_id
    where e.event_type = 'amendment'
),

by_day as (
    select contract_id, effective_date, sum(seat_change) as seat_change, sum(annual_change) as annual_change
    from changes
    group by contract_id, effective_date
)

select
    d.contract_id,
    d.effective_date                                                             as valid_from,
    coalesce(lead(d.effective_date) over w, l.end_date)                          as valid_to,
    cast(sum(d.seat_change) over (w rows between unbounded preceding and current row) as integer) as seats,
    cast(sum(d.annual_change) over (w rows between unbounded preceding and current row) as decimal(18, 2)) as annual_value_local
from by_day d
join lines l on l.contract_id = d.contract_id
window w as (partition by d.contract_id order by d.effective_date)
