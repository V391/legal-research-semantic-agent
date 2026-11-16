-- grain: one row per customer firm x product x week (week_start is a Monday). firm_sk as-was at week start.
select
    u.week_start,
    f.firm_sk,
    u.account_id,
    u.product_id,
    u.licensed_seats,
    u.active_users,
    u.searches,
    u.documents_viewed,
    u.ai_prompts
from {{ ref('slv_usage_weekly') }} u
join {{ ref('dim_firm') }} f
  on f.account_id = u.account_id and f.valid_from_date <= u.week_start and u.week_start < f.valid_to_date
