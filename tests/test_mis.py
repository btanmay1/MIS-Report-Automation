from pathlib import Path

import pandas as pd
import pytest

from mis.build import ROOT, commentary, data_checks, scorecard
from mis.generate import generate, to_sqlite


@pytest.fixture(scope="module")
def built():
    t = generate(seed=1)
    k = pd.read_sql_query((ROOT / "sql" / "kpis.sql").read_text(), to_sqlite(t))
    return t, k


def test_kpis_one_row_per_month_and_reconcile(built):
    t, k = built
    assert len(k) == 13 and k.month.is_unique
    assert data_checks(t, k).passed.all()


def test_sql_kpis_match_pandas(built):
    t, k = built
    a = t["applications"].assign(month=t["applications"].received_date.str[:7])
    sla = a.groupby("month").tat_hours.apply(lambda s: (s <= 48).mean())
    assert (k.set_index("month").within_sla_rate - sla).abs().max() < 1e-9
    am = t["account_month"].groupby("month")
    assert (k.set_index("month").dpd30_rate - am.dpd30.mean()).abs().max() < 1e-9


def test_scorecard_status_direction(built):
    _, k = built
    sc = scorecard(k, "2026-10").set_index("kpi")
    # lower-is-better KPI above target must be Missed; higher-is-better below target Missed
    assert sc.at["within_sla_rate", "Status"] == "Missed"
    assert sc.at["avg_tat_hours", "Status"] == "Missed"
    assert sc.at["applications", "Status"] == "-"


def test_commentary_finds_planted_events(built):
    t, k = built
    notes = " ".join(commentary(scorecard(k, "2026-10"), "2026-10", t))
    assert "Decisions within 48h SLA missed target" in notes
    assert "Duplicate charge" in notes


def test_first_month_has_no_prior(built):
    _, k = built
    sc = scorecard(k, "2025-10")
    assert (sc["MoM %"] == "-").all()
