"""Renewal risk: which contract lines will not renew, scored 90 days before the renewal date.

Features come from gold.ml_renewal_features (point in time, built in dbt). Out of time split: train on
renewals before 2025-07-01, test on renewals from 2025-07-01. The model must beat the rule Customer Success
already uses (rank by low seat utilization) on the held out half year, or it is not worth shipping.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
SPLIT = "2025-07-01"
NUM = ["arr_expiring_usd", "term_months", "tenure_months", "has_ai_assistant", "products_held", "firm_arr_usd",
       "product_utilization", "product_utilization_trend", "firm_utilization", "firm_utilization_trend",
       "firm_actions_per_seat_week", "firm_ai_prompts_per_seat_week"]
CAT = ["segment", "region", "product_line", "is_addon"]


def capture(y: np.ndarray, arr: np.ndarray, score: np.ndarray, top: float = 0.2) -> float:
    """Share of churned ARR found in the riskiest `top` share of renewals."""
    k = int(np.ceil(len(score) * top))
    idx = np.argsort(-score)[:k]
    return float((arr[idx] * y[idx]).sum() / (arr * y).sum())


def main() -> dict:
    con = duckdb.connect(str(ROOT / "warehouse" / "dev.duckdb"), read_only=True)
    df = con.execute("select * from gold.ml_renewal_features").df()
    df["arr_expiring_usd"] = df.arr_expiring_usd.astype(float)
    df["firm_arr_usd"] = df.firm_arr_usd.astype(float)
    df["is_addon"] = df.is_addon.astype(str)
    df["log_arr"] = np.log1p(df.arr_expiring_usd)
    train = df[df.renewal_date < pd.Timestamp(SPLIT)]
    test = df[df.renewal_date >= pd.Timestamp(SPLIT)]
    ytr, yte = train.churned.to_numpy(), test.churned.to_numpy()

    pre = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT),
    ])
    usage = ["product_utilization", "product_utilization_trend", "firm_utilization", "firm_utilization_trend", "has_ai_assistant"]
    pre_usage = ColumnTransformer([("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), usage)])
    candidates = {
        "logistic regression, usage features": make_pipeline(pre_usage, LogisticRegression(max_iter=2000, C=0.3)),
        "logistic regression": make_pipeline(pre, LogisticRegression(max_iter=2000, C=0.5)),
        "gradient boosting": make_pipeline(pre, HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                                                                max_iter=200, random_state=0)),
    }
    # Folds split by firm: a firm's lines churn together, so a row-level split leaks the answer across folds.
    cv = StratifiedGroupKFold(5, shuffle=True, random_state=0)
    cv_auc = {k: float(cross_val_score(m, train, ytr, cv=cv, groups=train.account_id, scoring="roc_auc").mean())
              for k, m in candidates.items()}
    chosen = max(cv_auc, key=cv_auc.get)          # chosen on training data only
    test_auc_all = {k: float(roc_auc_score(yte, m.fit(train, ytr).predict_proba(test)[:, 1])) for k, m in candidates.items()}
    model = candidates[chosen].fit(train, ytr)
    p = model.predict_proba(test)[:, 1]

    rule = -test.product_utilization.fillna(test.product_utilization.median()).to_numpy()
    arr = test.arr_expiring_usd.to_numpy()
    out = {
        "train_renewals": int(len(train)), "test_renewals": int(len(test)),
        "test_churn_rate": float(yte.mean()), "cv_auc_train": cv_auc, "chosen": chosen,
        "test_auc_model": float(roc_auc_score(yte, p)),
        "test_auc_every_candidate": test_auc_all,
        "test_auc_rule_low_utilization": float(roc_auc_score(yte, rule)),
        "churned_arr_in_top20pct_model": capture(yte, arr, p),
        "churned_arr_in_top20pct_rule": capture(yte, arr, rule),
        "test_churned_arr": float((arr * yte).sum()),
    }
    out["ship"] = ("model" if out["test_auc_model"] > out["test_auc_rule_low_utilization"]
                   and out["churned_arr_in_top20pct_model"] >= out["churned_arr_in_top20pct_rule"] else "rule")
    return out


if __name__ == "__main__":
    res = main()
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "renewal_risk.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
