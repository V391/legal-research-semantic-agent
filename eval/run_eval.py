"""Score the governed agent and the text-to-SQL baseline on the golden questions.

    python eval/run_eval.py --live        call the model, record every response to eval/runs/responses.jsonl
    python eval/run_eval.py               replay the recorded responses against a fresh build (what CI runs)

Before any agent runs, the reference run executes each question's spec through the semantic engine and
must match the answer key 40 of 40: otherwise the semantic layer itself is wrong and the eval stops.
Agents query warehouse/serve.duckdb, which holds the gold schema only (no silver, no answer key).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.agents import BaselineAgent, GovernedAgent  # noqa: E402
from eval.truth import Truth  # noqa: E402
from semantic.engine import run as run_spec  # noqa: E402

RUNS = ROOT / "eval" / "runs"
REL_TOL = 0.005


# ---------------- scoring ----------------
def _norm(v) -> str:
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip().lower()


def _num_match(v, t: float) -> bool:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    if v != v:  # NaN
        return False
    return any(abs(c - t) <= REL_TOL * abs(t) + 1e-9 for c in (v, v / 100))


def score(df: pd.DataFrame | None, truth) -> tuple[bool, str]:
    if df is None:
        return False, "no result"
    rows = [list(r) for r in df.itertuples(index=False)]
    if not isinstance(truth, dict):
        if len(rows) != 1:
            return False, f"expected one row, got {len(rows)}"
        ok = any(_num_match(x, truth) for x in rows[0])
        return ok, "" if ok else f"got {rows[0]}, truth {truth:,.4f}"
    misses = []
    for label, t in truth.items():
        hit = [r for r in rows if label.lower() in {_norm(x) for x in r}]
        if not hit:
            misses.append(f"{label}: missing")
        elif not any(_num_match(x, t) for x in hit[0]):
            misses.append(f"{label}: got {[x for x in hit[0] if not isinstance(x, str)]}, truth {t:,.4f}")
    return not misses, "; ".join(misses[:4])


# ---------------- LLM record / replay ----------------
class Recorder:
    def __init__(self, live: bool):
        self.live = live
        self.lock = threading.Lock()
        self.path = RUNS / "responses.jsonl"
        self.store = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                self.store[r["key"]] = r

    def __call__(self, system: str, user: str, key: str) -> str:
        sha = hashlib.sha256((system + "\n\n" + user).encode()).hexdigest()[:16]
        if not self.live:
            r = self.store.get(key)
            if r is None:
                raise KeyError(f"no recorded response for {key}; run with --live")
            return r["text"]
        if key in self.store and self.store[key].get("prompt_sha") == sha:
            return self.store[key]["text"]          # resume: same prompt already answered
        from eval.llm import complete
        for tries in range(3):
            try:
                out = complete(system, user)
                break
            except Exception:  # noqa: BLE001  transient CLI or network failure
                if tries == 2:
                    raise
        with self.lock:
            self.store[key] = {"key": key, "prompt_sha": sha, **out}
            self.save()
        return out["text"]

    def save(self) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(json.dumps(self.store[k]) for k in sorted(self.store)) + "\n", encoding="utf-8")


def build_serving_db(src: Path, dst: Path) -> None:
    dst.unlink(missing_ok=True)
    con = duckdb.connect(str(dst))
    con.execute(f"attach '{src.as_posix()}' as src (read_only)")
    con.execute("create schema gold")
    for (t,) in con.execute("select table_name from information_schema.tables where table_catalog = 'src' and table_schema = 'gold'").fetchall():
        con.execute(f"create table gold.{t} as select * from src.gold.{t}")
    con.execute("detach src")
    con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--reference-only", action="store_true")
    ap.add_argument("--repeats", type=int, default=3, help="independent runs per question and agent")
    a = ap.parse_args()

    questions = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    if a.ids:
        questions = [q for q in questions if q["id"] in a.ids]
    truth = Truth()
    serve = ROOT / "warehouse" / "serve.duckdb"
    build_serving_db(ROOT / "warehouse" / "dev.duckdb", serve)
    con = duckdb.connect(str(serve), read_only=True)

    # 1. reference run: the semantic layer itself must be right
    ref_fail = []
    for q in questions:
        q["truth"] = truth.answer(q["spec"])
        df, _ = run_spec(q["spec"], con.cursor())
        ok, why = score(df, q["truth"])
        if not ok:
            ref_fail.append(f"{q['id']}: {why}")
    print(f"reference (semantic engine, hand-written specs): {len(questions) - len(ref_fail)}/{len(questions)} match the answer key")
    if ref_fail:
        print("\n".join(ref_fail))
        return 1
    if a.reference_only:
        return 0

    # 2. agents
    rec = Recorder(a.live)
    results = []

    def one(q, agent_cls, rep):
        agent = agent_cls(con.cursor(), rec)
        out = agent.answer(q["id"], q["question"], rep)
        ok, why = score(out["result"], q["truth"])
        res = out["result"]
        return {"id": q["id"], "agent": agent.name, "run": rep + 1, "question": q["question"], "correct": ok,
                "why": why, "executed": out["ok"], "attempts": out["attempts"],
                "result": None if res is None else res.head(20).astype(str).to_dict(orient="records"),
                "trace": out["trace"]}

    jobs = [(q, cls, rep) for rep in range(a.repeats) for q in questions for cls in (GovernedAgent, BaselineAgent)]
    with ThreadPoolExecutor(a.workers if a.live else 1) as ex:
        for r in ex.map(lambda j: one(*j), jobs):
            results.append(r)
            print(f"run{r['run']} {r['id']} {r['agent']:9s} {'OK ' if r['correct'] else 'BAD'} {r['why'][:110]}", flush=True)
    if a.live:
        rec.save()

    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    summary = {}
    for name in ("governed", "baseline"):
        rs = [r for r in results if r["agent"] == name]
        per_q = {}
        for r in rs:
            per_q.setdefault(r["id"], []).append(r["correct"])
        summary[name] = {"answers": len(rs), "correct": sum(r["correct"] for r in rs),
                         "accuracy": round(sum(r["correct"] for r in rs) / len(rs), 3),
                         "questions_right_every_run": sum(all(v) for v in per_q.values()),
                         "questions_right_some_runs_only": sum(any(v) and not all(v) for v in per_q.values()),
                         "questions": len(per_q), "runs": a.repeats,
                         "executed_but_wrong": sum(r["executed"] and not r["correct"] for r in rs),
                         "failed_to_run": sum(not r["executed"] for r in rs),
                         "needed_retry": sum(r["attempts"] > 1 for r in rs)}
    (RUNS / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    write_report(results, summary, questions)
    print(json.dumps(summary, indent=1))
    return 0


def write_report(results: list, summary: dict, questions: list) -> None:
    by_q = {q["id"]: q for q in questions}
    md = ["# Agent evaluation", "",
          f"{summary['governed']['questions']} golden questions, {summary['governed']['runs']} independent runs each, "
          "same model for both agents. An answer is correct when the result table matches the answer key "
          f"within {REL_TOL:.1%}.", "",
          "| Question | Governed | Text-to-SQL |", "|---|---|---|"]
    for qid, q in by_q.items():
        cell = lambda a: "".join("✓" if r["correct"] else "✗" for r in sorted(  # noqa: E731
            (r for r in results if r["id"] == qid and r["agent"] == a), key=lambda r: r["run"]))
        md.append(f"| {qid} {q['question']} | {cell('governed')} | {cell('baseline')} |")
    md += ["", "## Every wrong answer", ""]
    for r in sorted(results, key=lambda r: (r["id"], r["agent"], r["run"])):
        if r["correct"]:
            continue
        last = r["trace"][-1]
        md += [f"### {r['id']} {r['agent']} run {r['run']}: {r['question']}", "",
               f"Truth: `{by_q[r['id']]['truth']}`. Got: {r['why']}", "",
               "```sql", (last.get("sql") or last.get("response", "")).strip(), "```", ""]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "agent_eval.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
