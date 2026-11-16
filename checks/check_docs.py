"""Fail if any gold model or column lacks a description, or any governed measure lacks a definition.

Descriptions are not decoration here: the text-to-SQL agent and Power BI users read them, and the semantic
catalog the governed agent reads is built from them.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    missing = []
    gold = yaml.safe_load((ROOT / "models" / "gold" / "_gold.yml").read_text(encoding="utf-8"))
    for m in gold["models"]:
        if not str(m.get("description", "")).strip():
            missing.append(m["name"])
        missing += [f"{m['name']}.{c['name']}" for c in m["columns"] if not str(c.get("description", "")).strip()]
    sql_models = {p.stem for p in (ROOT / "models" / "gold").glob("*.sql")}
    missing += [f"{s} (not in _gold.yml)" for s in sorted(sql_models - {m['name'] for m in gold['models']})]
    sem = yaml.safe_load((ROOT / "semantic" / "semantic_model.yml").read_text(encoding="utf-8"))
    for k, v in sem["measures"].items():
        for f in ("description", "sql", "dax", "family", "label"):
            if not str(v.get(f, "")).strip():
                missing.append(f"measure {k}.{f}")
    if missing:
        print("missing documentation:\n  " + "\n  ".join(missing))
        return 1
    print(f"docs ok: {len(gold['models'])} gold models, {sum(len(m['columns']) for m in gold['models'])} columns, "
          f"{len(sem['measures'])} measures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
