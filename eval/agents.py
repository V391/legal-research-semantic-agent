"""Two agents that answer the same business question with the same model over the same warehouse.

governed  sees the semantic model catalog and answers with a query spec. It cannot write SQL.
baseline  sees the gold star schema with every table and column description from dbt, and writes SQL.

Both get one retry when their query fails, with the error message. Each returns the result table that
would be shown to the user, plus the trace (prompts, responses, SQL) for audit.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from semantic.engine import SemanticError, catalog, run as run_spec

ROOT = Path(__file__).resolve().parents[1]

GOVERNED_SYSTEM = """You answer business questions for a legal research subscription company using its governed semantic layer.
You cannot write SQL. You answer by emitting one query spec that the semantic layer compiles and runs.
The result table of your query is shown to the user as the answer, so ask for exactly what answers the question.

Spec format (JSON):
{{"measures": ["<measure>", ...], "group_by": ["<dimension>", ...], "filters": {{"<dimension>": ["<value>", ...]}},
  "as_of": "YYYY-MM-DD"}}                        for snapshot measures at one month end
  or "period": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}   for usage, renewals and retention measures,
                                                     or snapshot measures grouped by month_end
group_by, filters are optional. Filter values must match the listed dimension values exactly.

{catalog}

Respond with only the JSON spec, no prose, no code fences."""

BASELINE_SYSTEM = """You answer business questions for a legal research subscription company by writing one DuckDB SQL query
over its analytics warehouse (schema `gold`, a documented star schema built with dbt).
The result of your query is shown to the user as the answer, so return exactly the rows and values that answer the question.

{schema}

Respond with only a JSON object {{"sql": "<one DuckDB SELECT statement>"}}, no prose, no code fences."""


def gold_schema_doc() -> str:
    """Every gold table and column with its dbt description and type: what a documented warehouse offers."""
    spec = yaml.safe_load((ROOT / "models" / "gold" / "_gold.yml").read_text(encoding="utf-8"))
    out = []
    for m in spec["models"]:
        out.append(f"## gold.{m['name']}\n{' '.join(str(m.get('description', '')).split())}")
        for c in m["columns"]:
            out.append(f"- {c['name']} {c.get('data_type', '')}: {c.get('description', '')}")
        out.append("")
    return "\n".join(out)


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in the response")
    return json.loads(t[start:end + 1])


class Agent:
    name = ""

    def __init__(self, con: duckdb.DuckDBPyConnection, llm):
        self.con = con
        self.llm = llm          # callable(system, user, key) -> text (live or replayed)

    def system(self) -> str:
        raise NotImplementedError

    def execute(self, parsed: dict) -> tuple[pd.DataFrame, str]:
        raise NotImplementedError

    def answer(self, qid: str, question: str, rep: int = 0) -> dict:
        system = self.system()
        user = f"Question: {question}"
        trace = []
        for attempt in (1, 2):
            text = self.llm(system, user, f"{self.name}:{qid}:{attempt}" + (f":r{rep}" if rep else ""))
            step = {"attempt": attempt, "response": text}
            trace.append(step)
            try:
                parsed = parse_json(text)
                df, sql = self.execute(parsed)
                step["sql"] = sql
                return {"ok": True, "result": df, "trace": trace, "attempts": attempt}
            except Exception as e:  # noqa: BLE001  the error goes back to the model, as a user would see it
                step["error"] = f"{type(e).__name__}: {e}"[:600]
                user = (f"Question: {question}\n\nYour previous answer was:\n{text}\n\n"
                        f"It failed with:\n{step['error']}\n\nTry again.")
        return {"ok": False, "result": None, "trace": trace, "attempts": 2}


class GovernedAgent(Agent):
    name = "governed"

    def system(self) -> str:
        return GOVERNED_SYSTEM.format(catalog=catalog(self.con))

    def execute(self, parsed):
        return run_spec(parsed, self.con)


class BaselineAgent(Agent):
    name = "baseline"

    def system(self) -> str:
        return BASELINE_SYSTEM.format(schema=gold_schema_doc())

    def execute(self, parsed):
        sql = parsed["sql"]
        if not re.match(r"^\s*(with|select)\b", sql, re.I) or ";" in sql.strip().rstrip(";"):
            raise ValueError("only a single SELECT statement is allowed")
        return self.con.execute(sql).df(), sql


__all__ = ["GovernedAgent", "BaselineAgent", "SemanticError"]
