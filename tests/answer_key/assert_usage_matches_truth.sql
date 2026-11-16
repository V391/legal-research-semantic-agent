-- Weekly usage after restatements matches the answer key exactly, row for row.
select coalesce(g.account_id, t.account_id) as account_id, coalesce(g.product_id, t.product_id) as product_id,
       coalesce(g.week_start, cast(t.week_start as date)) as week_start
from {{ ref('fct_usage_weekly') }} g
full outer join {{ source('truth', 'usage_weekly') }} t
  on cast(t.week_start as date) = g.week_start and t.account_id = g.account_id and t.product_id = g.product_id
where g.account_id is null or t.account_id is null
   or g.licensed_seats <> t.licensed_seats or g.active_users <> t.active_users or g.searches <> t.searches
   or g.documents_viewed <> t.documents_viewed or g.ai_prompts <> t.ai_prompts
