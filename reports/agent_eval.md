# Agent evaluation

40 golden questions, 3 independent runs each, same model for both agents. An answer is correct when the result table matches the answer key within 0.5%.

| Question | Governed | Text-to-SQL |
|---|---|---|
| q01 What was our total ARR at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q02 What was total ARR at the end of 2024? | ✓✓✓ | ✓✓✓ |
| q03 Break down ARR by product line at the end of December 2025. | ✓✓✓ | ✓✓✓ |
| q04 What was ARR by customer segment at the end of December 2024? | ✓✓✓ | ✓✓✓ |
| q05 Show ARR by sales region at the end of June 2025. | ✓✓✓ | ✓✓✓ |
| q06 How is ARR split across practice areas at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q07 How much ARR did the Tax practice area represent at the end of December 2024? | ✓✓✓ | ✓✓✓ |
| q08 How many active customer firms did we have at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q09 How many firms were paying for AI Assistant at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q10 What share of our active customer firms had AI Assistant at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q11 What was AI Assistant ARR at each month end in Q4 2025? | ✓✓✓ | ✓✓✓ |
| q12 How many licensed seats did we have in total at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q13 How many Litigation Analytics seats were licensed in India at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q14 What was average ARR per active firm at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q15 How much ARR came from Global Law Firm segment customers in the United States at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q16 How many Corporate Legal firms were active customers at the end of September 2025? | ✓✓✓ | ✓✓✓ |
| q17 What was Research Plus ARR by country at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q18 How much ARR did Litigation practice work represent in the United Kingdom at the end of December 2025? | ✓✓✓ | ✓✓✓ |
| q19 What was our net revenue retention for calendar year 2025? | ✓✓✓ | ✓✓✓ |
| q20 What was gross revenue retention for 2025? | ✓✓✓ | ✓✗✗ |
| q21 How many customer firms did we lose in 2025? | ✓✓✓ | ✓✓✓ |
| q22 What was the logo churn rate for 2025? | ✓✓✓ | ✓✓✓ |
| q23 How many new customer firms did we win in 2025? | ✓✓✓ | ✓✓✓ |
| q24 What was 2025 net revenue retention by region? | ✓✓✓ | ✓✓✓ |
| q25 What was 2025 gross revenue retention for Mid-size Law firms? | ✓✓✓ | ✗✓✗ |
| q26 Show 2025 net revenue retention by customer segment. | ✓✓✓ | ✓✓✓ |
| q27 What was net revenue retention over the first half of 2025? | ✓✓✓ | ✓✓✓ |
| q28 How many searches did customers run in 2025? | ✓✓✓ | ✓✓✓ |
| q29 What was the average number of weekly active users on AI Assistant in Q4 2025? | ✓✓✓ | ✓✓✓ |
| q30 What was overall seat utilization in Q4 2025? | ✓✓✓ | ✓✓✓ |
| q31 What was seat utilization by customer segment in Q3 2025? | ✓✓✓ | ✓✓✓ |
| q32 How many searches per active user did Research Core customers run in 2025? | ✓✓✓ | ✗✗✗ |
| q33 How many AI Assistant prompts were sent in each quarter of 2025? | ✓✓✓ | ✓✓✓ |
| q34 How many Practical Guidance documents did UK customers view in 2025? | ✓✓✓ | ✓✓✓ |
| q35 How many contract renewals came due in 2025? | ✓✓✓ | ✓✓✓ |
| q36 What was our renewal rate in 2025? | ✓✓✓ | ✓✓✓ |
| q37 What was the 2025 renewal rate by product line? | ✓✓✓ | ✓✓✓ |
| q38 How much ARR did we lose at renewal in 2025? | ✓✓✓ | ✗✓✓ |
| q39 How much ARR was up for renewal in Q1 2025? | ✓✓✓ | ✓✓✓ |
| q40 How much practice area ARR did Intellectual Property account for in India at the end of June 2025? | ✓✓✓ | ✓✓✓ |

## Every wrong answer

### q20 baseline run 2: What was gross revenue retention for 2025?

Truth: `0.9057362062406904`. Got: got [54421891.93, 48954750.94, 0.8995], truth 0.9057

```sql
WITH s AS (SELECT account_id, product_id, SUM(arr_usd) AS start_arr FROM gold.fct_arr_monthly WHERE month_end = DATE '2024-12-31' GROUP BY 1,2), e AS (SELECT account_id, product_id, SUM(arr_usd) AS end_arr FROM gold.fct_arr_monthly WHERE month_end = DATE '2025-12-31' GROUP BY 1,2) SELECT SUM(s.start_arr) AS starting_arr_usd, SUM(LEAST(s.start_arr, COALESCE(e.end_arr, 0))) AS retained_arr_usd, ROUND(SUM(LEAST(s.start_arr, COALESCE(e.end_arr, 0))) / SUM(s.start_arr), 4) AS gross_revenue_retention FROM s LEFT JOIN e ON s.account_id = e.account_id AND s.product_id = e.product_id
```

### q20 baseline run 3: What was gross revenue retention for 2025?

Truth: `0.9057362062406904`. Got: got [54421891.93, 48954750.94, 89.95], truth 0.9057

```sql
WITH s AS (SELECT account_id, product_id, SUM(arr_usd) AS arr FROM gold.fct_arr_monthly WHERE month_end = DATE '2024-12-31' GROUP BY 1,2), e AS (SELECT account_id, product_id, SUM(arr_usd) AS arr FROM gold.fct_arr_monthly WHERE month_end = DATE '2025-12-31' GROUP BY 1,2) SELECT SUM(s.arr) AS starting_arr_usd, SUM(LEAST(s.arr, COALESCE(e.arr, 0))) AS retained_arr_usd, ROUND(100.0 * SUM(LEAST(s.arr, COALESCE(e.arr, 0))) / SUM(s.arr), 2) AS gross_revenue_retention_pct FROM s LEFT JOIN e ON s.account_id = e.account_id AND s.product_id = e.product_id
```

### q25 baseline run 1: What was 2025 gross revenue retention for Mid-size Law firms?

Truth: `0.9263208556671572`. Got: got [0.8739, 5727964.36, 5005860.53], truth 0.9263

```sql
SELECT ROUND(SUM(LEAST(r.arr_renewed_usd, r.arr_expiring_usd)) / SUM(r.arr_expiring_usd), 4) AS gross_revenue_retention_2025, SUM(r.arr_expiring_usd) AS arr_expiring_usd, SUM(LEAST(r.arr_renewed_usd, r.arr_expiring_usd)) AS arr_retained_usd FROM gold.fct_renewals r JOIN gold.dim_firm f ON r.firm_sk = f.firm_sk WHERE f.segment ILIKE 'mid%size%' AND r.renewal_date >= DATE '2025-01-01' AND r.renewal_date < DATE '2026-01-01'
```

### q25 baseline run 3: What was 2025 gross revenue retention for Mid-size Law firms?

Truth: `0.9263208556671572`. Got: got [0.8739, 5727964.36, 5005860.53], truth 0.9263

```sql
SELECT ROUND(SUM(LEAST(r.arr_renewed_usd, r.arr_expiring_usd)) / SUM(r.arr_expiring_usd), 4) AS gross_revenue_retention_2025, SUM(r.arr_expiring_usd) AS arr_expiring_usd, SUM(LEAST(r.arr_renewed_usd, r.arr_expiring_usd)) AS arr_retained_usd FROM gold.fct_renewals r JOIN gold.dim_firm f ON r.firm_sk = f.firm_sk WHERE f.segment ILIKE 'mid%' AND r.renewal_date >= DATE '2025-01-01' AND r.renewal_date < DATE '2026-01-01'
```

### q32 baseline run 1: How many searches per active user did Research Core customers run in 2025?

Truth: `9.208140338854454`. Got: got [10022704.0, 941091.0, 10.650090161312773], truth 9.2081

```sql
SELECT SUM(u.searches) AS total_searches, SUM(u.active_users) AS total_active_user_weeks, SUM(u.searches) * 1.0 / NULLIF(SUM(u.active_users), 0) AS searches_per_active_user FROM gold.fct_usage_weekly u JOIN gold.dim_product p ON u.product_id = p.product_id WHERE p.product_line = 'Research' AND p.is_core AND u.week_start >= DATE '2025-01-01' AND u.week_start < DATE '2026-01-01'
```

### q32 baseline run 2: How many searches per active user did Research Core customers run in 2025?

Truth: `9.208140338854454`. Got: got [10022704.0, 941091.0, 10.65], truth 9.2081

```sql
SELECT SUM(f.searches) AS total_searches, SUM(f.active_users) AS total_weekly_active_users, ROUND(SUM(f.searches) * 1.0 / NULLIF(SUM(f.active_users), 0), 2) AS searches_per_active_user FROM gold.fct_usage_weekly f JOIN gold.dim_product p ON f.product_id = p.product_id WHERE p.product_line = 'Research' AND p.is_core AND f.week_start >= DATE '2025-01-01' AND f.week_start < DATE '2026-01-01'
```

### q32 baseline run 3: How many searches per active user did Research Core customers run in 2025?

Truth: `9.208140338854454`. Got: got [10022704.0, 941091.0, 10.65], truth 9.2081

```sql
SELECT SUM(u.searches) AS total_searches, SUM(u.active_users) AS active_user_weeks, ROUND(SUM(u.searches) * 1.0 / NULLIF(SUM(u.active_users), 0), 2) AS searches_per_active_user FROM gold.fct_usage_weekly u JOIN gold.dim_product p ON u.product_id = p.product_id WHERE p.product_line = 'Research' AND p.is_core AND u.week_start >= DATE '2025-01-01' AND u.week_start < DATE '2026-01-01'
```

### q38 baseline run 1: How much ARR did we lose at renewal in 2025?

Truth: `5549263.508183837`. Got: got [5737131.86], truth 5,549,263.5082

```sql
SELECT SUM(GREATEST(arr_expiring_usd - arr_renewed_usd, 0)) AS arr_lost_at_renewal_2025_usd FROM gold.fct_renewals WHERE renewal_date >= DATE '2025-01-01' AND renewal_date < DATE '2026-01-01'
```
