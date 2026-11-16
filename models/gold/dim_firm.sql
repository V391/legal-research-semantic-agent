-- grain: one row per customer firm version (Type 2). Internal and demo tenants never reach gold.
select
    md5(account_id || '|' || cast(valid_from_ts as varchar))  as firm_sk,
    account_id,
    account_name,
    segment,
    country,
    case country
        when 'United States' then 'Americas'
        when 'Canada' then 'Americas'
        when 'United Kingdom' then 'EMEA'
        when 'India' then 'APAC'
    end                                                         as region,
    account_owner,
    valid_from_date,
    valid_to_date,
    is_current
from {{ ref('slv_accounts_scd2') }}
where account_type = 'customer'
