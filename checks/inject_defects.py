"""Break the bronze feeds on purpose, one defect at a time, and prove the build stops.

For each defect: reload clean bronze into a scratch warehouse, apply the defect, run `dbt build` WITHOUT the
answer key tests (production has no answer key), and record which tests failed. A defect counts as caught
only if a production test fails. Results go to reports/defects.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from load_raw import load  # noqa: E402

DB = ROOT / "warehouse" / "defect.duckdb"

DEFECTS = [
    ("CPQ replays 5 contract bookings under new event ids",
     "insert into bronze.cpq_contract_events select * replace ('R' || event_id as event_id) "
     "from bronze.cpq_contract_events where event_type = 'contract_created' order by event_id limit 5"),
    ("CPQ sends a week of contract values in major units instead of minor units",
     "update bronze.cpq_contract_events set tcv_minor = tcv_minor // 100 "
     "where event_type = 'contract_created' and event_ts >= timestamp '2025-06-01' and event_ts < timestamp '2025-06-08'"),
    ("FX feed misses INR for one month",
     "delete from bronze.fx_rates_monthly where currency = 'INR' and month_start = date '2025-03-01'"),
    ("CPQ amends a contract that was never booked",
     "insert into bronze.cpq_contract_events select * replace ('X' || event_id as event_id, 'C999999' as contract_id) "
     "from bronze.cpq_contract_events where event_type = 'amendment' order by event_id limit 1"),
    ("CRM starts sending a new account type (partner sandbox)",
     "update bronze.crm_account_changes set account_type = 'partner' where account_id = "
     "(select min(account_id) from bronze.crm_account_changes where account_type = 'customer')"),
    ("Practice focus survey saved with percentages not adding to 100",
     "update bronze.crm_practice_focus set focus_pct = focus_pct + 10 where account_id = "
     "(select min(account_id) from bronze.crm_practice_focus)"),
    ("Usage restatement doubles a week's counts",
     "update bronze.product_usage_weekly set active_users = active_users * 2, searches = searches * 2 "
     "where week_start = date '2025-05-05'"),
    ("CPQ books a contract that ends before it starts",
     "update bronze.cpq_contract_events set end_date = start_date - interval 1 month where contract_id = "
     "(select min(contract_id) from bronze.cpq_contract_events where start_date >= date '2025-01-01')"),
]


def dbt_exe() -> str:
    scripts = Path(sys.executable).parent
    return next((str(scripts / n) for n in ("dbt.exe", "dbt") if (scripts / n).exists()), "dbt")


def main() -> int:
    env = {**__import__("os").environ, "DBT_PROFILES_DIR": str(ROOT)}
    rows = []
    for name, sql in DEFECTS:
        DB.unlink(missing_ok=True)
        load(str(DB), str(ROOT / "data"))
        con = duckdb.connect(str(DB))
        con.execute(sql)
        con.close()
        r = subprocess.run([dbt_exe(), "build", "--target", "defect", "--exclude", "path:tests/answer_key",
                            "--target-path", "target_defect"],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        res = json.loads((ROOT / "target_defect" / "run_results.json").read_text(encoding="utf-8"))
        failed = sorted({x["unique_id"].split(".")[2] for x in res["results"] if x["status"] in ("fail", "error")})
        rows.append({"defect": name, "caught": bool(failed) and r.returncode != 0, "failed": failed})
        print(f"{'CAUGHT' if rows[-1]['caught'] else 'MISSED'}  {name}: {', '.join(failed[:4])}", flush=True)
    md = ["# Injected defects", "",
          "Each defect is applied alone to clean bronze data, then `dbt build` runs without the answer key tests.", "",
          "| Defect | Caught | Failing tests |", "|---|---|---|"]
    md += [f"| {r['defect']} | {'yes' if r['caught'] else 'NO'} | {', '.join(f'`{t}`' for t in r['failed'][:4])} |" for r in rows]
    caught = sum(r["caught"] for r in rows)
    md += ["", f"**{caught} of {len(rows)} caught.**", ""]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "defects.md").write_text("\n".join(md), encoding="utf-8")
    (ROOT / "reports" / "defects.json").write_text(json.dumps({"caught": caught, "total": len(rows), "rows": rows}, indent=1))
    return 0 if caught == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
