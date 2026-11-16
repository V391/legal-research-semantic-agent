# Legal research semantic agent

A medallion data product for a legal research subscription business (bronze, silver and gold in dbt), a governed semantic layer on the gold star schema, a Power BI / Fabric model generated from the same definitions, and a Claude agent that answers business questions only through that layer. It is scored against a text-to-SQL agent that uses the same model and the same documented warehouse.

**Result:** across 40 business questions × 3 runs, the governed agent gave **120 of 120** correct answers. Text-to-SQL over a fully documented star schema gave **112 of 120**. All 8 wrong answers ran cleanly and returned plausible numbers, and 3 questions flipped between right and wrong across runs. The warehouse matches an independent answer key on every row of 5 gold tables, and production tests catch **8 of 8** injected source defects.

```
python run_all.py      # about 2 minutes, exits non-zero on any miss
```

## Why this exists

A firm's leadership asks "what was GRR for Mid-size Law last year?" An agent writing SQL over a good warehouse will usually get it right. Sometimes it computes GRR from the renewals table instead of the ARR snapshots, or caps at firm × product instead of firm. It returns 87.4% instead of 92.6%, with no error and no warning. The fix is not a better prompt. It is to give the agent the business's definitions instead of its tables: one governed measure per metric, compiled to SQL by code that owns the joins, the date logic and the formulas, with the same definitions exported to Power BI so dashboards and agents never disagree.

## Architecture

```
generator/            simulated business + answer key (520 firms, 4 currencies, Jan 2024 to Dec 2025)
  │
bronze (raw)          CPQ contract events, CRM change data capture, practice focus surveys,
  │                   weekly usage extracts, monthly FX. Append-only, _loaded_at on every row.
silver (dbt)          deduped, minor units converted, TCV annualised, amendments applied,
  │                   Type 2 accounts, latest survey, latest usage restatement
gold (dbt, contracts) dim_date, dim_firm (SCD2), dim_product, dim_practice_area,
  │                   bridge_firm_practice_area (weighted many to many),
  │                   fct_arr_monthly (periodic snapshot), fct_usage_weekly, fct_renewals,
  │                   ml_renewal_features (point in time)
semantic/             semantic_model.yml: 21 measures, each with SQL and a DAX twin
  ├── engine.py       spec -> SQL compiler; refuses specs that would give a wrong number
  ├── export_tmdl.py  -> powerbi/LegalResearch.SemanticModel (TMDL, Direct Lake partitions)
eval/                 governed agent vs text-to-SQL agent, 40 golden questions, answer key scoring
ml/                   renewal risk (vs a utilization rule), usage anomaly detection (vs static thresholds)
orchestration/        Airflow DAG with the same steps as run_all.py
```

## The data, and the traps in it

`generator/generate.py` simulates firms buying seats on six products across four product lines. It covers renewals, mid-term upsells, AI Assistant adoption after its July 2024 launch, segment upgrades, owner changes and weekly product usage driven by each firm's latent health. Health also drives churn. The generator lands what each source system would send and writes, separately, what really happened.

| Trap | Wrong answer if missed |
|---|---|
| CPQ webhooks delivered at least once | ARR double counted |
| Money in minor units | ARR off by 100× |
| 36 month contracts carry three years of TCV | ARR tripled |
| Amendments carry a prorated TCV delta for the remaining term | Upsell ARR understated |
| Four currencies, monthly FX | Mixed currencies; FX moves showing as churn |
| CRM CDC re-sends and loads out of order | Duplicate or misordered firm versions |
| Firms move up segments over time | History restated with today's segment |
| Firms work across several practice areas | Practice area ARR double counted |
| Firms with no practice survey | Their ARR silently dropped from practice area views |
| Usage weeks first land partial, restated later | Partial weeks counted |
| Internal demo tenants with real-looking contracts and usage | Fake ARR and usage |

## Dimensional model

- **Grain stated in every model's first line**, tested with a uniqueness test on the grain.
- **As-was by construction.** Every fact row carries the `firm_sk` in force on its own date. Slicing 2024 ARR by segment uses 2024 segments without the user having to know.
- **Semi-additive snapshot.** `fct_arr_monthly` sums across firms and products, never across months. The semantic engine refuses a spec that would sum it over a period.
- **Weighted bridge.** `bridge_firm_practice_area` weights sum to exactly 1 per firm (tested), so allocated ARR adds back to the total. Firm counts are refused through the bridge, because a firm in three practice areas is still one firm.
- **Contracts enforced** on every gold model (column names and types). CI fails if any gold column lacks a description.

## Semantic layer

`semantic/semantic_model.yml` is the single definition of each measure, in four families:

| Family | Measures | Date logic |
|---|---|---|
| snapshot | arr, seats, active_firms, arr_per_firm, ai_adoption_rate | one month end (`as_of`), or each month end in a period |
| cohort | nrr, grr, churned_logos, logo_churn_rate, new_logos, starting_arr | month end before the period vs month end at its close; firm attributes as at the start |
| usage | searches, documents_viewed, ai_prompts, avg_weekly_active_users, seat_utilization, searches_per_active_user | weeks whose Monday falls in the period |
| renewals | renewals_due, renewal_rate, arr_up_for_renewal, churned_arr_at_renewal | renewal date in the period |

The agent emits a spec, not SQL:

```json
{"measures": ["grr"], "filters": {"segment": ["Mid-size Law"]}, "period": {"start": "2025-01-01", "end": "2025-12-31"}}
```

`engine.py` compiles it, choosing the joins (as-was firm version, weighted bridge), the snapshot dates and the formula. A spec that cannot be answered correctly is refused with a reason the agent can act on. Examples are ARR summed over a year, firm counts by practice area, and a retention period with no starting snapshot. `export_tmdl.py` writes the same measures as DAX into a PBIP / TMDL semantic model with Direct Lake partitions over the gold tables. It fails if any DAX references a column the gold contracts do not have.

## Agent evaluation

Two agents, the same model (Claude Sonnet), the same 40 questions, 3 independent runs each:

- **Governed** sees the semantic catalog (measures, definitions, dimensions and their values) and answers with a spec.
- **Text-to-SQL** sees every gold table and column with its dbt description and type, and writes DuckDB SQL.

Both get one retry with the error message if their query fails. Both query a serving database that holds only the gold schema. Before any agent runs, the reference run executes each question's hand-written spec through the engine. It must match the answer key on 40 of 40, computed separately in pandas (`eval/truth.py`). That proves the semantic layer itself is right.

| | Governed | Text-to-SQL |
|---|---|---|
| Correct answers | **120/120** | 112/120 (93.3%) |
| Questions right on every run | 40/40 | 36/40 |
| Questions right on some runs only | 0 | 3 |
| Wrong answers that ran without error | 0 | **8 of 8** |

How text-to-SQL went wrong ([every wrong answer, with its SQL](reports/agent_eval.md)):

| Question | What it did | Answer vs truth |
|---|---|---|
| GRR for Mid-size Law, 2025 | GRR from the renewals table, not ARR snapshots | 87.4% vs 92.6% |
| GRR, 2025 (2 of 3 runs) | capped at firm × product instead of firm | 90.0% vs 90.6% |
| Searches per active user, Research Core | read "Research Core" as both core research products | 10.65 vs 9.21 |
| ARR lost at renewal, 2025 | added downsell on renewed lines to churned ARR | $5.74M vs $5.55M |

Every one is a defensible reading of the question. That is the point: the warehouse was clean and documented, and the agent still produced a different number from the business's definition, with nothing to signal it. Model responses are recorded in `eval/runs/responses.jsonl`. CI replays them against a fresh build, so a model change that breaks an answer, or a code change that breaks the layer, fails the PR.

## Applied data science

**Renewal risk** (`ml/renewal_risk.py`). Features are frozen 90 days before each renewal, in dbt (`ml_renewal_features`). The split is out of time: train on renewals before July 2025, test July to December 2025. Model selection uses folds grouped by firm, because a firm's lines churn together and a row-level split leaks. That leak is real: before the fix, it inflated gradient boosting's cross-validated AUC to 0.84, against 0.59 with grouped folds.

| On the held-out half year | AUC | Churned ARR in riskiest 20% |
|---|---|---|
| Rule: lowest seat utilization | **0.71** | **55%** |
| Logistic regression, chosen by grouped CV | 0.59 | 53% |

Decision: **ship the rule**. With about 550 training renewals, the extra features add variance, not signal. The model goes back on the shelf until there are more renewals or a stronger leading indicator.

**Usage anomalies** (`ml/usage_anomalies.py`). Two kinds are planted: search spikes, a licence compliance signal (scraping or shared logins), and tracking gaps, an outage that makes a healthy firm look like it is churning. The detector divides per seat rates by a market-wide seasonal index (holiday weeks dip for everyone), compares them with the series' own trailing median and scores a robust z by MAD. Spikes and gaps get separate rules. Thresholds are tuned on 2024 and scored on 2025.

| 2025 | Weeks flagged | Precision | Recall |
|---|---|---|---|
| Static threshold (per series, tuned) | 3,726 | 1.1% | 89% |
| Seasonal robust z | **34** | **100%** | 72% |

Customer Success can work 34 alerts. It cannot work 3,726.

## Proof

`python run_all.py` runs all of this and fails on any miss. CI runs the same script.

1. **Answer key.** `tests/answer_key/` compares 5 gold tables with the simulator row for row: ARR and seats on 19,992 firm × product × month rows, 1,479 renewal decisions, 86,451 usage rows, 690 firm versions, and the practice area bridge.
2. **Production tests.** These are uniqueness on every grain, interval overlap and exactly-one-current on SCD2, bridge weights summing to 1, FX coverage, ARR completeness, price sanity per seat, active users at most licensed seats, and contracts on every gold model. 83 dbt nodes in all.
3. **Injected defects.** `checks/inject_defects.py` breaks bronze 8 ways, one at a time, and runs the build without the answer key tests. **8 of 8 caught** ([which test caught which](reports/defects.md)).
4. **Semantic reference run.** 40 of 40 hand-written specs match the answer key before any agent is scored.
5. **Docs gate.** It fails if any gold model or column lacks a description, or any measure lacks SQL, DAX or a definition.

## Run it

```
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -r requirements.txt
python run_all.py                                 # generate, build, test, export, replay eval, ML, defects
python eval/run_eval.py --live                    # re-ask the model (ANTHROPIC_API_KEY, or the Claude Code CLI)
python semantic/engine.py '{"measures": ["nrr"], "group_by": ["region"], "period": {"start": "2025-01-01", "end": "2025-12-31"}}'
```

The dbt project runs on DuckDB locally. The `snowflake` target in `profiles.yml` runs the same models, and cross-database date logic uses `dbt.datediff`. `orchestration/legal_research_dag.py` is the Airflow schedule: bronze tests gate silver, silver gates gold, and gold gates the Power BI export, agent regression eval and ML scoring. `CLAUDE.md` and `.claude/skills/` hold the working rules for coding agents: adding a governed measure end to end, and reviewing agent-written SQL.

## Results

[reports/results.md](reports/results.md) is regenerated on every run.
