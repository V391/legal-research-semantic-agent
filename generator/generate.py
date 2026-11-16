"""Simulate a legal research subscription business and land its raw feeds.

Writes what the source systems would deliver (CPQ contract events, CRM change data capture,
CRM practice focus surveys, weekly product usage extracts, monthly FX) to data/landing/, and an
answer key computed here in plain Python to data/truth/. The answer key never goes through dbt,
so the warehouse and the semantic layer can be checked against it.

Everything is seeded: the same command always produces the same business.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261117
H0 = date(2024, 1, 1)            # reporting horizon start
H1 = date(2025, 12, 31)          # reporting horizon end
LAST_MONTH = date(2025, 12, 1)
AI_LAUNCH = date(2024, 7, 1)
N_FIRMS = 520

SEGMENTS = ["Global Law Firm", "Large Law", "Mid-size Law", "Small Law", "Corporate Legal", "Government"]
SEG_P = [0.06, 0.14, 0.28, 0.30, 0.14, 0.08]
SEG_SEATS = {"Global Law Firm": 300, "Large Law": 110, "Mid-size Law": 34, "Small Law": 7,
             "Corporate Legal": 22, "Government": 28}
SEG_DISCOUNT = {"Global Law Firm": 0.70, "Large Law": 0.80, "Mid-size Law": 0.90, "Small Law": 1.0,
                "Corporate Legal": 0.85, "Government": 0.75}
UPGRADE = {"Small Law": "Mid-size Law", "Mid-size Law": "Large Law", "Large Law": "Global Law Firm"}

# country: (currency, region, price index vs US list, share of firms)
COUNTRIES = {"United States": ("USD", "Americas", 1.00, 0.50), "United Kingdom": ("GBP", "EMEA", 0.95, 0.20),
             "Canada": ("CAD", "Americas", 0.90, 0.10), "India": ("INR", "APAC", 0.35, 0.20)}
FX_BASE = {"USD": 1.0, "GBP": 0.78, "CAD": 1.30, "INR": 74.0}
FX_DRIFT = {"USD": 0.0, "GBP": 0.0005, "CAD": 0.0008, "INR": 0.0030}   # monthly log drift (local per USD)

# product_id: (name, line, USD list price per seat per year, base activity logit, searches/wk, docs/wk, ai prompts/wk)
PRODUCTS = {
    "P01": ("Research Core", "Research", 1800, 0.6, 9.0, 6.0, 0.0),
    "P02": ("Research Plus", "Research", 2600, 0.8, 12.0, 8.0, 0.0),
    "P03": ("Litigation Analytics", "Analytics", 1500, 0.1, 4.0, 2.0, 0.0),
    "P04": ("Docket Intelligence", "Analytics", 900, -0.2, 3.0, 1.0, 0.0),
    "P05": ("Practical Guidance", "Guidance", 1200, 0.0, 1.5, 5.0, 0.0),
    "P06": ("AI Assistant", "AI", 1400, -0.1, 1.0, 1.5, 14.0),
}
ADDONS = ["P03", "P04", "P05"]
PRACTICE_AREAS = {
    "PA01": "Litigation", "PA02": "Corporate and M&A", "PA03": "Tax", "PA04": "Intellectual Property",
    "PA05": "Employment", "PA06": "Real Estate", "PA07": "Banking and Finance", "PA08": "Regulatory and Compliance",
    "PA09": "Criminal", "PA10": "Family", "PA11": "Energy", "PA12": "Healthcare",
}
UNSPECIFIED = ("PA00", "Unspecified")

OWNERS = [f"AE{n:02d}" for n in range(1, 31)]


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return add_months(date(d.year, d.month, 1), 1) - timedelta(days=1)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class Line:
    contract_id: str
    product_id: str
    start: date
    end: date
    per_seat_local: int                       # whole currency units, multiple of 12
    fx_start: float                           # local per USD in the start month
    history: list = field(default_factory=list)   # (effective_date, seats)
    renews: str | None = None

    def seats_at(self, d: date) -> int:
        s = 0
        for eff, seats in self.history:
            if eff <= d:
                s = seats
        return s

    def arr_usd_at(self, d: date) -> float:
        return self.seats_at(d) * self.per_seat_local / self.fx_start


class Sim:
    def __init__(self, seed: int = SEED):
        self.rng = np.random.default_rng(seed)
        self.fx = self._fx()
        self.events: list[dict] = []
        self.crm: list[dict] = []
        self.survey: list[dict] = []
        self.lines: list[tuple[str, Line]] = []          # (account_id, line)
        self.renewals: list[dict] = []
        self.firms: list[dict] = []
        self.health: dict[str, dict[date, float]] = {}
        self.versions: list[dict] = []
        self.weights: list[dict] = []
        self._cid = 0
        self._eid = 0

    # ---------- reference feeds ----------
    def _fx(self) -> dict[tuple[str, date], float]:
        out = {}
        m = date(2020, 1, 1)
        level = {c: math.log(v) for c, v in FX_BASE.items()}
        while m <= LAST_MONTH:
            for c in FX_BASE:
                if c != "USD":
                    level[c] += FX_DRIFT[c] + self.rng.normal(0, 0.012)
                out[(c, m)] = 1.0 if c == "USD" else round(math.exp(level[c]), 6)
            m = add_months(m, 1)
        return out

    def next_contract_id(self) -> str:
        self._cid += 1
        return f"C{self._cid:06d}"

    def emit(self, **kw) -> None:
        self._eid += 1
        kw.setdefault("event_id", f"E{self._eid:07d}")
        self.events.append(kw)

    # ---------- firm lifecycle ----------
    def price(self, product_id: str, firm: dict, m: date) -> tuple[int, float]:
        fx = self.fx[(firm["currency"], m)]
        local = PRODUCTS[product_id][2] * SEG_DISCOUNT[firm["segment0"]] * firm["price_index"] * firm["price_level"] * fx
        return max(12, int(round(local / 12)) * 12), fx

    def new_line(self, aid: str, firm: dict, product_id: str, start: date, end: date, seats: int,
                 renews: str | None = None) -> Line:
        ps, fx = self.price(product_id, firm, start)
        ln = Line(self.next_contract_id(), product_id, start, end, ps, fx, [(start, seats)], renews)
        term = months_between(start, end)
        tcv_minor = ps * seats * 100 * term // 12
        booked = datetime.combine(start, datetime.min.time()) - timedelta(days=int(self.rng.integers(2, 25)),
                                                                          hours=int(self.rng.integers(0, 23)))
        self.emit(event_type="contract_created", contract_id=ln.contract_id, account_id=aid, product_id=product_id,
                  renews_contract_id=renews, start_date=start, end_date=end, term_months=term, seats=seats,
                  seat_delta=None, effective_date=start, currency=firm["currency"], tcv_minor=tcv_minor,
                  tcv_delta_minor=None, event_ts=booked)
        self.lines.append((aid, ln))
        return ln

    def amend(self, aid: str, firm: dict, ln: Line, m: date, delta: int) -> None:
        seats = ln.seats_at(m) + delta
        ln.history.append((m, seats))
        rem = months_between(m, ln.end)
        self.emit(event_type="amendment", contract_id=ln.contract_id, account_id=aid, product_id=ln.product_id,
                  renews_contract_id=None, start_date=ln.start, end_date=ln.end, term_months=months_between(ln.start, ln.end),
                  seats=None, seat_delta=delta, effective_date=m, currency=firm["currency"], tcv_minor=None,
                  tcv_delta_minor=ln.per_seat_local * delta * 100 * rem // 12,
                  event_ts=datetime.combine(m, datetime.min.time()) - timedelta(days=int(self.rng.integers(1, 10))))

    def crm_row(self, firm: dict, op: str, ts: datetime, segment: str, owner: str) -> None:
        self.crm.append(dict(account_id=firm["account_id"], op=op, account_name=firm["name"],
                             account_type=firm["account_type"], segment=segment, country=firm["country"],
                             account_owner=owner, changed_at=ts))

    def simulate_firm(self, i: int, internal: bool = False) -> None:
        rng = self.rng
        aid = f"A{i:05d}"
        if internal:
            seg, country = "Large Law", "United States"
            start = date(2021, 1, 1)
        else:
            seg = SEGMENTS[rng.choice(len(SEGMENTS), p=SEG_P)]
            names = list(COUNTRIES)
            country = names[rng.choice(len(names), p=[COUNTRIES[c][3] for c in names])]
            if rng.random() < 0.72:
                start = add_months(date(2021, 1, 1), int(rng.integers(0, 36)))
            else:
                start = add_months(date(2024, 1, 1), int(rng.integers(0, 21)))
        cur, region, pidx, _ = COUNTRIES[country]
        firm = dict(account_id=aid, name=(f"Internal Demo Tenant {i}" if internal else f"Firm {i:05d}"),
                    account_type=("internal" if internal else "customer"), segment0=seg, country=country,
                    currency=cur, region=region, price_index=pidx, price_level=1.0, start=start)
        self.firms.append(firm)

        # health: monthly random walk with mean reversion
        h = rng.normal(0, 0.9)
        trend = rng.normal(0, 0.03)
        hs: dict[date, float] = {}
        m = add_months(start, -12)
        while m <= LAST_MONTH:
            h += trend + rng.normal(0, 0.17) - 0.04 * h
            hs[m] = h
            m = add_months(m, 1)
        self.health[aid] = hs

        # CRM: insert, optional owner changes, optional segment upgrade
        owner = OWNERS[int(rng.integers(len(OWNERS)))]
        created = datetime.combine(add_months(start, -2), datetime.min.time()) + timedelta(days=int(rng.integers(0, 27)), hours=int(rng.integers(8, 18)))
        self.crm_row(firm, "insert", created, seg, owner)
        changes = []
        if not internal and seg in UPGRADE and rng.random() < 0.16:
            when = add_months(max(start, date(2023, 7, 1)), int(rng.integers(1, 24)))
            if when <= LAST_MONTH:
                changes.append((when, "segment"))
        if not internal and rng.random() < 0.25:
            when = add_months(max(start, date(2023, 6, 1)), int(rng.integers(1, 30)))
            if when <= LAST_MONTH:
                changes.append((when, "owner"))
        cur_seg, cur_owner = seg, owner
        version_rows = [(created, cur_seg, cur_owner)]
        for when, kind in sorted(changes):
            ts = datetime.combine(when, datetime.min.time()) + timedelta(days=int(rng.integers(0, 27)), hours=int(rng.integers(8, 18)))
            if ts <= version_rows[-1][0] + timedelta(days=1):
                ts = version_rows[-1][0] + timedelta(days=2)
            if kind == "segment":
                cur_seg = UPGRADE[cur_seg]
            else:
                cur_owner = OWNERS[int(rng.integers(len(OWNERS)))]
            self.crm_row(firm, "update", ts, cur_seg, cur_owner)
            version_rows.append((ts, cur_seg, cur_owner))
        for k, (ts, s, o) in enumerate(version_rows):
            nxt = version_rows[k + 1][0].date() if k + 1 < len(version_rows) else date(9999, 12, 31)
            self.versions.append(dict(account_id=aid, segment=s, account_owner=o, country=country, region=region,
                                      account_type=firm["account_type"], valid_from=ts.date(), valid_to=nxt))

        # practice focus survey (bridge)
        if not internal:
            r = rng.random()
            if r < 0.05:
                self.weights.append(dict(account_id=aid, practice_area_id=UNSPECIFIED[0], weight=1.0))
            else:
                k = int(rng.choice([1, 2, 3, 4, 5], p=[0.2, 0.3, 0.25, 0.15, 0.1]))
                pas = list(rng.choice(list(PRACTICE_AREAS), size=k, replace=False))
                raw = rng.dirichlet(np.ones(k) * 1.5)
                pct = np.floor(raw * 100).astype(int)
                pct[0] += 100 - pct.sum()
                if (pct <= 0).any():
                    pct = np.full(k, 100 // k)
                    pct[0] += 100 - pct.sum()
                surveyed = created + timedelta(days=int(rng.integers(10, 200)))
                if rng.random() < 0.04:   # an older, superseded survey also sits in the feed
                    old = list(rng.choice(list(PRACTICE_AREAS), size=2, replace=False))
                    for pa, p in zip(old, [60, 40]):
                        self.survey.append(dict(account_id=aid, practice_area_id=pa, focus_pct=p,
                                                surveyed_at=surveyed - timedelta(days=400)))
                for pa, p in zip(pas, pct):
                    self.survey.append(dict(account_id=aid, practice_area_id=pa, focus_pct=int(p), surveyed_at=surveyed))
                    self.weights.append(dict(account_id=aid, practice_area_id=pa, weight=int(p) / 100))

        # contracts
        def seats_for(scale: float = 1.0) -> int:
            return max(1, int(round(SEG_SEATS[seg] * math.exp(rng.normal(0, 0.45)) * scale)))

        term = 36 if rng.random() < 0.3 else 12
        end = add_months(start, term)
        core_pid = "P02" if rng.random() < (0.55 if seg in ("Global Law Firm", "Large Law") else 0.25) else "P01"
        if internal:
            core_pid = "P02"
        core_seats = 40 if internal else seats_for()
        active: list[Line] = [self.new_line(aid, firm, core_pid, start, end, core_seats)]
        for pid, p in (("P03", 0.35), ("P04", 0.15), ("P05", 0.30)):
            if not internal and rng.random() < p:
                active.append(self.new_line(aid, firm, pid, start, end, max(1, int(core_seats * rng.uniform(0.2, 0.7)))))

        m = add_months(start, 1)
        while m <= LAST_MONTH and active:
            hm = hs[m]
            core = next(ln for ln in active if ln.product_id in ("P01", "P02"))
            if core.end == m:     # renewal moment for the whole firm (all lines co-termed)
                trend6 = hm - hs[add_months(m, -6)]
                has_ai = any(ln.product_id == "P06" for ln in active)
                price_up = rng.random() < 0.25
                seg_now = cur_seg_at(self.versions, aid, m)
                p_churn = sigmoid(-2.7 - 1.25 * hm - 1.6 * trend6 + 0.6 * (seg_now == "Small Law") + 0.5 * price_up
                                  - 0.6 * has_ai)
                logo_churn = internal is False and rng.random() < p_churn
                firm["price_level"] *= 1.12 if price_up else 1.05
                new_term = 36 if rng.random() < 0.25 else 12
                new_end = add_months(m, new_term)
                nxt: list[Line] = []
                for ln in active:
                    exp_arr = ln.arr_usd_at(add_months(m, 0) - timedelta(days=1))
                    churn_line = logo_churn or (ln is not core and rng.random() < sigmoid(-2.6 - 1.0 * hm))
                    if churn_line:
                        self.renewals.append(dict(contract_id=ln.contract_id, account_id=aid, product_id=ln.product_id,
                                                  renewal_date=m, arr_expiring_usd=exp_arr, outcome="churned",
                                                  arr_renewed_usd=0.0, successor_contract_id=None))
                        continue
                    seats_now = ln.seats_at(m - timedelta(days=1))
                    new_seats = max(1, int(round(seats_now * (1 + rng.normal(0.03 + 0.05 * hm, 0.08)))))
                    if internal:
                        new_seats = seats_now
                    nl = self.new_line(aid, firm, ln.product_id, m, new_end, new_seats, renews=ln.contract_id)
                    self.renewals.append(dict(contract_id=ln.contract_id, account_id=aid, product_id=ln.product_id,
                                              renewal_date=m, arr_expiring_usd=exp_arr, outcome="renewed",
                                              arr_renewed_usd=nl.arr_usd_at(m), successor_contract_id=nl.contract_id))
                    nxt.append(nl)
                if not logo_churn and not internal and rng.random() < 0.08:
                    owned = {ln.product_id for ln in nxt}
                    options = [p for p in ADDONS if p not in owned]
                    if options:
                        pid = options[int(rng.integers(len(options)))]
                        core_new = next(ln for ln in nxt if ln.product_id in ("P01", "P02"))
                        nxt.append(self.new_line(aid, firm, pid, m, new_end,
                                                 max(1, int(core_new.seats_at(m) * rng.uniform(0.2, 0.6)))))
                active = nxt
            elif not internal:
                rem = months_between(m, core.end)
                if rng.random() < 0.012 * (1 + max(hm, 0)):
                    s = core.seats_at(m)
                    self.amend(aid, firm, core, m, max(1, int(math.ceil(s * rng.uniform(0.05, 0.25)))))
                has_ai = any(ln.product_id == "P06" for ln in active)
                if m >= AI_LAUNCH and not has_ai and rem >= 2 and rng.random() < 0.035 * math.exp(0.5 * hm):
                    active.append(self.new_line(aid, firm, "P06", m, core.end,
                                                max(1, int(round(core.seats_at(m) * rng.uniform(0.2, 0.6))))))
                elif rem >= 3 and rng.random() < 0.004:
                    owned = {ln.product_id for ln in active}
                    options = [p for p in ADDONS if p not in owned]
                    if options:
                        pid = options[int(rng.integers(len(options)))]
                        active.append(self.new_line(aid, firm, pid, m, core.end,
                                                    max(1, int(core.seats_at(m) * rng.uniform(0.2, 0.6)))))
            m = add_months(m, 1)

    # ---------- usage ----------
    def usage(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        rng = self.rng
        weeks = [H0 + timedelta(days=7 * k) for k in range(104)]          # Mondays, 2024-01-01 .. 2025-12-22
        firm_eff = {f["account_id"]: rng.normal(0, 0.35) for f in self.firms}
        by_firm: dict[str, list[Line]] = {}
        for aid, ln in self.lines:
            by_firm.setdefault(aid, []).append(ln)
        rows = []
        for aid, lines in by_firm.items():
            for ln in lines:
                if ln.end <= H0 or ln.start > weeks[-1]:
                    continue
                name, line, _, base, sr, dr, ar = PRODUCTS[ln.product_id]
                for ws in weeks:
                    if not (ln.start <= ws < ln.end):
                        continue
                    seats = ln.seats_at(ws)
                    hm = self.health[aid][date(ws.year, ws.month, 1)]
                    season = 0.45 if (ws.month == 12 and ws.day >= 22) or (ws.month == 1 and ws.day <= 1) else (0.88 if ws.month == 8 else 1.0)
                    p = sigmoid(base + 1.1 * hm + firm_eff[aid] + rng.normal(0, 0.15)) * season
                    active = int(rng.binomial(seats, min(max(p, 0.0), 1.0)))
                    k = math.exp(rng.normal(0, 0.2))
                    rows.append(dict(week_start=ws, account_id=aid, product_id=ln.product_id, licensed_seats=seats,
                                     active_users=active, searches=int(rng.poisson(active * sr * k)),
                                     documents_viewed=int(rng.poisson(active * dr * k)),
                                     ai_prompts=int(rng.poisson(active * ar * k))))
        df = pd.DataFrame(rows)
        # behavioural anomalies, real in both the feed and the answer key
        cust = df[df.account_id.isin([f["account_id"] for f in self.firms if f["account_type"] == "customer"])
                  & (df.licensed_seats >= 5) & (df.week_start >= H0 + timedelta(days=70))]
        series = cust[["account_id", "product_id"]].drop_duplicates().sample(75, random_state=SEED).to_numpy()
        anomalies = []
        for j, (aid, pid) in enumerate(series):
            s = df[(df.account_id == aid) & (df.product_id == pid) & (df.week_start >= H0 + timedelta(days=70))]
            idx = s.index[int(rng.integers(0, max(1, len(s) - 2)))]
            if j < 45:     # bulk scraping / shared credentials: search volume jumps
                span = [idx] + ([idx + 1] if rng.random() < 0.4 and idx + 1 in s.index else [])
                for ix in span:
                    df.loc[ix, "searches"] = int(df.loc[ix, "searches"] * rng.uniform(6, 12) + 30)
                    anomalies.append(dict(account_id=aid, product_id=pid, week_start=df.loc[ix, "week_start"], kind="search_spike"))
            else:          # firm-side tracking outage: everything near zero for a week
                for c in ("active_users", "searches", "documents_viewed", "ai_prompts"):
                    df.loc[idx, c] = int(df.loc[idx, c] * 0.05)
                anomalies.append(dict(account_id=aid, product_id=pid, week_start=df.loc[idx, "week_start"], kind="tracking_gap"))
        anom = pd.DataFrame(anomalies).drop_duplicates()

        # feed: weekly extract lands 8 days after week start; 4% of rows first land partial and are restated a week later
        feed = df.copy()
        feed["_loaded_at"] = [datetime.combine(w + timedelta(days=8), datetime.min.time()) + timedelta(hours=3) for w in feed.week_start]
        partial = feed.sample(frac=0.04, random_state=SEED + 1).copy()
        frac = rng.uniform(0.5, 0.85, len(partial))
        for c in ("active_users", "searches", "documents_viewed", "ai_prompts"):
            partial[c] = (partial[c] * frac).astype(int)
        feed["_loaded_at"] = [t if i not in partial.index else t + timedelta(days=7) for i, t in zip(feed.index, feed._loaded_at)]
        feed = pd.concat([feed, partial]).sort_values(["_loaded_at", "account_id"]).reset_index(drop=True)
        return df, feed, anom


def cur_seg_at(versions: list[dict], aid: str, d: date) -> str:
    seg = None
    for v in versions:
        if v["account_id"] == aid and v["valid_from"] <= d:
            seg = v["segment"]
    return seg


def main(out: Path) -> None:
    sim = Sim()
    for i in range(1, N_FIRMS + 1):
        sim.simulate_firm(i)
    for i in range(N_FIRMS + 1, N_FIRMS + 7):
        sim.simulate_firm(i, internal=True)
    usage_clean, usage_feed, anomalies = sim.usage()
    rng = sim.rng
    land, truth = out / "landing", out / "truth"
    land.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)

    # ---- CPQ contract events: delivered at least once, amounts in minor units
    ev = pd.DataFrame(sim.events)
    ev["_loaded_at"] = ev.event_ts + pd.to_timedelta(rng.integers(5, 240, len(ev)), unit="m")
    dup = ev.sample(frac=0.03, random_state=SEED).copy()
    dup["_loaded_at"] = dup._loaded_at + pd.to_timedelta(rng.integers(1, 72, len(dup)), unit="h")
    ev = pd.concat([ev, dup]).sort_values("_loaded_at").reset_index(drop=True)
    for c in ("seats", "seat_delta", "tcv_minor", "tcv_delta_minor"):
        ev[c] = ev[c].astype("Int64")
    ev.to_parquet(land / "cpq_contract_events.parquet", index=False)

    # ---- CRM CDC: 2% re-sent, loads out of order
    crm = pd.DataFrame(sim.crm)
    crm["_loaded_at"] = crm.changed_at + pd.to_timedelta(rng.integers(1, 600, len(crm)), unit="m")
    re = crm.sample(frac=0.02, random_state=SEED).copy()
    re["_loaded_at"] = re._loaded_at + pd.to_timedelta(rng.integers(2, 30, len(re)), unit="D")
    pd.concat([crm, re]).sample(frac=1, random_state=SEED).to_parquet(land / "crm_account_changes.parquet", index=False)

    sv = pd.DataFrame(sim.survey)
    sv["_loaded_at"] = sv.surveyed_at + timedelta(hours=6)
    sv.to_parquet(land / "crm_practice_focus.parquet", index=False)

    fx = pd.DataFrame([dict(currency=c, month_start=m, local_per_usd=v) for (c, m), v in sim.fx.items()])
    fx["_loaded_at"] = [datetime.combine(m, datetime.min.time()) + timedelta(hours=1) for m in fx.month_start]
    fx.to_parquet(land / "fx_rates_monthly.parquet", index=False)

    usage_feed.to_parquet(land / "product_usage_weekly.parquet", index=False)

    # ---- answer key (customers only)
    cust = {f["account_id"] for f in sim.firms if f["account_type"] == "customer"}
    arr_rows = []
    m = H0
    while m <= LAST_MONTH:
        me = month_end(m)
        for aid, ln in sim.lines:
            if aid in cust and ln.start <= me < ln.end:
                arr_rows.append(dict(month_end=me, account_id=aid, product_id=ln.product_id,
                                     seats=ln.seats_at(me), arr_usd=ln.arr_usd_at(me)))
        m = add_months(m, 1)
    arr = pd.DataFrame(arr_rows).groupby(["month_end", "account_id", "product_id"], as_index=False).sum()
    arr.to_parquet(truth / "arr_monthly.parquet", index=False)
    pd.DataFrame([v for v in sim.versions if v["account_id"] in cust]).to_parquet(truth / "firm_versions.parquet", index=False)
    pd.DataFrame(sim.weights).to_parquet(truth / "practice_weights.parquet", index=False)
    ren = pd.DataFrame(sim.renewals)
    ren[ren.account_id.isin(cust)].to_parquet(truth / "renewals.parquet", index=False)
    usage_clean[usage_clean.account_id.isin(cust)].to_parquet(truth / "usage_weekly.parquet", index=False)
    anomalies.to_parquet(truth / "usage_anomalies.parquet", index=False)
    pd.DataFrame([dict(product_id=k, product_name=v[0], product_line=v[1], list_price_usd=v[2]) for k, v in PRODUCTS.items()]) \
        .to_parquet(truth / "products.parquet", index=False)
    pd.DataFrame([dict(practice_area_id=k, practice_area=v) for k, v in [UNSPECIFIED, *PRACTICE_AREAS.items()]]) \
        .to_parquet(truth / "practice_areas.parquet", index=False)

    dec24 = arr[arr.month_end == date(2024, 12, 31)].arr_usd.sum()
    dec25 = arr[arr.month_end == date(2025, 12, 31)].arr_usd.sum()
    print(f"events={len(ev):,} crm={len(crm):,} usage_rows={len(usage_feed):,} renewals={len(ren):,}")
    print(f"ARR Dec 2024 ${dec24:,.0f}  Dec 2025 ${dec25:,.0f}")
    f24 = arr[arr.month_end == date(2024, 12, 31)].groupby("account_id").arr_usd.sum()
    f25 = arr[arr.month_end == date(2025, 12, 31)].groupby("account_id").arr_usd.sum()
    nrr = f25.reindex(f24.index).fillna(0).sum() / f24.sum()
    print(f"firms Dec24={len(f24)} Dec25={len(f25)} logo churn={(~f24.index.isin(f25.index)).mean():.1%} NRR={nrr:.1%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    main(Path(ap.parse_args().out))
