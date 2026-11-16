-- The practice area bridge matches the latest true survey for every firm, Unspecified included.
select coalesce(g.account_id, t.account_id) as account_id, coalesce(g.practice_area_id, t.practice_area_id) as practice_area_id,
       g.allocation_weight, t.weight as truth_weight
from {{ ref('bridge_firm_practice_area') }} g
full outer join (
    select w.* from {{ source('truth', 'practice_weights') }} w
    where w.account_id in (select account_id from {{ ref('dim_firm') }})
) t on t.account_id = g.account_id and t.practice_area_id = g.practice_area_id
where g.account_id is null or t.account_id is null or abs(g.allocation_weight - t.weight) > 0.00001
