"""Build the monthly MIS pack.

    python -m mis.build                    # latest month (Oct 2026)
    python -m mis.build --month 2026-06    # any month in the data
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .generate import generate, to_sqlite
from .kpi_config import COMMENTARY_MOM_THRESHOLD, KPIS, fmt

ROOT = Path(__file__).resolve().parent.parent
INK, INK2, GRID, BLUE, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6", "#fcfcfb"


def data_checks(tables: dict[str, pd.DataFrame], kpis: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t, key in (("applications", "application_id"), ("disputes", "dispute_id"), ("complaints", "complaint_id")):
        rows.append((f"{t}: {key} unique", int(tables[t][key].duplicated().sum()) == 0, f"{len(tables[t]):,} rows"))
    rows.append(("account_month: one row per account per month",
                 int(tables["account_month"].duplicated(["account_id", "month"]).sum()) == 0, f"{len(tables['account_month']):,} rows"))
    rows.append(("Every month has all KPIs populated", bool(kpis.drop(columns="month").notna().all().all()), f"{len(kpis)} months"))
    rows.append(("SQL application count = Pandas count", int(kpis.applications.sum()) == len(tables["applications"]),
                 f"{int(kpis.applications.sum()):,} vs {len(tables['applications']):,}"))
    rows.append(("SQL spend total = Pandas total", abs(kpis.total_spend.sum() - tables["account_month"].spend.sum()) < 1,
                 f"Rs. {kpis.total_spend.sum():,.0f}"))
    rows.append(("Resolved dates not before opened dates",
                 bool((tables["disputes"].resolved_date >= tables["disputes"].opened_date).all()), "disputes"))
    return pd.DataFrame(rows, columns=["check", "passed", "detail"])


def scorecard(kpis: pd.DataFrame, month: str) -> pd.DataFrame:
    k = kpis.set_index("month")
    prev = str(pd.Period(month) - 1)
    ly = str(pd.Period(month) - 12)
    rows = []
    for key, (label, kind, hib, target, section) in KPIS.items():
        cur = k.at[month, key]
        p = k.at[prev, key] if prev in k.index else None
        y = k.at[ly, key] if ly in k.index else None
        mom = (cur - p) / p if p else None
        yoy = (cur - y) / y if y else None
        if target is None or hib is None:
            status = "-"
        else:
            status = "Met" if (cur >= target if hib else cur <= target) else "Missed"
        trend = "-" if hib is None or mom is None or abs(mom) < 0.02 else ("Improving" if (mom > 0) == hib else "Worsening")
        rows.append({"section": section, "kpi": key, "KPI": label, "This month": fmt(cur, kind), "Prior month": fmt(p, kind),
                     "MoM %": f"{mom:+.1%}" if mom is not None else "-", "Same month LY": fmt(y, kind),
                     "YoY %": f"{yoy:+.1%}" if yoy is not None else "-", "Target": fmt(target, kind) if target is not None else "-",
                     "Status": status, "Trend": trend, "_cur": cur, "_mom": mom, "_hib": hib, "_target": target, "_kind": kind})
    return pd.DataFrame(rows)


def commentary(sc: pd.DataFrame, month: str, tables: dict[str, pd.DataFrame]) -> list[str]:
    """Rule-based commentary: target misses first, then the biggest month-on-month movers."""
    lines = []
    m = pd.Period(month).strftime("%B %Y")
    met = (sc.Status == "Met").sum()
    tgt = (sc.Status != "-").sum()
    lines.append(f"{m}: {met} of {tgt} targeted KPIs met target.")
    for _, r in sc[sc.Status == "Missed"].iterrows():
        lines.append(f"{r.KPI} missed target at {r['This month']} (target {r.Target}; prior month {r['Prior month']}).")
    movers = sc[sc._mom.notna() & (sc._mom.abs() >= COMMENTARY_MOM_THRESHOLD) & (sc.Status != "Missed")]
    for _, r in movers.reindex(movers._mom.abs().sort_values(ascending=False).index).iterrows():
        direction = "up" if r._mom > 0 else "down"
        tone = "" if r._hib is None else (" (favourable)" if (r._mom > 0) == r._hib else " (adverse)")
        lines.append(f"{r.KPI} {direction} {abs(r._mom):.0%} month on month to {r['This month']}{tone}.")
    # driver drill-down for disputes
    d = tables["disputes"]
    cur = d[d.opened_date.str.startswith(month)]
    prev = d[d.opened_date.str.startswith(str(pd.Period(month) - 1))]
    if len(prev) and len(cur) / len(prev) - 1 >= COMMENTARY_MOM_THRESHOLD:
        mix = cur.reason.value_counts()
        pmix = prev.reason.value_counts()
        top = (mix - pmix.reindex(mix.index, fill_value=0)).idxmax()
        lines.append(f"Dispute increase is driven by '{top}' ({pmix.get(top, 0):,} -> {mix[top]:,} cases); "
                     f"recommend root-cause review with the merchant acquiring team.")
    return lines


def write_excel(path: Path, month: str, sc: pd.DataFrame, kpis: pd.DataFrame, notes: list[str], checks: pd.DataFrame) -> None:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    hdr = lambda c: (setattr(c, "font", Font(bold=True, color="FFFFFF")), setattr(c, "fill", PatternFill("solid", fgColor="1F3864")))
    wb = Workbook()
    ws = wb.active
    ws.title = "Scorecard"
    ws["A1"] = f"Card Operations MIS - {pd.Period(month).strftime('%B %Y')}"
    ws["A1"].font = Font(bold=True, size=14)
    cols = ["Section", "KPI", "This month", "Prior month", "MoM %", "Same month LY", "YoY %", "Target", "Status", "Trend"]
    for j, c in enumerate(cols, 1):
        hdr(ws.cell(row=3, column=j, value=c))
    fills = {"Met": "C6EFCE", "Missed": "FFC7CE", "Improving": "C6EFCE", "Worsening": "FFC7CE"}
    for i, r in enumerate(sc.itertuples(), 4):
        vals = [r.section, r.KPI, r._4, r._5, r._6, r._7, r._8, r.Target, r.Status, r.Trend]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            if v in fills:
                c.fill = PatternFill("solid", fgColor=fills[v])
    for j, w in enumerate([13, 36, 13, 13, 9, 14, 9, 10, 9, 11], 1):
        ws.column_dimensions[get_column_letter(j)].width = w

    cm = wb.create_sheet("Commentary")
    cm["A1"] = "Management commentary (auto-generated, review before circulation)"
    cm["A1"].font = Font(bold=True, size=12)
    for i, line in enumerate(notes, 3):
        c = cm.cell(row=i, column=1, value=f"• {line}")
        c.alignment = Alignment(wrap_text=True)
    cm.column_dimensions["A"].width = 120

    tr = wb.create_sheet("Trend")
    keys = list(KPIS)
    tr.cell(row=1, column=1, value="Month")
    hdr(tr.cell(row=1, column=1))
    for j, k in enumerate(keys, 2):
        hdr(tr.cell(row=1, column=j, value=KPIS[k][0]))
        tr.column_dimensions[get_column_letter(j)].width = 16
    for i, r in enumerate(kpis.itertuples(index=False), 2):
        tr.cell(row=i, column=1, value=r.month)
        for j, k in enumerate(keys, 2):
            c = tr.cell(row=i, column=j, value=float(getattr(r, k)))
            c.number_format = {"pct": "0.0%", "pct2": "0.00%", "int": "#,##0", "cr": "#,##0", "dec1": "0.0", "dec2": "0.00"}[KPIS[k][1]]
    n = len(kpis) + 1
    cats = Reference(tr, min_col=1, min_row=2, max_row=n)
    ch = wb.create_sheet("Charts")
    for idx, (key, chart_type) in enumerate([("applications", "bar"), ("within_sla_rate", "line"), ("dpd30_rate", "line"),
                                             ("disputes_per_10k_txns", "line"), ("complaints_per_1k_active", "line"),
                                             ("spend_per_active", "bar")]):
        col = keys.index(key) + 2
        c = BarChart() if chart_type == "bar" else LineChart()
        c.title = KPIS[key][0]
        c.add_data(Reference(tr, min_col=col, min_row=1, max_row=n), titles_from_data=True)
        c.set_categories(cats)
        c.legend = None
        c.height, c.width = 7, 13
        c.series[0].graphicalProperties.line.solidFill = "2A78D6"
        if chart_type == "bar":
            c.series[0].graphicalProperties.solidFill = "2A78D6"
        ch.add_chart(c, f"{'A' if idx % 2 == 0 else 'J'}{1 + (idx // 2) * 15}")

    dc = wb.create_sheet("Data Checks")
    for j, c in enumerate(checks.columns, 1):
        hdr(dc.cell(row=1, column=j, value=c))
    for i, r in enumerate(checks.itertuples(index=False), 2):
        for j, v in enumerate(r, 1):
            c = dc.cell(row=i, column=j, value="PASS" if v is True else "FAIL" if v is False else v)
            if v is True or v is False:
                c.fill = PatternFill("solid", fgColor="C6EFCE" if v else "FFC7CE")
    dc.column_dimensions["A"].width, dc.column_dimensions["C"].width = 50, 30
    wb.save(path)


def trend_png(path: Path, kpis: pd.DataFrame, month: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.edgecolor": GRID, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})
    keys = ["applications", "within_sla_rate", "dpd30_rate", "disputes_per_10k_txns", "complaints_per_1k_active", "spend_per_active"]
    fig, axes = plt.subplots(2, 3, figsize=(10, 4.6))
    x = [pd.Period(m).strftime("%b\n%y") for m in kpis.month]
    for ax, k in zip(axes.flat, keys):
        label, kind, hib, target, _ = KPIS[k]
        ax.plot(x, kpis[k], color=BLUE, lw=2, marker="o", ms=3)
        if target is not None:
            ax.axhline(target, color=INK2, lw=1, ls="--")
            ax.text(len(x) - 0.5, target, " target", va="bottom", ha="right", fontsize=7, color=INK2)
        ax.set_title(label, loc="left", fontsize=9, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.grid(True, color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
        ax.set_xticks(range(0, len(x), 3), [x[i] for i in range(0, len(x), 3)])
        if kind.startswith("pct"):
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=1 if kind == "pct2" else 0))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_pdf(path: Path, month: str, sc: pd.DataFrame, notes: list[str], chart: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("s", fontSize=7.5, leading=9.5)
    hdr = small.clone("h", textColor=colors.white, fontName="Helvetica-Bold")
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"Card Operations MIS {month}")
    cols = ["KPI", "This month", "Prior month", "MoM %", "YoY %", "Target", "Status"]
    data = [[Paragraph(c, hdr) for c in cols]] + [[Paragraph(str(r[c]), small) for c in cols] for _, r in sc.iterrows()]
    t = Table(data, colWidths=[62 * mm, 22 * mm, 22 * mm, 16 * mm, 16 * mm, 20 * mm, 16 * mm], repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i, s in enumerate(sc.Status, 1):
        if s in ("Met", "Missed"):
            style.append(("BACKGROUND", (6, i), (6, i), colors.HexColor("#C6EFCE" if s == "Met" else "#FFC7CE")))
    t.setStyle(TableStyle(style))
    story = [Paragraph(f"Card Operations MIS - {pd.Period(month).strftime('%B %Y')}", st["Title"]),
             Paragraph("Key commentary", st["Heading3"])]
    story += [Paragraph(f"• {n}", small) for n in notes]
    story += [Spacer(1, 3 * mm), t, Spacer(1, 3 * mm), Image(str(chart), width=186 * mm, height=186 * mm * 4.6 / 10)]
    doc.build(story)


def build(month: str | None = None, out: Path = ROOT / "output", seed: int = 42) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tables = generate(seed)
    con = to_sqlite(tables)
    kpis = pd.read_sql_query((ROOT / "sql" / "kpis.sql").read_text(), con)
    month = month or kpis.month.max()
    if month not in set(kpis.month):
        raise SystemExit(f"Month {month} not in data ({kpis.month.min()} - {kpis.month.max()})")
    checks = data_checks(tables, kpis)
    if not checks.passed.all():
        raise SystemExit("Data checks failed:\n" + checks[~checks.passed].to_string(index=False))
    sc = scorecard(kpis, month)
    notes = commentary(sc, month, tables)
    tag = month.replace("-", "_")
    write_excel(out / f"MIS_{tag}.xlsx", month, sc, kpis, notes, checks)
    trend_png(out / f"trends_{tag}.png", kpis, month)
    write_pdf(out / f"MIS_{tag}.pdf", month, sc, notes, out / f"trends_{tag}.png")
    kpis.to_csv(out / "kpi_history.csv", index=False)
    (out / f"commentary_{tag}.json").write_text(json.dumps(notes, indent=2))
    print(f"[checks] {int(checks.passed.sum())}/{len(checks)} passed")
    print(sc[["KPI", "This month", "Prior month", "MoM %", "Target", "Status"]].to_string(index=False))
    print("\n".join("- " + n for n in notes))
    return {"scorecard": sc, "commentary": notes, "checks": checks}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", help="YYYY-MM; default = latest")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    a = ap.parse_args()
    build(a.month, a.out)


if __name__ == "__main__":
    main()
