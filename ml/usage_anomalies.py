"""Usage anomalies: find firm-product-weeks where usage broke from its own pattern.

Two kinds matter to the business: search spikes (bulk scraping or shared credentials, a licence
compliance issue) and tracking gaps (an instrumentation outage that makes a healthy firm look like it is
churning). The simulator plants both and records where, so detectors are scored on precision and recall.

baseline  static rule per series: flag a week above `hi` x or below `lo` x the series mean.
detector  per seat rates divided by a market-wide seasonal index (holiday weeks dip for everyone),
          compared with the series' own trailing 8 week median on a log scale, robust z-score by MAD,
          with a minimum expected volume so tiny series do not fire on noise.

Both get their thresholds tuned on 2024 weeks only. Reported numbers are on 2025 weeks.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SPLIT = pd.Timestamp("2025-01-01")


def load() -> tuple[pd.DataFrame, pd.Series]:
    con = duckdb.connect(str(ROOT / "warehouse" / "dev.duckdb"), read_only=True)
    u = con.execute("select account_id, product_id, week_start, licensed_seats, active_users, searches "
                    "from gold.fct_usage_weekly order by account_id, product_id, week_start").df()
    t = con.execute("select distinct account_id, product_id, cast(week_start as date) as week_start, true as is_anomaly "
                    "from truth.usage_anomalies").df()
    u["week_start"] = pd.to_datetime(u.week_start)
    t["week_start"] = pd.to_datetime(t.week_start)
    y = u.merge(t, how="left", on=["account_id", "product_id", "week_start"]).is_anomaly.fillna(False).astype(bool)
    return u, y


def baseline_parts(u: pd.DataFrame) -> dict:
    keys = [u.account_id, u.product_id]
    return {c: u[c] / u[c].groupby(keys).transform("mean").clip(lower=1e-9) for c in ("searches", "active_users")}


def baseline(parts: dict, hi: float, lo: float) -> pd.Series:
    return pd.concat([(r > hi) | (r < lo) for r in parts.values()], axis=1).any(axis=1)


def detector_parts(u: pd.DataFrame) -> dict:
    keys = [u.account_id, u.product_id]
    out = {}
    for col in ("searches", "active_users"):
        rate = (u[col] + 0.5) / u.licensed_seats
        rel = rate / rate.groupby(keys).transform("median")
        season = rel.groupby(u.week_start).transform("median")          # market-wide weekly index
        adj = np.log(rate / season)
        trail = adj.groupby(keys).transform(lambda s: s.shift(1).rolling(8, min_periods=4).median())
        resid = adj - trail
        mad = resid.groupby(keys).transform(lambda s: (s - s.median()).abs().median()) * 1.4826
        expected = np.exp(trail) * season * u.licensed_seats                # expected count this week
        out[col] = pd.DataFrame({"z": resid / mad.clip(lower=0.05), "resid": resid, "expected": expected})
    return out


def detector(parts: dict, z_up: float, ratio_up: float, ratio_down: float, min_users: float) -> pd.Series:
    s, a = parts["searches"], parts["active_users"]
    # spike: searches jump far above the series' own seasonal expectation
    spike = (s.z > z_up) & (s.resid > np.log(ratio_up)) & (s.expected >= 10)
    # gap: everything collapses at once, in a series big enough that a quiet week is not just chance
    gap = (s.resid < -np.log(ratio_down)) & (a.resid < -np.log(ratio_down)) & (a.expected >= min_users)
    return (spike | gap).fillna(False)


def metrics(flags: pd.Series, y: pd.Series) -> dict:
    tp = int((flags & y).sum())
    fl = int(flags.sum())
    p, r = tp / max(fl, 1), tp / max(int(y.sum()), 1)
    return {"flagged": fl, "true_positives": tp, "anomalies": int(y.sum()), "precision": round(p, 3),
            "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3)}


def tune(make, grid: dict, tr: pd.Series, y: pd.Series) -> dict:
    best, best_f1 = None, -1
    for vals in itertools.product(*grid.values()):
        params = dict(zip(grid, vals))
        f1 = metrics(make(**params)[tr], y[tr])["f1"]
        if f1 > best_f1:
            best, best_f1 = params, f1
    return best


def main() -> dict:
    u, y = load()
    tr, te = u.week_start < SPLIT, u.week_start >= SPLIT
    bp, dp = baseline_parts(u), detector_parts(u)
    b_par = tune(lambda hi, lo: baseline(bp, hi, lo), {"hi": [2, 3, 4, 6, 8], "lo": [0.05, 0.1, 0.2, 0.3]}, tr, y)
    d_par = tune(lambda **k: detector(dp, **k),
                 {"z_up": [2, 3, 4, 5, 6], "ratio_up": [2, 3, 4, 6], "ratio_down": [2, 3, 5, 8],
                  "min_users": [2, 3, 5, 8]}, tr, y)
    return {
        "series": int(u.groupby(["account_id", "product_id"]).ngroups), "weeks_scored_2025": int(te.sum()),
        "baseline_static_threshold": {"params": b_par, "test_2025": metrics(baseline(bp, **b_par)[te], y[te])},
        "detector_seasonal_robust_z": {"params": d_par, "test_2025": metrics(detector(dp, **d_par)[te], y[te])},
    }


if __name__ == "__main__":
    res = main()
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "usage_anomalies.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))

