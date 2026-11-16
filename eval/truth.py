"""Answer each golden question from the simulator's answer key, in pandas.

Shares nothing with dbt or the semantic engine except the spec vocabulary: the data comes from
data/truth (what the simulator knows really happened) and every formula is written again here.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "data" / "truth"


class Truth:
    def __init__(self) -> None:
        self.arr = pd.read_parquet(T / "arr_monthly.parquet")
        self.arr["month_end"] = pd.to_datetime(self.arr.month_end).dt.date
        self.ver = pd.read_parquet(T / "firm_versions.parquet")
        self.ver["valid_from"] = pd.to_datetime(self.ver.valid_from).dt.date
        self.ver["valid_to"] = self.ver.valid_to.map(lambda d: d if isinstance(d, date) else pd.Timestamp(d).date())
        self.w = pd.read_parquet(T / "practice_weights.parquet")
        self.pa = pd.read_parquet(T / "practice_areas.parquet")
        self.prod = pd.read_parquet(T / "products.parquet").rename(columns={"product_name": "product"})
        self.usage = pd.read_parquet(T / "usage_weekly.parquet")
        self.usage["week_start"] = pd.to_datetime(self.usage.week_start).dt.date
        self.ren = pd.read_parquet(T / "renewals.parquet")
        self.ren["renewal_date"] = pd.to_datetime(self.ren.renewal_date).dt.date

    # ---- helpers
    def attrs(self, df: pd.DataFrame, at: str) -> pd.DataFrame:
        """Firm attributes as they were on each row's own date."""
        m = df.merge(self.ver[["account_id", "segment", "country", "region", "account_owner", "valid_from", "valid_to"]],
                     on="account_id")
        m = m[(m.valid_from <= m[at]) & (m[at] < m.valid_to)]
        assert len(m) == len(df), "every row must find exactly one firm version"
        return m.drop(columns=["valid_from", "valid_to"])

    def enrich(self, df: pd.DataFrame, at: str, dims: set[str]) -> pd.DataFrame:
        df = self.attrs(df, at)
        if "product_id" in df:
            df = df.merge(self.prod[["product_id", "product", "product_line"]], on="product_id")
        if "practice_area" in dims:
            df = df.merge(self.w, on="account_id").merge(self.pa, on="practice_area_id")
        else:
            df = df.assign(weight=1.0)
        return df

    @staticmethod
    def _filter(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
        for k, v in filters.items():
            df = df[df[k].isin(v if isinstance(v, list) else [v])]
        return df

    @staticmethod
    def _out(df: pd.DataFrame, by: list[str], fn):
        if not by:
            return fn(df)
        return {" | ".join(str(x) for x in (k if isinstance(k, tuple) else (k,))): fn(g)
                for k, g in df.groupby(by if len(by) > 1 else by[0])}

    # ---- families
    def answer(self, spec: dict):
        m = spec["measures"][0]
        by = spec.get("group_by", [])
        f = spec.get("filters", {})
        dims = set(by) | set(f)
        if m in ("arr", "seats", "active_firms", "arr_per_firm", "ai_adoption_rate"):
            if "as_of" in spec:
                df = self.arr[self.arr.month_end == date.fromisoformat(spec["as_of"])]
            else:
                p = spec["period"]
                df = self.arr[(self.arr.month_end >= date.fromisoformat(p["start"])) & (self.arr.month_end <= date.fromisoformat(p["end"]))]
            df = self._filter(self.enrich(df, "month_end", dims), f)
            fns = {
                "arr": lambda g: (g.arr_usd * g.weight).sum(),
                "seats": lambda g: (g.seats * g.weight).sum(),
                "active_firms": lambda g: g.account_id.nunique(),
                "arr_per_firm": lambda g: g.arr_usd.sum() / g.account_id.nunique(),
                "ai_adoption_rate": lambda g: g[g.product_id == "P06"].account_id.nunique() / g.account_id.nunique(),
            }
            return self._out(df, by, fns[m])

        if m in ("nrr", "grr", "churned_logos", "logo_churn_rate", "new_logos", "starting_arr"):
            p = spec["period"]
            s = date.fromisoformat(p["start"]).replace(day=1) - timedelta(days=1)
            e = date.fromisoformat(p["end"])
            a0 = self.arr[self.arr.month_end == s].groupby("account_id").arr_usd.sum()
            a1 = self.arr[self.arr.month_end == e].groupby("account_id").arr_usd.sum()
            firms = pd.DataFrame({"start_arr": a0, "end_arr": a1}).fillna(0).reset_index(names="account_id")
            firms["at"] = [s if x > 0 else e for x in firms.start_arr]   # attributes at start; new logos at end
            df = self._filter(self.attrs(firms, "at"), f)
            fns = {
                "nrr": lambda g: g[g.start_arr > 0].end_arr.sum() / g.start_arr.sum(),
                "grr": lambda g: g[g.start_arr > 0][["start_arr", "end_arr"]].min(axis=1).sum() / g.start_arr.sum(),
                "churned_logos": lambda g: int(((g.start_arr > 0) & (g.end_arr == 0)).sum()),
                "logo_churn_rate": lambda g: ((g.start_arr > 0) & (g.end_arr == 0)).sum() / (g.start_arr > 0).sum(),
                "new_logos": lambda g: int(((g.start_arr == 0) & (g.end_arr > 0)).sum()),
                "starting_arr": lambda g: g.start_arr.sum(),
            }
            return self._out(df, by, fns[m])

        p = spec["period"]
        s, e = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if m in ("searches", "documents_viewed", "ai_prompts", "avg_weekly_active_users", "seat_utilization",
                 "searches_per_active_user"):
            df = self.usage[(self.usage.week_start >= s) & (self.usage.week_start <= e)]
            df = self._filter(self.enrich(df, "week_start", dims), f)
            df = df.assign(year_quarter=[f"{d.year}-Q{(d.month - 1) // 3 + 1}" for d in df.week_start],
                           calendar_year=[d.year for d in df.week_start])
            fns = {
                "searches": lambda g: (g.searches * g.weight).sum(),
                "documents_viewed": lambda g: (g.documents_viewed * g.weight).sum(),
                "ai_prompts": lambda g: (g.ai_prompts * g.weight).sum(),
                "avg_weekly_active_users": lambda g: (g.active_users * g.weight).sum() / g.week_start.nunique(),
                "seat_utilization": lambda g: (g.active_users * g.weight).sum() / (g.licensed_seats * g.weight).sum(),
                "searches_per_active_user": lambda g: (g.searches * g.weight).sum() / (g.active_users * g.weight).sum(),
            }
            return self._out(df, by, fns[m])

        df = self.ren[(self.ren.renewal_date >= s) & (self.ren.renewal_date <= e)]
        df = self._filter(self.enrich(df, "renewal_date", dims), f)
        fns = {
            "renewals_due": lambda g: len(g),
            "renewal_rate": lambda g: (g.outcome == "renewed").mean(),
            "arr_up_for_renewal": lambda g: g.arr_expiring_usd.sum(),
            "churned_arr_at_renewal": lambda g: g[g.outcome == "churned"].arr_expiring_usd.sum(),
        }
        return self._out(df, by, fns[m])
