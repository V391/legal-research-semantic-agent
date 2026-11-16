"""Compile a governed query spec into SQL over the gold star schema, and run it.

A spec names measures, never tables or formulas:

    {"measures": ["arr"], "group_by": ["segment"], "filters": {"country": ["India"]}, "as_of": "2025-12-31"}
    {"measures": ["nrr", "grr"], "period": {"start": "2025-01-01", "end": "2025-12-31"}}

The engine owns the joins (as-was firm versions, the weighted practice area bridge), the date logic
(snapshot vs flow vs cohort) and the formulas. Anything that would produce a wrong number, such as
summing ARR across months or counting firms through the practice area bridge, is refused with a
message saying what to do instead.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL = yaml.safe_load((ROOT / "semantic" / "semantic_model.yml").read_text(encoding="utf-8"))


class SemanticError(ValueError):
    """The spec cannot be answered as written. The message says why and how to fix it."""


@dataclass
class Compiled:
    sql: str
    family: str
    measures: list[str]
    dimensions: list[str]


def _d(s: str, field: str) -> date:
    try:
        return date.fromisoformat(str(s))
    except ValueError as e:
        raise SemanticError(f"{field} must be an ISO date (YYYY-MM-DD), got {s!r}") from e


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _lit(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def compile_spec(spec: dict) -> Compiled:
    if not isinstance(spec, dict):
        raise SemanticError("spec must be a JSON object")
    unknown = set(spec) - {"measures", "group_by", "filters", "as_of", "period", "order_by", "limit"}
    if unknown:
        raise SemanticError(f"unknown spec keys {sorted(unknown)}")
    measures = spec.get("measures") or []
    if isinstance(measures, str):
        measures = [measures]
    if not measures:
        raise SemanticError("give at least one measure")
    for m in measures:
        if m not in MODEL["measures"]:
            raise SemanticError(f"unknown measure {m!r}. Known: {sorted(MODEL['measures'])}")
    families = {MODEL["measures"][m]["family"] for m in measures}
    if len(families) > 1:
        raise SemanticError(f"measures {measures} come from different families {sorted(families)}; ask one family per query")
    family = families.pop()

    group_by = spec.get("group_by") or []
    if isinstance(group_by, str):
        group_by = [group_by]
    filters = spec.get("filters") or {}
    dims_used = list(dict.fromkeys([*group_by, *filters]))
    for dname in dims_used:
        dim = MODEL["dimensions"].get(dname)
        if dim is None:
            raise SemanticError(f"unknown dimension {dname!r}. Known: {sorted(MODEL['dimensions'])}")
        if family not in dim.get("families", list(MODEL["families"])):
            raise SemanticError(f"dimension {dname!r} is not available for {family} measures")
    allocate = "practice_area" in dims_used
    if allocate:
        blocked = [m for m in measures if MODEL["measures"][m].get("allocatable", True) is False]
        if blocked:
            raise SemanticError(f"{blocked} cannot be split by practice area: a firm belongs to several practice areas, "
                                "so firm counts and ratios do not allocate. Use arr or seats by practice_area instead.")
    for m in measures:
        if MODEL["measures"][m].get("product_filter", True) is False and {"product", "product_line"} & set(dims_used):
            raise SemanticError(f"{m} is defined across all products; do not filter or group it by product")

    where: list[str] = []
    for dname, vals in filters.items():
        vals = vals if isinstance(vals, list) else [vals]
        if not vals:
            raise SemanticError(f"filter {dname!r} has no values")
        where.append(f"{MODEL['dimensions'][dname]['column']} in ({', '.join(_lit(v) for v in vals)})")

    w = "b.allocation_weight" if allocate else "1"
    sel_dims = [f"{MODEL['dimensions'][g]['column']} as {g}" for g in group_by]
    sel_meas = [f"{MODEL['measures'][m]['sql'].format(w=w)} as {m}" for m in measures]
    bridge = ("join gold.bridge_firm_practice_area b on b.account_id = d.account_id\n"
              "join gold.dim_practice_area pa on pa.practice_area_id = b.practice_area_id\n") if allocate else ""

    if family == "snapshot":
        if "as_of" in spec and "period" in spec:
            raise SemanticError("give as_of or period, not both")
        if "as_of" in spec:
            d = _d(spec["as_of"], "as_of")
            if _month_end(d) != d:
                raise SemanticError(f"snapshot measures exist at month ends only; use {_month_end(d).isoformat()}")
            where.append(f"f.month_end = date '{d.isoformat()}'")
        elif "period" in spec:
            if "month_end" not in group_by:
                raise SemanticError("ARR, seats and firm counts are snapshots and cannot be summed over a period. "
                                    "Use as_of for one month end, or group_by month_end to see each month.")
            s, e = _d(spec["period"].get("start"), "period.start"), _d(spec["period"].get("end"), "period.end")
            where.append(f"f.month_end between date '{s.isoformat()}' and date '{e.isoformat()}'")
        else:
            raise SemanticError("snapshot measures need as_of (a month end) or a period grouped by month_end")
        frm = ("from gold.fct_arr_monthly f\njoin gold.dim_firm d on d.firm_sk = f.firm_sk\n"
               "join gold.dim_product p on p.product_id = f.product_id\n" + bridge)
    elif family in ("usage", "renewals"):
        if "period" not in spec:
            raise SemanticError(f"{family} measures need a period with start and end dates")
        s, e = _d(spec["period"].get("start"), "period.start"), _d(spec["period"].get("end"), "period.end")
        alias, col = ("u", "week_start") if family == "usage" else ("r", "renewal_date")
        fact = "fct_usage_weekly" if family == "usage" else "fct_renewals"
        where.append(f"{alias}.{col} between date '{s.isoformat()}' and date '{e.isoformat()}'")
        frm = (f"from gold.{fact} {alias}\njoin gold.dim_firm d on d.firm_sk = {alias}.firm_sk\n"
               f"join gold.dim_product p on p.product_id = {alias}.product_id\n"
               f"join gold.dim_date dd on dd.date_day = {alias}.{col}\n" + bridge)
    else:  # cohort
        if "period" not in spec:
            raise SemanticError("retention measures need a period; the start snapshot is the month end before period.start")
        s, e = _d(spec["period"].get("start"), "period.start"), _d(spec["period"].get("end"), "period.end")
        start_snap = date(s.year, s.month, 1) - timedelta(days=1)
        end_snap = e if _month_end(e) == e else date(e.year, e.month, 1) - timedelta(days=1)
        if start_snap < date.fromisoformat("2024-01-31"):
            raise SemanticError(f"no ARR snapshot before 2024-01-31; a retention period must start in February 2024 or later")
        prod_where = [x for x in where if x.startswith("p.")]
        firm_where = [x for x in where if not x.startswith("p.")]
        pw = (" and " + " and ".join(prod_where)) if prod_where else ""
        frm = (
            "from (\n"
            "  select coalesce(s.account_id, e.account_id) as account_id, coalesce(s.firm_sk, e.firm_sk) as firm_sk,\n"
            "         coalesce(s.arr, 0) as start_arr, coalesce(e.arr, 0) as end_arr\n"
            f"  from (select f.account_id, any_value(f.firm_sk) as firm_sk, sum(f.arr_usd) as arr from gold.fct_arr_monthly f"
            f" join gold.dim_product p on p.product_id = f.product_id where f.month_end = date '{start_snap.isoformat()}'{pw} group by 1) s\n"
            f"  full outer join (select f.account_id, any_value(f.firm_sk) as firm_sk, sum(f.arr_usd) as arr from gold.fct_arr_monthly f"
            f" join gold.dim_product p on p.product_id = f.product_id where f.month_end = date '{end_snap.isoformat()}'{pw} group by 1) e\n"
            "  on e.account_id = s.account_id\n) c\njoin gold.dim_firm d on d.firm_sk = c.firm_sk\n"
        )
        where = firm_where

    sql = "select " + ", ".join([*sel_dims, *sel_meas]) + "\n" + frm
    if where:
        sql += "where " + "\n  and ".join(where) + "\n"
    if group_by:
        sql += "group by " + ", ".join(str(i + 1) for i in range(len(group_by))) + "\n"
        order = spec.get("order_by")
        sql += f"order by {order if order in (*measures, *group_by) else ', '.join(str(i + 1) for i in range(len(group_by)))}"
        sql += " desc\n" if order in measures else "\n"
    if spec.get("limit"):
        sql += f"limit {int(spec['limit'])}\n"
    return Compiled(sql=sql, family=family, measures=measures, dimensions=group_by)


def run(spec: dict, con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, str]:
    c = compile_spec(spec)
    return con.execute(c.sql).df(), c.sql


def catalog(con: duckdb.DuckDBPyConnection | None = None) -> str:
    """The text an agent sees: measures, dimensions (with their values) and the spec format."""
    lines = [f"# {MODEL['name']} semantic model", MODEL["description"], "", "## Measure families"]
    for k, v in MODEL["families"].items():
        lines.append(f"- {k}: {' '.join(v['description'].split())}")
    lines += ["", "## Measures (name | family | definition)"]
    for k, v in MODEL["measures"].items():
        lines.append(f"- {k} | {v['family']} | {v['description']}")
    lines += ["", "## Dimensions (usable in group_by and filters)"]
    for k, v in MODEL["dimensions"].items():
        fams = ", ".join(v.get("families", list(MODEL["families"])))
        vals = ""
        if con is not None and k in ("segment", "country", "region", "product", "product_line", "practice_area"):
            col = v["column"].split(".")[1]
            table = {"d": "gold.dim_firm", "p": "gold.dim_product", "pa": "gold.dim_practice_area"}[v["column"].split(".")[0]]
            vals = "; values: " + ", ".join(r[0] for r in con.execute(f"select distinct {col} from {table} order by 1").fetchall())
        lines.append(f"- {k} ({fams}): {v['description']}{vals}")
    lines += ["", "## Data available", "- ARR snapshots: month ends 2024-01-31 to 2025-12-31.",
              "- Usage: weeks starting 2024-01-01 to 2025-12-22. Renewals: renewal dates up to 2025-12-01."]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    con = duckdb.connect(str(ROOT / "warehouse" / "dev.duckdb"), read_only=True)
    spec = json.loads(sys.argv[1])
    df, sql = run(spec, con)
    print(sql)
    print(df.to_string(index=False))
