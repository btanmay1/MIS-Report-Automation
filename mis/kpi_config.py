"""KPI catalogue: display name, format, direction (is higher better?), target and section."""

# key: (label, fmt, higher_is_better, target or None, section)
KPIS = {
    "applications": ("New applications", "int", True, None, "Acquisition"),
    "approval_rate": ("Approval rate", "pct", True, 0.60, "Acquisition"),
    "avg_tat_hours": ("Avg decision TAT (hours)", "dec1", False, 24.0, "Acquisition"),
    "within_sla_rate": ("Decisions within 48h SLA", "pct", True, 0.90, "Acquisition"),
    "active_accounts": ("Active accounts", "int", True, None, "Portfolio"),
    "total_spend": ("Total spend (Rs. cr)", "cr", True, None, "Portfolio"),
    "spend_per_active": ("Spend per active account (Rs.)", "int", True, None, "Portfolio"),
    "utilisation": ("Credit utilisation", "pct", None, None, "Portfolio"),
    "dpd30_rate": ("30+ DPD rate", "pct2", False, 0.040, "Credit risk"),
    "disputes": ("Disputes opened", "int", False, None, "Servicing"),
    "disputes_per_10k_txns": ("Disputes per 10k transactions", "dec2", False, 52.0, "Servicing"),
    "disputes_resolved_30d_rate": ("Disputes resolved within 30 days", "pct", True, 0.85, "Servicing"),
    "duplicate_charge_share": ("Duplicate-charge share of disputes", "pct", False, None, "Servicing"),
    "complaints": ("Complaints received", "int", False, None, "Servicing"),
    "complaints_per_1k_active": ("Complaints per 1,000 active", "dec2", False, 45.0, "Servicing"),
    "avg_complaint_days": ("Avg complaint resolution (days)", "dec1", False, 8.0, "Servicing"),
}

COMMENTARY_MOM_THRESHOLD = 0.10   # call out a KPI when it moves more than 10% month on month


def fmt(value, kind: str) -> str:
    if value is None or value != value:
        return "-"
    return {"int": f"{value:,.0f}", "pct": f"{value:.1%}", "pct2": f"{value:.2%}", "dec1": f"{value:,.1f}",
            "dec2": f"{value:,.2f}", "cr": f"{value / 1e7:,.2f}"}[kind]
