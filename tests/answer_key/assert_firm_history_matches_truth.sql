-- The Type 2 firm dimension reproduces the true history: same versions, same segment and owner, same dates.
select coalesce(g.account_id, t.account_id) as account_id, g.valid_from_date, t.valid_from as truth_from,
       g.segment, t.segment as truth_segment
from {{ ref('dim_firm') }} g
full outer join {{ source('truth', 'firm_versions') }} t
  on t.account_id = g.account_id and cast(t.valid_from as date) = g.valid_from_date
where g.account_id is null or t.account_id is null
   or g.segment <> t.segment or g.account_owner <> t.account_owner
   or g.valid_to_date <> cast(t.valid_to as date) or g.region <> t.region
