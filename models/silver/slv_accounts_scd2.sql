-- grain: one row per account version. Type 2 history built from CRM change data capture.
-- Re-sent changes collapse to one row; versions are ordered by when the change happened, not when it loaded.
with changes as (
    select *
    from {{ source('bronze', 'crm_account_changes') }}
    qualify row_number() over (partition by account_id, changed_at order by _loaded_at desc) = 1
)

select
    account_id,
    account_name,
    account_type,
    segment,
    country,
    account_owner,
    changed_at                                                                  as valid_from_ts,
    cast(changed_at as date)                                                    as valid_from_date,
    coalesce(lead(cast(changed_at as date)) over w, date '9999-12-31')         as valid_to_date,
    lead(changed_at) over w is null                                             as is_current
from changes
window w as (partition by account_id order by changed_at)
