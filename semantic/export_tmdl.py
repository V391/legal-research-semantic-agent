"""Generate the Power BI / Fabric semantic model (TMDL, PBIP folder layout) from the same definitions.

Tables and columns come from the gold dbt contracts (models/gold/_gold.yml), measures from
semantic/semantic_model.yml (the `dax` twin of each governed SQL measure). Partitions are Direct Lake on
the Fabric Lakehouse that holds the gold tables, so Power BI reads the same Delta tables dbt builds.

Run: python semantic/export_tmdl.py  ->  powerbi/LegalResearch.SemanticModel/
Also checks that every column a DAX expression references exists in the gold contracts.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "powerbi" / "LegalResearch.SemanticModel"
TABLES = ["dim_date", "dim_firm", "dim_product", "dim_practice_area", "bridge_firm_practice_area",
          "fct_arr_monthly", "fct_usage_weekly", "fct_renewals"]
TYPES = {"varchar": "string", "date": "dateTime", "boolean": "boolean", "integer": "int64", "bigint": "int64",
         "double": "double"}
FORMATS = {"usd": "\\$#,0", "int": "#,0", "pct": "0.0%", "dec1": "#,0.0"}
RELATIONSHIPS = [  # from (many) -> to (one), cross filter
    ("fct_arr_monthly", "firm_sk", "dim_firm", "firm_sk", "oneDirection"),
    ("fct_arr_monthly", "product_id", "dim_product", "product_id", "oneDirection"),
    ("fct_arr_monthly", "month_end_key", "dim_date", "date_key", "oneDirection"),
    ("fct_usage_weekly", "firm_sk", "dim_firm", "firm_sk", "oneDirection"),
    ("fct_usage_weekly", "product_id", "dim_product", "product_id", "oneDirection"),
    ("fct_renewals", "firm_sk", "dim_firm", "firm_sk", "oneDirection"),
    ("fct_renewals", "product_id", "dim_product", "product_id", "oneDirection"),
    ("bridge_firm_practice_area", "practice_area_id", "dim_practice_area", "practice_area_id", "oneDirection"),
]


def tag(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"legal-research/{name}"))


def dtype(t: str) -> str:
    return "decimal" if t.startswith("decimal") else TYPES[t]


def main() -> int:
    gold = {m["name"]: m for m in yaml.safe_load((ROOT / "models" / "gold" / "_gold.yml").read_text(encoding="utf-8"))["models"]}
    sem = yaml.safe_load((ROOT / "semantic" / "semantic_model.yml").read_text(encoding="utf-8"))
    (OUT / "definition" / "tables").mkdir(parents=True, exist_ok=True)

    cols = {t: {c["name"] for c in gold[t]["columns"]} for t in TABLES}
    problems = []
    for name, m in sem["measures"].items():
        if not m.get("dax"):
            problems.append(f"measure {name} has no DAX twin")
        for t, c in re.findall(r"(\w+)\[(\w+)\]", m.get("dax", "") + m.get("dax_allocated", "")):
            if t in cols and c not in cols[t]:
                problems.append(f"{name}: {t}[{c}] is not a gold column")
            elif t not in cols and t not in ("",):
                problems.append(f"{name}: unknown table {t}")
    if problems:
        print("\n".join(problems))
        return 1

    for t in TABLES:
        m = gold[t]
        lines = [f"/// {' '.join(str(m.get('description', '')).split())}", f"table {t}", f"\tlineageTag: {tag(t)}", ""]
        for c in m["columns"]:
            lines += [f"\t/// {c.get('description', '')}", f"\tcolumn {c['name']}", f"\t\tdataType: {dtype(c['data_type'])}"]
            if c["data_type"].startswith("decimal"):
                lines.append("\t\tformatString: #,0.00")
            hidden = c["name"].endswith(("_sk", "_key")) or c["name"] in ("account_id",) and t.startswith("fct")
            if hidden:
                lines.append("\t\tisHidden")
            lines += [f"\t\tlineageTag: {tag(t + '.' + c['name'])}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {c['name']}", ""]
        if t == "fct_arr_monthly":   # governed measures live on the fact they read most
            variants = []
            for name, ms in sem["measures"].items():
                variants.append((name, ms["label"], ms["dax"], ms["description"], ms))
                if ms.get("dax_allocated"):
                    variants.append((name + "_allocated", ms["label"] + " (Practice Area Allocated)", ms["dax_allocated"],
                                     ms["description"] + " Weighted by the practice area bridge; use when slicing by practice area.", ms))
            for key, label, dax, desc, ms in variants:
                body = dax.strip().splitlines()
                lines.append(f"\t/// {desc}")
                if len(body) == 1:
                    lines.append(f"\tmeasure '{label}' = {body[0]}")
                else:
                    lines.append(f"\tmeasure '{label}' = ```")
                    lines += [f"\t\t\t{b}" for b in body]
                    lines.append("\t\t\t```")
                lines += [f"\t\tformatString: {FORMATS[ms['format']]}", f"\t\tdisplayFolder: {ms['folder']}",
                          f"\t\tlineageTag: {tag('measure.' + key)}", ""]
        lines += [f"\tpartition {t} = entity", "\t\tmode: directLake", "\t\tsource",
                  f"\t\t\tentityName: {t}", "\t\t\tschemaName: gold", "\t\t\texpressionSource: DatabaseQuery", ""]
        (OUT / "definition" / "tables" / f"{t}.tmdl").write_text("\n".join(lines), encoding="utf-8")

    rel = []
    for f, fc, to, tc, xf in RELATIONSHIPS:
        rel += [f"relationship {tag(f + fc + to)}", f"\tfromColumn: {f}.{fc}", f"\ttoColumn: {to}.{tc}"]
        if xf != "oneDirection":
            rel.append(f"\tcrossFilteringBehavior: {xf}")
        rel.append("")
    (OUT / "definition" / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")
    (OUT / "definition" / "expressions.tmdl").write_text(
        "/// Fabric Lakehouse SQL endpoint holding the gold Delta tables built by dbt\n"
        "expression DatabaseQuery =\n\t\tlet\n"
        "\t\t\tdatabase = Sql.Database(\"<workspace>.datawarehouse.fabric.microsoft.com\", \"<lakehouse-id>\")\n"
        "\t\tin\n\t\t\tdatabase\n\tlineageTag: " + tag("DatabaseQuery") + "\n", encoding="utf-8")
    (OUT / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-GB\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tsourceQueryCulture: en-GB\n\tdiscourageImplicitMeasures\n\n"
        + "".join(f"ref table {t}\n" for t in TABLES), encoding="utf-8")
    (OUT / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1604\n", encoding="utf-8")
    (OUT / "definition.pbism").write_text('{\n  "version": "4.0",\n  "settings": {}\n}\n', encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(TABLES)} tables, {len(sem['measures'])} measures, {len(RELATIONSHIPS)} relationships")
    return 0


if __name__ == "__main__":
    sys.exit(main())
