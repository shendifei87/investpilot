"""Comps Generator — reads step2_comps_data.json and produces xlsx + summary md.

All PE/PB/PS ratios are self-calculated from price and EPS data in the JSON.
No pre-computed values from third parties are used.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.analysis.financial import calc_pe, calc_pe_forward


# ── Helpers ──────────────────────────────────────────────

def _load_comps_data(workspace: Path) -> dict:
    """Load and validate step2_comps_data.json from workspace."""
    path = workspace / "step2_comps_data.json"
    if not path.exists():
        raise FileNotFoundError(
            f"step2_comps_data.json not found in {workspace}. "
            "Create it first with peer financial data."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if "peers" not in data or not data["peers"]:
        raise ValueError("step2_comps_data.json has no peers array.")
    return data


def _safe_pe(price: float | None, eps: float | None) -> float | None:
    """Calculate PE, returning None if inputs invalid or negative result."""
    if price is None or eps is None or eps <= 0:
        return None
    return round(price / eps, 1)


def _fmt_pe(pe: float | None) -> str:
    if pe is None:
        return "N/M"
    return f"{pe:.1f}x"


def _fmt_pct(val: float | None, show_sign: bool = True) -> str:
    if val is None:
        return "N/A"
    sign = ("+" if val > 0 else "") if show_sign else ""
    return f"{sign}{val:.1f}%"


def _fmt_rev(val: float | None, ccy: str) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}B {ccy}"


def _staleness(as_of: str | None, threshold_days: int = 90) -> str:
    """Return 'fresh', 'stale', or 'very_stale' based on as_of date."""
    if not as_of:
        return "unknown"
    try:
        d = datetime.strptime(as_of, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "unknown"
    days = (date.today() - d).days
    if days <= threshold_days:
        return "fresh"
    elif days <= 180:
        return "stale"
    return "very_stale"


def _staleness_emoji(s: str) -> str:
    return {"fresh": "🟢", "stale": "🟡", "very_stale": "🔴"}.get(s, "⚪")


# ── Core logic ───────────────────────────────────────────

def compute_all_pe(data: dict) -> list[dict]:
    """Compute PE for all peers across FY2025A/FY2026E/FY2027E.

    Returns a list of dicts, one per peer, with 'name', 'ticker', and pe values.
    """
    rows = []
    for p in data["peers"]:
        fin = p.get("financials", {})
        row = {
            "name": p["name"],
            "ticker": p["ticker"],
            "market": p.get("market", ""),
            "is_target": p.get("is_target", False),
            "ccy": p["ccy"],
            "price": p["price"],
            "mcap_bn_usd": p.get("mcap_bn_usd"),
            "fy_end": p.get("fy_end", ""),
        }
        for fy in ["FY2025A", "FY2026E", "FY2027E"]:
            fy_data = fin.get(fy, {}) or {}
            eps = fy_data.get("eps")
            pe_result = calc_pe(p["price"], eps, label=fy)
            row[f"eps_{fy}"] = eps
            row[f"pe_{fy}"] = pe_result.get("pe")
            row[f"pe_valid_{fy}"] = pe_result.get("valid", False)
            # Track data freshness
            as_of = fy_data.get("as_of")
            row[f"source_{fy}"] = fy_data.get("source", "")
            row[f"as_of_{fy}"] = as_of
            row[f"freshness_{fy}"] = _staleness(as_of)

        # Revenue & margins from FY2025A
        fy25 = fin.get("FY2025A", {}) or {}
        row["revenue_25a"] = fy25.get("revenue_bn")
        row["revenue_25a_ccy"] = fy25.get("revenue_ccy", p["ccy"])
        row["rev_yoy_25a"] = fy25.get("rev_yoy")
        row["gm_pct"] = fy25.get("gm_pct")
        row["nm_pct"] = fy25.get("nm_pct")

        # Revenue growth forward
        for fy in ["FY2026E", "FY2027E"]:
            fy_data = fin.get(fy, {}) or {}
            row[f"revenue_{fy}"] = fy_data.get("revenue_bn")
            row[f"rev_yoy_{fy}"] = fy_data.get("rev_yoy")

        row["notes"] = p.get("notes", "")
        rows.append(row)
    return rows


def peer_statistics(rows: list[dict], fy: str, exclude_target: bool = True) -> dict:
    """Compute median/mean PE for non-target peers."""
    pool = [r for r in rows if (not exclude_target or not r["is_target"])]
    pe_vals = [r[f"pe_{fy}"] for r in pool if r.get(f"pe_{fy}") is not None]
    if not pe_vals:
        return {"median": None, "mean": None, "n": 0}
    return {
        "median": round(statistics.median(pe_vals), 1),
        "mean": round(statistics.mean(pe_vals), 1),
        "n": len(pe_vals),
    }


def target_premium(rows: list[dict], fy: str) -> dict | None:
    """Calculate target's premium/discount vs peer median."""
    target = next((r for r in rows if r["is_target"]), None)
    if not target:
        return None
    stats = peer_statistics(rows, fy, exclude_target=True)
    if stats["median"] is None or target.get(f"pe_{fy}") is None:
        return None
    pe_t = target[f"pe_{fy}"]
    pe_m = stats["median"]
    premium_pct = round(((pe_t / pe_m) - 1) * 100, 1)
    return {
        "target_pe": pe_t,
        "peer_median_pe": pe_m,
        "premium_pct": premium_pct,
        "direction": "premium" if premium_pct > 0 else "discount",
    }


# ── XLSX generation ──────────────────────────────────────

def generate_xlsx(data: dict, rows: list[dict], output_path: Path) -> Path:
    """Generate step2_comps_analysis.xlsx from computed data."""
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    except ImportError:
        raise ImportError("openpyxl required: pip install openpyxl")

    wb = openpyxl.Workbook()

    # Styles
    hdr_font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="2F5496")
    sub_fill = PatternFill("solid", fgColor="D6E4F0")
    sub_font = Font(name="Calibri", bold=True, size=10)
    data_font = Font(name="Calibri", size=10)
    note_font = Font(name="Calibri", size=9, italic=True, color="666666")
    highlight_fill = PatternFill("solid", fgColor="FFF2CC")
    stale_fill = PatternFill("solid", fgColor="FFCCCC")  # Red tint
    thin_border = Border(
        left=Side(style="thin", color="B4C6E7"),
        right=Side(style="thin", color="B4C6E7"),
        top=Side(style="thin", color="B4C6E7"),
        bottom=Side(style="thin", color="B4C6E7"),
    )

    ws = wb.active
    ws.title = "Comps"
    ws.sheet_properties.tabColor = "2F5496"

    col_widths = {"A": 28}
    for i, r in enumerate(rows):
        col_letter = chr(ord("B") + i)
        col_widths[col_letter] = 20
    col_widths[chr(ord("B") + len(rows))] = 14  # Median
    col_widths[chr(ord("B") + len(rows) + 1)] = 14  # Mean
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2 + len(rows) + 1)
    ws["A1"] = f"Peer Comps — {data['peers'][0]['name']} ({data['peers'][0]['ticker']}) — {date.today().strftime('%Y-%m-%d')}"
    ws["A1"].font = Font(name="Calibri", bold=True, size=14, color="2F5496")
    ws.row_dimensions[1].height = 28

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2 + len(rows) + 1)
    ws["A2"] = f"Benchmark: {data.get('benchmark_label', 'FY2026E Forward PE')}. All PE self-calculated (Price / EPS). source: calculated."
    ws["A2"].font = note_font

    row_idx = 4
    n_peers = len(rows)
    total_cols = 1 + n_peers + 2  # label + peers + median + mean

    def _col_offset(peer_idx: int) -> int:
        return peer_idx + 2  # 1-indexed: col B = peer 0

    # ── Header ──
    headers = ["Metric"] + [f"{r['name']}\n{r['ticker']}" for r in rows] + ["Peer\nMedian", "Peer\nMean"]
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=row_idx, column=ci, value=h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = thin_border
    ws.row_dimensions[row_idx].height = 36
    row_idx += 1

    def _section(title: str):
        nonlocal row_idx
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
        c = ws.cell(row=row_idx, column=1, value=title)
        c.font = sub_font
        c.fill = sub_fill
        for ci in range(1, total_cols + 1):
            ws.cell(row=row_idx, column=ci).border = thin_border
            ws.cell(row=row_idx, column=ci).fill = sub_fill
        row_idx += 1

    def _data_row(label: str, vals: list[str | None], highlight_col: int | None = None):
        nonlocal row_idx
        c = ws.cell(row=row_idx, column=1, value=label)
        c.font = Font(name="Calibri", bold=True, size=10)
        c.border = thin_border
        for ci, v in enumerate(vals, 2):
            c = ws.cell(row=row_idx, column=ci, value=v if v else "—")
            c.font = data_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border
            # Highlight target column
            target_peer_idx = next((i for i, r in enumerate(rows) if r["is_target"]), None)
            if target_peer_idx is not None and ci == _col_offset(target_peer_idx):
                c.fill = highlight_fill
        row_idx += 1

    # ── Company Overview ──
    _section("📊 Company Overview")
    _data_row("Exchange", [r.get("market", "") for r in rows] + ["—", "—"])
    _data_row("Price (Local)", [f"{r['price']:.2f} {r['ccy']}" for r in rows] + ["—", "—"])
    _data_row("Market Cap ($B USD)", [f"${r.get('mcap_bn_usd', 0):.1f}B" if r.get("mcap_bn_usd") else "N/A" for r in rows] + ["—", "—"])
    _data_row("Fiscal Year End", [r.get("fy_end", "") for r in rows] + ["—", "—"])

    # ── Revenue ──
    _section("📈 Revenue (Billions, Local Currency)")
    _data_row("FY2025A Revenue", [_fmt_rev(r.get("revenue_25a"), r.get("revenue_25a_ccy", r["ccy"])) for r in rows] + ["—", "—"])
    _data_row("FY2025A YoY Growth", [_fmt_pct(r.get("rev_yoy_25a")) for r in rows] + ["—", "—"])
    _data_row("FY2026E Revenue", [_fmt_rev(r.get("revenue_FY2026E"), r.get("revenue_25a_ccy", r["ccy"])) for r in rows] + ["—", "—"])
    _data_row("FY2026E YoY Growth", [_fmt_pct(r.get("rev_yoy_FY2026E")) for r in rows] + ["—", "—"])
    _data_row("FY2027E Revenue", [_fmt_rev(r.get("revenue_FY2027E"), r.get("revenue_25a_ccy", r["ccy"])) for r in rows] + ["—", "—"])
    _data_row("FY2027E YoY Growth", [_fmt_pct(r.get("rev_yoy_FY2027E")) for r in rows] + ["—", "—"])

    # ── EPS ──
    _section("💰 EPS (Local Currency)")
    _data_row("FY2025A EPS", [_fmt_pe_val(r.get("eps_FY2025A"), r["ccy"]) for r in rows] + ["—", "—"])
    _data_row("FY2026E EPS (Consensus)", [_fmt_pe_val(r.get("eps_FY2026E"), r["ccy"]) for r in rows] + ["—", "—"])
    _data_row("FY2027E EPS (Consensus)", [_fmt_pe_val(r.get("eps_FY2027E"), r["ccy"]) for r in rows] + ["—", "—"])

    # ── PE Valuation ──
    _section("⚖️ PE Ratio (Self-Calculated: Current Price ÷ EPS)")
    for fy in ["FY2025A", "FY2026E", "FY2027E"]:
        stats = peer_statistics(rows, fy, exclude_target=True)
        label_suffix = " ★" if fy == data.get("benchmark_year", "FY2026E") else ""
        pe_vals = [_fmt_pe(r.get(f"pe_{fy}")) for r in rows]
        med_str = _fmt_pe(stats["median"]) if stats["median"] else "N/A"
        mean_str = _fmt_pe(stats["mean"]) if stats["mean"] else "N/A"
        _data_row(f"PE {fy}{label_suffix}", pe_vals + [med_str, mean_str])

    # ── Margins ──
    _section("📊 Profitability (FY2025A)")
    _data_row("Gross Margin", [_fmt_pct(r.get("gm_pct"), show_sign=False) for r in rows] + ["—", "—"])
    _data_row("Net Margin", [_fmt_pct(r.get("nm_pct"), show_sign=False) for r in rows] + ["—", "—"])

    # ── Premium Analysis ──
    bm = data.get("benchmark_year", "FY2026E")
    prem = target_premium(rows, bm)
    if prem:
        _section(f"🔍 Target Premium vs Peers ({bm} Forward PE)")
        _data_row(f"Target PE ({bm})", [_fmt_pe(prem["target_pe"])] + [""] * (n_peers + 1))
        _data_row(f"Peer Median PE ({bm})", [_fmt_pe(prem["peer_median_pe"])] + [""] * (n_peers + 1))
        direction = prem["direction"]
        _data_row(f"Target vs Peers", [f"{abs(prem['premium_pct']):.1f}% {direction} to peer median"] + [""] * (n_peers + 1))

    # ── Data Freshness ──
    _section("📅 Data Freshness")
    for fy in ["FY2026E", "FY2027E"]:
        freshness_vals = []
        for r in rows:
            f = r.get(f"freshness_{fy}", "unknown")
            emoji = _staleness_emoji(f)
            as_of = r.get(f"as_of_{fy}", "")
            if as_of:
                freshness_vals.append(f"{emoji} {as_of}")
            else:
                freshness_vals.append(f"{emoji} no data")
        _data_row(f"Data Source ({fy})", freshness_vals + ["—", "—"])

    # ── Notes ──
    row_idx += 1
    _section("📋 Notes")
    standard_notes = [
        "1. All PE ratios self-calculated as Current Price ÷ EPS. Tag: source: calculated.",
        "2. Apple-to-Apple: benchmark year is marked with ★. No Trailing vs Forward mixing.",
        "3. Data freshness: 🟢 ≤90d, 🟡 91-180d, 🔴 >180d. Stale data may not reflect current consensus.",
    ]
    for n in standard_notes:
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
        c = ws.cell(row=row_idx, column=1, value=n)
        c.font = note_font
        c.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[row_idx].height = 18
        row_idx += 1

    # Per-peer notes
    for r in rows:
        if r.get("notes"):
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
            c = ws.cell(row=row_idx, column=1, value=f"{r['ticker']}: {r['notes']}")
            c.font = note_font
            c.alignment = Alignment(wrap_text=True)
            ws.row_dimensions[row_idx].height = 18
            row_idx += 1

    # ── Sheet 2: Raw Data ──
    ws2 = wb.create_sheet("Raw Data")
    ws2.sheet_properties.tabColor = "548235"
    raw_h = ["Company", "Ticker", "Metric", "FY2025A", "FY2026E", "FY2027E", "Unit", "Source", "Date", "Freshness"]
    for ci, h in enumerate(raw_h, 1):
        c = ws2.cell(row=1, column=ci, value=h)
        c.font = hdr_font
        c.fill = PatternFill("solid", fgColor="548235")
        c.border = thin_border
    ws2.column_dimensions["A"].width = 14
    ws2.column_dimensions["B"].width = 12
    ws2.column_dimensions["C"].width = 20
    ws2.column_dimensions["H"].width = 30
    ws2.column_dimensions["J"].width = 14

    rr = 2
    for r in rows:
        for metric, fy_keys in [
            ("Revenue", {
                "FY2025A": ("revenue_25a", "revenue_25a_ccy"),
                "FY2026E": ("revenue_FY2026E", "revenue_25a_ccy"),
                "FY2027E": ("revenue_FY2027E", "revenue_25a_ccy"),
            }),
            ("EPS", {
                "FY2025A": ("eps_FY2025A", "ccy"),
                "FY2026E": ("eps_FY2026E", "ccy"),
                "FY2027E": ("eps_FY2027E", "ccy"),
            }),
            ("PE (self-calc)", {
                "FY2025A": (f"pe_FY2025A", None),
                "FY2026E": (f"pe_FY2026E", None),
                "FY2027E": (f"pe_FY2027E", None),
            }),
        ]:
            ws2.cell(row=rr, column=1, value=r["name"]).font = data_font
            ws2.cell(row=rr, column=2, value=r["ticker"]).font = data_font
            ws2.cell(row=rr, column=3, value=metric).font = data_font
            ws2.cell(row=rr, column=10, value="source: calculated" if "PE" in metric else "Consensus/reported").font = data_font
            for fy, (val_key, unit_key) in fy_keys.items():
                val = r.get(val_key)
                if metric.startswith("PE"):
                    cell_val = _fmt_pe(val)
                    unit = "x"
                elif val is None:
                    cell_val = "N/A"
                    unit = ""
                else:
                    cell_val = f"{val:.2f}"
                    unit = r.get(unit_key, "") if unit_key else ""
                col_map = {"FY2025A": 4, "FY2026E": 5, "FY2027E": 6}
                ws2.cell(row=rr, column=col_map[fy], value=cell_val).font = data_font
                ws2.cell(row=rr, column=7, value=unit).font = data_font
                ws2.cell(row=rr, column=8, value=r.get(f"source_{fy}", "")).font = data_font
                ws2.cell(row=rr, column=9, value=r.get(f"as_of_{fy}", "")).font = data_font
            for ci in range(1, 11):
                ws2.cell(row=rr, column=ci).border = thin_border
            rr += 1
        rr += 1

    wb.save(str(output_path))
    return output_path


def _fmt_pe_val(eps: float | None, ccy: str) -> str:
    if eps is None:
        return "N/M (neg)"
    return f"{eps:.2f} {ccy}"


# ── Summary MD generation ────────────────────────────────

def generate_summary_md(data: dict, rows: list[dict], output_path: Path) -> Path:
    """Generate step2_comps_summary.md from computed data."""
    target = next((r for r in rows if r["is_target"]), rows[0])
    bm = data.get("benchmark_year", "FY2026E")
    prem = target_premium(rows, bm)
    stats = peer_statistics(rows, bm, exclude_target=True)

    lines = [
        f"# Step 2 Comps Summary — {target['name']} ({target['ticker']})",
        "",
        f"**日期**: {date.today().strftime('%Y-%m-%d')} | **价格**: {target['price']} {target['ccy']}",
        "",
        "---",
        "",
        "## Peer Universe",
        "",
    ]

    # Peer table
    lines.append("| Company | Ticker | Market | Market Cap (USD) | FY End |")
    lines.append("|:--------|:-------|:-------|:-----------------|:-------|")
    for r in rows:
        bold = "**" if r["is_target"] else ""
        mcap = f"${r.get('mcap_bn_usd', 0):.1f}B" if r.get("mcap_bn_usd") else "N/A"
        lines.append(f"| {bold}{r['name']}{bold} | {r['ticker']} | {r.get('market', '')} | {mcap} | {r.get('fy_end', '')} |")

    # PE table
    lines.extend(["", "---", "", f"## {bm} Forward PE (Primary Benchmark)", ""])
    lines.append("**Apple-to-Apple**: All PE self-calculated (Current Price ÷ EPS). `source: calculated`.")
    lines.append("")
    lines.append("| Company | Price | EPS | PE |")
    lines.append("|:--------|:------|:----|:--|")
    for r in rows:
        bold = "**" if r["is_target"] else ""
        eps_val = r.get(f"eps_{bm}")
        pe_val = r.get(f"pe_{bm}")
        lines.append(f"| {bold}{r['name']}{bold} | {r['price']:.2f} {r['ccy']} | {eps_val:.2f} {r['ccy'] if eps_val else ''} | {_fmt_pe(pe_val)} |")
    if stats["median"]:
        lines.append(f"| **Peer Median** | — | — | **{_fmt_pe(stats['median'])}** |")
    if stats["mean"]:
        lines.append(f"| **Peer Mean** | — | — | **{_fmt_pe(stats['mean'])}** |")

    if prem:
        lines.extend([
            "",
            f"**{target['name']} {prem['direction'].title()}**: {abs(prem['premium_pct']):.1f}% vs peer median ({_fmt_pe(prem['target_pe'])} vs {_fmt_pe(prem['peer_median_pe'])})",
        ])

    # Revenue growth
    lines.extend(["", "---", "", "## Revenue Growth Comparison", ""])
    lines.append("| Company | FY2025A | FY2026E YoY | FY2027E YoY |")
    lines.append("|:--------|:--------|:-----------|:-----------|")
    for r in rows:
        bold = "**" if r["is_target"] else ""
        rev_ccy = r.get("revenue_25a_ccy", r["ccy"])
        rev25 = _fmt_rev(r.get("revenue_25a"), rev_ccy)
        lines.append(f"| {bold}{r['name']}{bold} | {rev25} | {_fmt_pct(r.get('rev_yoy_FY2026E'))} | {_fmt_pct(r.get('rev_yoy_FY2027E'))} |")

    # Margins
    lines.extend(["", "---", "", "## Margin Comparison (FY2025A)", ""])
    lines.append("| Company | Gross Margin | Net Margin |")
    lines.append("|:--------|:-----------|:-----------|")
    for r in rows:
        bold = "**" if r["is_target"] else ""
        lines.append(f"| {bold}{r['name']}{bold} | {_fmt_pct(r.get('gm_pct'), show_sign=False)} | {_fmt_pct(r.get('nm_pct'), show_sign=False)} |")

    # Data freshness
    lines.extend(["", "---", "", "## Data Freshness", ""])
    lines.append("| Company | FY2026E Source | As Of | Freshness |")
    lines.append("|:--------|:--------------|:------|:----------|")
    for r in rows:
        freshness = r.get("freshness_FY2026E", "unknown")
        emoji = _staleness_emoji(freshness)
        as_of = r.get("as_of_FY2026E", "—")
        source = r.get("source_FY2026E", "—")
        lines.append(f"| {r['name']} | {source} | {as_of} | {emoji} {freshness} |")

    # Moat constraint
    lines.extend(["", "---", "", "## Moat → Valuation Constraint", ""])
    lines.append("*(Copy from step2_competitive_moat.md)*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by `python -m src.cli comps`*")
    lines.append(f"*Accompanying spreadsheet: step2_comps_analysis.xlsx*")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ── Public entry point ───────────────────────────────────

def run_comps(workspace: Path) -> dict:
    """Load data, compute PE, generate xlsx + summary md.

    Returns a summary dict with file paths and key metrics.
    """
    data = _load_comps_data(workspace)
    rows = compute_all_pe(data)
    bm = data.get("benchmark_year", "FY2026E")
    prem = target_premium(rows, bm)
    stats = peer_statistics(rows, bm, exclude_target=True)

    xlsx_path = workspace / "step2_comps_analysis.xlsx"
    md_path = workspace / "step2_comps_summary.md"

    generate_xlsx(data, rows, xlsx_path)
    generate_summary_md(data, rows, md_path)

    return {
        "xlsx": str(xlsx_path),
        "summary_md": str(md_path),
        "benchmark": bm,
        "target_pe": prem["target_pe"] if prem else None,
        "peer_median_pe": stats.get("median"),
        "premium_pct": prem["premium_pct"] if prem else None,
        "n_peers": len(rows),
        "data_date": data.get("date"),
    }
