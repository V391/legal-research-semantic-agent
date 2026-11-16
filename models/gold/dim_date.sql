-- grain: one row per calendar day, 2020 to 2026. Weeks start Monday; a week belongs to the month and year of its Monday.
with days as (
    select cast(d as date) as date_day
    from generate_series(timestamp '2020-01-01', timestamp '2026-12-31', interval 1 day) t(d)
)

select
    cast(strftime(date_day, '%Y%m%d') as integer)            as date_key,
    date_day,
    cast(date_trunc('week', date_day) as date)              as week_start,
    cast(date_trunc('month', date_day) as date)             as month_start,
    last_day(date_day)                                       as month_end,
    date_day = last_day(date_day)                            as is_month_end,
    year(date_day) || '-Q' || quarter(date_day)              as year_quarter,
    quarter(date_day)                                        as quarter_of_year,
    year(date_day)                                           as calendar_year
from days
