---
name: add-governed-measure
description: Add or change a business measure in the governed semantic layer. Use when someone asks for a new KPI, a changed definition, or a number the agent cannot answer yet.
---

# Add a governed measure

1. **Agree the definition in words first**, with the business owner: numerator, denominator, grain, which date,
   as-was or as-is attributes, what is excluded. Write it as the `description`. Two people should not be able to
   compute it two ways from that sentence.
2. **Pick the family** in `semantic/semantic_model.yml`: snapshot (month end ARR facts), cohort (start vs end),
   usage (weekly flow) or renewals. If none fits, the gold layer is missing a fact: stop and model it in dbt first.
3. **Write `sql`** against the family alias. Use `{w}` on additive terms if it may be sliced by practice area,
   otherwise set `allocatable: false`.
4. **Write the `dax` twin.** `python semantic/export_tmdl.py` fails if it references a column the gold contracts
   do not have.
5. **Add a golden question** to `eval/questions.yaml` in business language, with its `spec`, and add the formula to
   `eval/truth.py` from the answer key, written independently of your SQL.
6. Run `python eval/run_eval.py --reference-only` (engine must match the answer key), then
   `python eval/run_eval.py --live --ids <new id>` and read `reports/agent_eval.md`.
7. `python run_all.py` must exit 0.
