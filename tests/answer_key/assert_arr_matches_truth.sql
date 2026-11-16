-- Every firm x product x month end in fct_arr_monthly must match the simulator's answer key:
-- same rows, same seats, ARR within one cent. A row missing on either side fails.
select coalesce(g.month_end, t.month_end) as month_end, coalesce(g.account_id, t.account_id) as account_id,
       coalesce(g.product_id, t.product_id) as product_id, g.seats, t.seats as truth_seats, g.arr_usd, t.arr_usd as truth_arr
from {{ ref('fct_arr_monthly') }} g
full outer join {{ source('truth', 'arr_monthly') }} t
  on t.month_end = g.month_end and t.account_id = g.account_id and t.product_id = g.product_id
where g.account_id is null or t.account_id is null
   or g.seats <> t.seats
   or abs(g.arr_usd - t.arr_usd) > 0.01
