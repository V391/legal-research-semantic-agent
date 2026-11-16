# Working in this repo (for coding agents)

Medallion dbt project (bronze -> silver -> gold star schema), a governed semantic layer on top, a Power BI model
generated from it, and an agent that answers questions through it. DuckDB locally, Snowflake target in `profiles.yml`.

## Run
- Everything: `python run_all.py`. A change is done when it exits 0. Green `dbt build` alone is not enough:
  the agent eval, ML checks and the defect suite run outside dbt.
- Models only: `python load_raw.py` then `dbt build` with `DBT_PROFILES_DIR=.`.
- Agent eval against the live model: `python eval/run_eval.py --live` (records to `eval/runs/responses.jsonl`).

## Rules that are easy to break
- **Grain first.** Every model states its grain in its first comment. Check it with a `group by ... having count(*) > 1`.
- **Money.** CPQ sends minor units and whole-term TCV. Convert in `slv_contract_events`, annualise in `slv_contract_lines`
  and `slv_contract_line_versions`, nowhere else. USD uses the contract's start month FX rate.
- **As-was.** Facts carry the `firm_sk` valid at their own date. Never join `dim_firm` on `account_id` with `is_current`
  for anything historical.
- **The bridge.** Anything sliced by practice area multiplies by `allocation_weight`. Firm counts never go through it.
- **Semi-additive ARR.** Sum across firms and products, never across months.
- **One definition per measure.** A new metric goes in `semantic/semantic_model.yml` with both `sql` and `dax`,
  plus a golden question in `eval/questions.yaml`. Do not compute business metrics in ad hoc SQL in the app layer.
- Do not edit `tests/answer_key/`, `eval/truth.py` or the generator to make a build pass. A mismatch is a bug.

## Skills
- `.claude/skills/add-governed-measure/` adding a metric end to end (YAML, DAX, golden question, eval).
- `.claude/skills/review-agent-sql/` checklist for SQL an agent wrote, before it is merged or shown to a user.
