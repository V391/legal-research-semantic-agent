-- Every renewal decision matches the answer key: outcome, expiring ARR and renewed ARR to the cent.
select coalesce(g.contract_id, t.contract_id) as contract_id, g.outcome, t.outcome as truth_outcome,
       g.arr_expiring_usd, t.arr_expiring_usd as truth_expiring, g.arr_renewed_usd, t.arr_renewed_usd as truth_renewed
from {{ ref('fct_renewals') }} g
full outer join {{ source('truth', 'renewals') }} t on t.contract_id = g.contract_id
where g.contract_id is null or t.contract_id is null
   or g.outcome <> t.outcome
   or cast(g.renewal_date as date) <> cast(t.renewal_date as date)
   or abs(g.arr_expiring_usd - t.arr_expiring_usd) > 0.01
   or abs(g.arr_renewed_usd - t.arr_renewed_usd) > 0.01
