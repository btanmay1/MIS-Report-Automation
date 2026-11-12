"""Synthetic card-operations source data, 13 months (Oct 2025 - Oct 2026), loaded into SQLite.

Tables: applications, account_month, disputes, complaints. A few operational events are planted
(an SLA dip, a dispute spike, a seasonal spend peak) so the month-on-month commentary has something to find.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

MONTHS = pd.period_range("2025-10", "2026-10", freq="M")


def generate(seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    apps, accts, disputes, complaints = [], [], [], []
    n_acc = 15_000
    base_spend = rng.lognormal(9.6, 0.8, n_acc)
    limit = rng.choice([50_000, 100_000, 200_000, 400_000], n_acc, p=[0.35, 0.35, 0.2, 0.1])
    opened = rng.integers(-30, 13, n_acc)  # month index the account opened (negative = before window)
    risky = rng.random(n_acc) < 0.08

    for i, m in enumerate(MONTHS):
        ms = m.to_timestamp()
        days = m.days_in_month
        # Applications: SLA dip planted in Sep-Oct 2026 (backlog)
        n_app = int(rng.normal(3_000, 150) * (1.15 if m.month in (10, 11) else 1.0))
        tat_scale = 22 if i < 11 else (34 if i == 11 else 41)
        apps.append(pd.DataFrame({
            "application_id": [f"A{i:02d}{k:05d}" for k in range(n_app)],
            "received_date": ms + pd.to_timedelta(rng.integers(0, days, n_app), "D"),
            "decision": rng.choice(["Approved", "Declined", "Withdrawn"], n_app, p=[0.62, 0.31, 0.07]),
            "tat_hours": np.round(rng.gamma(2.0, tat_scale / 2.0, n_app), 1),
            "channel": rng.choice(["Digital", "Branch", "DSA"], n_app, p=[0.6, 0.15, 0.25]),
        }))
        # Account-month snapshot
        live = opened <= i
        season = 1.18 if m.month in (10, 11) else (0.92 if m.month in (1, 2) else 1.0)
        active = live & (rng.random(n_acc) < 0.82)
        spend = np.where(active, base_spend * season * rng.lognormal(0, 0.3, n_acc), 0)
        bal = np.minimum(limit, spend * rng.uniform(0.6, 1.6, n_acc))
        dpd_p = np.where(risky, 0.22, 0.012) * (1 + 0.04 * i)  # slow deterioration
        accts.append(pd.DataFrame({
            "account_id": np.arange(n_acc)[live], "month": str(m), "active": active[live].astype(int),
            "spend": np.round(spend[live], 2), "txn_count": np.where(active, rng.poisson(14, n_acc), 0)[live],
            "balance": np.round(bal[live], 2), "credit_limit": limit[live],
            "dpd30": (rng.random(n_acc) < dpd_p)[live].astype(int)}))
        # Disputes: spike in Oct 2026 (merchant outage causing duplicate charges)
        n_d = int(rng.normal(780, 40) * (1.45 if i == 12 else 1.0))
        op = ms + pd.to_timedelta(rng.integers(0, days, n_d), "D")
        res_days = rng.gamma(2.2, 9 if i < 12 else 13, n_d).astype(int) + 1
        disputes.append(pd.DataFrame({
            "dispute_id": [f"D{i:02d}{k:05d}" for k in range(n_d)], "opened_date": op, "resolved_date": op + pd.to_timedelta(res_days, "D"),
            "amount": np.round(rng.lognormal(7.5, 1.0, n_d), 2),
            "reason": rng.choice(["Duplicate charge", "Goods not received", "Fraud - card not present", "Incorrect amount", "Other"], n_d,
                                 p=[0.40, 0.20, 0.18, 0.12, 0.10] if i == 12 else [0.18, 0.27, 0.22, 0.15, 0.18]),
            "outcome": rng.choice(["Customer favour", "Merchant favour", "Partial"], n_d, p=[0.55, 0.35, 0.10])}))
        # Complaints
        n_c = int(rng.normal(420, 25) * (1.2 if i >= 11 else 1.0))
        cd = ms + pd.to_timedelta(rng.integers(0, days, n_c), "D")
        complaints.append(pd.DataFrame({
            "complaint_id": [f"C{i:02d}{k:05d}" for k in range(n_c)], "received_date": cd,
            "category": rng.choice(["Billing", "Service delay", "Card delivery", "Rewards", "Fraud", "Other"], n_c),
            "resolved_date": cd + pd.to_timedelta(rng.gamma(2.0, 3.5, n_c).astype(int) + 1, "D")}))

    out = {"applications": pd.concat(apps), "account_month": pd.concat(accts), "disputes": pd.concat(disputes),
           "complaints": pd.concat(complaints)}
    for df in out.values():
        for c in df.columns:
            if c.endswith("_date"):
                df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d")
    return out


def to_sqlite(tables: dict[str, pd.DataFrame], path: Path | str = ":memory:") -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    for name, df in tables.items():
        df.to_sql(name, con, index=False, if_exists="replace")
    return con
