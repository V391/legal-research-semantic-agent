# Injected defects

Each defect is applied alone to clean bronze data, then `dbt build` runs without the answer key tests.

| Defect | Caught | Failing tests |
|---|---|---|
| CPQ replays 5 contract bookings under new event ids | yes | `unique_slv_contract_lines_contract_id` |
| CPQ sends a week of contract values in major units instead of minor units | yes | `expression_true_fct_arr_monthly_arr_usd_seats_between_100_and_10000` |
| FX feed misses INR for one month | yes | `assert_every_contract_has_fx` |
| CPQ amends a contract that was never booked | yes | `relationships_slv_contract_events_contract_id__contract_id__ref_slv_contract_lines_` |
| CRM starts sending a new account type (partner sandbox) | yes | `source_accepted_values_bronze_crm_account_changes_account_type__customer__internal` |
| Practice focus survey saved with percentages not adding to 100 | yes | `weights_sum_to_one_slv_practice_focus_account_id__focus_pct_100_0` |
| Usage restatement doubles a week's counts | yes | `expression_true_fct_usage_weekly_active_users_licensed_seats` |
| CPQ books a contract that ends before it starts | yes | `no_overlapping_intervals_slv_contract_line_versions_valid_from__contract_id__valid_to` |

**8 of 8 caught.**
