---
name: review-agent-sql
description: Review SQL written by an agent (text-to-SQL answers, generated dbt models) before it is merged or its number is shown to a user.
---

# Review agent written SQL

Agent SQL usually runs and usually looks right. Every wrong answer in `reports/agent_eval.md` ran without error.
Check each point and quote the line for any finding.

1. **Is this metric already governed?** If the question maps to a measure in `semantic/semantic_model.yml`,
   the answer must come from the semantic layer, not new SQL. Compare the two numbers.
2. **Grain of the formula.** Retention is firm level: capping at firm x product (q20) or computing GRR from the
   renewals table (q25) gives a different, plausible number.
3. **Names vs flags.** "Research Core" is a product, not `is_core` (q32). Filters must use the dimension value the
   user said.
4. **Semi-additive measures.** ARR and seats from `fct_arr_monthly` must be filtered to one month end.
5. **As-was joins.** Facts join `dim_firm` on `firm_sk`. A join on `account_id` + `is_current` restates history.
6. **Bridge fan out.** Any join to `bridge_firm_practice_area` without `allocation_weight` double counts.
7. **Definitions hidden in the wording.** "ARR lost at renewal" is churned lines only, not churn plus downsell (q38).
   If the wording allows two readings, ask, do not pick.

Output: approve, or a numbered list of findings with the line and a query showing the difference.
