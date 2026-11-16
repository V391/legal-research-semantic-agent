"""Airflow DAG for the production schedule: the same steps run_all.py runs locally, split into tasks
so a failure stops downstream consumers (Power BI refresh, agent, ML scoring) from reading a bad build.

Daily at 06:00 UTC, after the CPQ, CRM and usage extracts have landed in object storage.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

REPO = "/opt/airflow/repos/legal-research-semantic-agent"
DBT = f"cd {REPO} && dbt --no-use-colors"

with DAG(
    dag_id="legal_research_semantic",
    start_date=datetime(2026, 1, 1),
    schedule="0 6 * * *",
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10), "owner": "data-ai-engineering"},
    tags=["medallion", "semantic", "agent"],
) as dag:
    land_bronze = BashOperator(task_id="land_bronze", bash_command=f"cd {REPO} && python load_raw.py --db $WAREHOUSE")
    source_tests = BashOperator(task_id="bronze_source_tests", bash_command=f"{DBT} test --select source:bronze")
    silver = BashOperator(task_id="build_silver", bash_command=f"{DBT} build --select models/silver")
    gold = BashOperator(task_id="build_gold", bash_command=f"{DBT} build --select models/gold tests --exclude path:tests/answer_key")
    docs_gate = BashOperator(task_id="docs_gate", bash_command=f"cd {REPO} && python checks/check_docs.py")
    tmdl = BashOperator(task_id="export_semantic_model", bash_command=f"cd {REPO} && python semantic/export_tmdl.py")
    agent_eval = BashOperator(task_id="agent_regression_eval", bash_command=f"cd {REPO} && python eval/run_eval.py")
    ml_score = BashOperator(task_id="score_renewal_risk_and_anomalies",
                            bash_command=f"cd {REPO} && python ml/renewal_risk.py && python ml/usage_anomalies.py")

    land_bronze >> source_tests >> silver >> gold >> docs_gate >> tmdl
    gold >> [agent_eval, ml_score]
