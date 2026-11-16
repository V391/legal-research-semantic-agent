-- grain: one row per account x product x week. A restated week replaces the partial first delivery.
select
    cast(week_start as date) as week_start,
    account_id,
    product_id,
    licensed_seats,
    active_users,
    searches,
    documents_viewed,
    ai_prompts,
    _loaded_at
from {{ source('bronze', 'product_usage_weekly') }}
qualify row_number() over (partition by account_id, product_id, week_start order by _loaded_at desc) = 1
