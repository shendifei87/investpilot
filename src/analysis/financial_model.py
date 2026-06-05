"""Formula-linked financial forecast model generated from Step 4 assumptions.

The model artifact is intentionally JSON-first: it is the auditable source of
truth that can be rendered to HTML today and exported to Excel/Sheets later.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from src.analysis._base import resolve_workspace_path
from src.analysis.step4_schema import load_structured_assumptions
from src.storage import AtomicJSON


MODEL_JSON = "forecast_model.json"
MODEL_HTML = "forecast_model.html"


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return default
        is_pct = text.endswith("%")
        text = text.rstrip("%xX")
        try:
            out = float(text)
        except ValueError:
            return default
        return out / 100 if is_pct else out
    return default


def _fmt(value: Any, kind: str = "number") -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return escape(value, quote=True)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return escape(str(value), quote=True)
    if kind == "percent":
        return f"{v:.1%}"
    if kind == "multiple":
        return f"{v:.1f}x"
    if kind == "per_share":
        return f"{v:.2f}"
    return f"{v:,.1f}"


def _periods(structured: dict) -> list[str]:
    periods = structured.get("forecast_periods")
    if isinstance(periods, list) and len(periods) >= 3:
        return [str(p) for p in periods[:3]]
    years = []
    for row in structured.get("assumption_matrix", []) or []:
        y = row.get("year")
        if y and str(y) not in years:
            years.append(str(y))
    if len(years) >= 3:
        return years[:3]
    return ["T+1", "T+2", "T+3"]


def _matrix_lookup(structured: dict) -> dict[tuple[str, str], dict]:
    lookup = {}
    for row in structured.get("assumption_matrix", []) or []:
        var = str(row.get("variable", "")).lower()
        year = str(row.get("year", "T+1"))
        if var:
            lookup[(var, year)] = row
            lookup.setdefault((var, ""), row)
    return lookup


def _assumption_value(lookup: dict, names: list[str], period: str, default: float) -> float:
    for name in names:
        key = (name.lower(), period)
        if key in lookup:
            return _num(lookup[key].get("p50"), default)
    for name in names:
        key = (name.lower(), "")
        if key in lookup:
            return _num(lookup[key].get("p50"), default)
    return default


def _base_inputs(structured: dict, workspace: Path) -> tuple[dict, list[str]]:
    """Load base financial inputs, tracking which fields used fallback defaults.

    Returns (inputs_dict, defaults_used) where *defaults_used* lists the
    field names that fell back to a hard-coded default because the agent
    did not supply a value.
    """
    cv = {}
    p = workspace / "calculated_valuation.json"
    if p.exists():
        try:
            cv = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            cv = {}

    raw_inputs = {}
    rp = workspace / "valuation_raw_inputs.json"
    if rp.exists():
        try:
            raw_inputs = json.loads(rp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            raw_inputs = {}

    model_inputs = structured.get("financial_model_inputs", {}) or {}
    defaults_used: list[str] = []

    def _pick(primary, fallback_key=None, fallback_dict=None, default=0.0, field_name=""):
        """Return value from primary, then fallback, then default; track usage."""
        val = model_inputs.get(primary)
        if val is not None and not isinstance(val, bool):
            return _num(val, default)
        if fallback_key and fallback_dict:
            fb = fallback_dict.get(fallback_key)
            if fb is not None and not isinstance(fb, bool):
                return _num(fb, default)
        if field_name:
            defaults_used.append(field_name)
        return default

    shares = _pick("shares_outstanding", "shares_outstanding", raw_inputs, 0.0, "shares_outstanding")
    if shares <= 0:
        shares = 1.0
        if "shares_outstanding" not in defaults_used:
            defaults_used.append("shares_outstanding")

    price = _pick("current_price", default=0.0)
    if price <= 0:
        for key in ("pe_forward", "pe_trailing"):
            if isinstance(cv.get(key), dict):
                price = _num(cv[key].get("price"), 0.0)
                if price > 0:
                    break

    inputs = {
        "shares_outstanding": shares,
        "current_price": price,
        "cash": _pick("cash", "total_cash", raw_inputs, 0.0, "cash"),
        "debt": _pick("debt", "total_debt", raw_inputs, 0.0, "debt"),
        "equity": _pick("equity", "total_equity", raw_inputs, 0.0, "equity"),
        "nwc_ratio": _pick("nwc_ratio", default=0.08, field_name="nwc_ratio"),
        "ppe_ratio": _pick("ppe_ratio", default=0.25, field_name="ppe_ratio"),
        "other_assets_ratio": _pick("other_assets_ratio", default=0.05, field_name="other_assets_ratio"),
        "ap_ratio": _pick("ap_ratio", default=0.06, field_name="ap_ratio"),
        "dividend_payout": _pick("dividend_payout", default=0.0, field_name="dividend_payout"),
    }
    return inputs, defaults_used


def build_financial_model(workspace_dir: str | Path, ticker: str = "") -> dict:
    """Build a three-year formula-linked forecast model from Step 4 assumptions."""
    ws = resolve_workspace_path(workspace_dir)
    structured = load_structured_assumptions(ws)
    if not structured:
        raise FileNotFoundError(f"{ws / 'step4_structured_assumptions.json'} not found")

    periods = _periods(structured)
    lookup = _matrix_lookup(structured)
    inputs, defaults_used = _base_inputs(structured, ws)

    # Track assumption-matrix defaults for da_ratio / capex_ratio
    assumption_defaults: list[str] = []

    segments = [
        s for s in structured.get("segment_revenues", []) or []
        if str(s.get("name", "")).strip().lower() != "total"
    ]
    if not segments:
        raise ValueError("No segment_revenues found for financial model generation")

    model_segments = []
    total_revenue = {p: 0.0 for p in periods}
    for seg in segments:
        name = str(seg.get("name", "Segment"))
        base = _num(seg.get("base_revenue"), 0.0)
        values = {}
        prev = base
        for idx, period in enumerate(periods):
            growth = _num(seg.get(f"{period}_growth"), None)
            if growth is None:
                # T+1 uses segment p50; later years use explicit period total
                # growth when available, otherwise repeat the segment p50.
                fallback = _num(seg.get("p50_growth"), 0.0)
                growth = _assumption_value(
                    lookup,
                    [f"{name}_rev_growth", "rev_growth", "revenue_growth"],
                    period,
                    fallback,
                )
            revenue = prev * (1 + growth)
            values[period] = {
                "revenue": revenue,
                "growth": growth,
                "formula": (
                    f"{name} {period} revenue = prior period revenue × (1 + {period} growth)"
                ),
            }
            total_revenue[period] += revenue
            prev = revenue
        model_segments.append({"name": name, "base_revenue": base, "forecast": values})

    income_rows = []
    cashflow_rows = []
    balance_rows = []
    checks = []

    prev_cash = inputs["cash"]
    prev_nwc = sum(_num(s.get("base_revenue"), 0.0) for s in segments) * inputs["nwc_ratio"]
    prev_ppe = sum(_num(s.get("base_revenue"), 0.0) for s in segments) * inputs["ppe_ratio"]
    prev_equity = inputs["equity"]
    if prev_equity <= 0:
        prev_equity = prev_cash + prev_nwc + prev_ppe

    income_values = {}
    cash_values = {}
    balance_values = {}
    valuation_values = {}

    for period in periods:
        revenue = total_revenue[period]
        gm = _assumption_value(lookup, ["gross_margin", "gm"], period, 0.35)
        opex_ratio = _assumption_value(lookup, ["opex_ratio", "operating_expense_ratio"], period, 0.18)
        tax_rate = _assumption_value(lookup, ["tax_rate", "effective_tax_rate"], period, 0.20)
        da_ratio = _assumption_value(lookup, ["da_ratio", "depreciation_ratio"], period, 0.04)
        capex_ratio = _assumption_value(lookup, ["capex_ratio"], period, 0.06)
        nwc_ratio = _assumption_value(lookup, ["nwc_ratio"], period, inputs["nwc_ratio"])
        pe = _assumption_value(lookup, ["pe", "forward_pe"], period, 20.0)

        # Track assumption-matrix defaults (only on first period to avoid duplicates)
        if period == periods[0]:
            for var_name, names, default_val in [
                ("da_ratio", ["da_ratio", "depreciation_ratio"], 0.04),
                ("capex_ratio", ["capex_ratio"], 0.06),
            ]:
                found = any(
                    (name.lower(), period) in lookup or (name.lower(), "") in lookup
                    for name in names
                )
                if not found:
                    assumption_defaults.append(var_name)

        gross_profit = revenue * gm
        cogs = revenue - gross_profit
        opex = revenue * opex_ratio
        ebit = gross_profit - opex
        tax = max(0.0, ebit * tax_rate)
        net_income = ebit - tax
        eps = net_income / inputs["shares_outstanding"] if inputs["shares_outstanding"] else 0.0

        da = revenue * da_ratio
        capex = revenue * capex_ratio
        nwc = revenue * nwc_ratio
        delta_nwc = nwc - prev_nwc
        fcf = net_income + da - capex - delta_nwc
        dividends = max(0.0, net_income * inputs["dividend_payout"])
        ending_cash = prev_cash + fcf - dividends

        ppe = prev_ppe + capex - da
        other_assets = revenue * inputs["other_assets_ratio"]
        ap = revenue * inputs["ap_ratio"]
        debt = inputs["debt"]
        equity = prev_equity + net_income - dividends
        total_assets = ending_cash + nwc + ppe + other_assets
        total_liab_equity = ap + debt + equity
        bs_check = total_assets - total_liab_equity
        target_price = eps * pe

        income_values[period] = {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "gross_margin": gm,
            "opex": opex,
            "opex_ratio": opex_ratio,
            "ebit": ebit,
            "tax": tax,
            "tax_rate": tax_rate,
            "net_income": net_income,
            "eps": eps,
        }
        cash_values[period] = {
            "net_income": net_income,
            "da": da,
            "capex": capex,
            "delta_nwc": delta_nwc,
            "fcf": fcf,
            "dividends": dividends,
            "ending_cash": ending_cash,
        }
        balance_values[period] = {
            "cash": ending_cash,
            "nwc": nwc,
            "ppe": ppe,
            "other_assets": other_assets,
            "total_assets": total_assets,
            "ap": ap,
            "debt": debt,
            "equity": equity,
            "total_liab_equity": total_liab_equity,
            "balance_check": bs_check,
        }
        valuation_values[period] = {
            "eps": eps,
            "forward_pe": pe,
            "target_price": target_price,
        }

        checks.append({
            "period": period,
            "check": "Balance sheet balances",
            "actual": total_assets,
            "expected": total_liab_equity,
            "difference": bs_check,
            "tolerance": max(abs(total_assets), 1.0) * 0.02,
            "status": "OK" if abs(bs_check) <= max(abs(total_assets), 1.0) * 0.02 else "WARN",
            "notes": "Simplified model uses explicit cash/equity roll-forward; WARN means inputs need a fuller balance-sheet schedule.",
        })

        prev_cash = ending_cash
        prev_nwc = nwc
        prev_ppe = ppe
        prev_equity = equity

    def row(statement: str, label: str, key: str, formula: str, kind: str = "number"):
        values = {p: income_values[p].get(key, cash_values[p].get(key, balance_values[p].get(key))) for p in periods}
        return {"statement": statement, "label": label, "values": values, "formula": formula, "format": kind}

    income_rows = [
        row("Income Statement", "Revenue", "revenue", "Σ segment revenue", "number"),
        row("Income Statement", "COGS", "cogs", "Revenue × (1 - gross margin)", "number"),
        row("Income Statement", "Gross Profit", "gross_profit", "Revenue - COGS", "number"),
        row("Income Statement", "Gross Margin", "gross_margin", "Gross Profit / Revenue", "percent"),
        row("Income Statement", "Operating Expense", "opex", "Revenue × OpEx ratio", "number"),
        row("Income Statement", "EBIT", "ebit", "Gross Profit - Operating Expense", "number"),
        row("Income Statement", "Tax Expense", "tax", "MAX(0, EBIT × effective tax rate)", "number"),
        row("Income Statement", "Net Income", "net_income", "EBIT - Tax Expense", "number"),
        row("Income Statement", "EPS", "eps", "Net Income / shares outstanding", "per_share"),
    ]
    cashflow_rows = [
        {"statement": "Cash Flow", "label": "Net Income", "values": {p: cash_values[p]["net_income"] for p in periods}, "formula": "Linked from income statement", "format": "number"},
        {"statement": "Cash Flow", "label": "D&A", "values": {p: cash_values[p]["da"] for p in periods}, "formula": "Revenue × D&A ratio", "format": "number"},
        {"statement": "Cash Flow", "label": "Capex", "values": {p: cash_values[p]["capex"] for p in periods}, "formula": "Revenue × capex ratio", "format": "number"},
        {"statement": "Cash Flow", "label": "Change in NWC", "values": {p: cash_values[p]["delta_nwc"] for p in periods}, "formula": "Ending NWC - prior NWC", "format": "number"},
        {"statement": "Cash Flow", "label": "Free Cash Flow", "values": {p: cash_values[p]["fcf"] for p in periods}, "formula": "Net Income + D&A - Capex - Change in NWC", "format": "number"},
        {"statement": "Cash Flow", "label": "Ending Cash", "values": {p: cash_values[p]["ending_cash"] for p in periods}, "formula": "Beginning Cash + FCF - dividends", "format": "number"},
    ]
    balance_rows = [
        {"statement": "Balance Sheet", "label": "Cash", "values": {p: balance_values[p]["cash"] for p in periods}, "formula": "Linked from cash-flow ending cash", "format": "number"},
        {"statement": "Balance Sheet", "label": "Net Working Capital", "values": {p: balance_values[p]["nwc"] for p in periods}, "formula": "Revenue × NWC ratio", "format": "number"},
        {"statement": "Balance Sheet", "label": "PP&E", "values": {p: balance_values[p]["ppe"] for p in periods}, "formula": "Prior PP&E + Capex - D&A", "format": "number"},
        {"statement": "Balance Sheet", "label": "Other Assets", "values": {p: balance_values[p]["other_assets"] for p in periods}, "formula": "Revenue × other assets ratio", "format": "number"},
        {"statement": "Balance Sheet", "label": "Total Assets", "values": {p: balance_values[p]["total_assets"] for p in periods}, "formula": "Cash + NWC + PP&E + Other Assets", "format": "number"},
        {"statement": "Balance Sheet", "label": "AP / Operating Liabilities", "values": {p: balance_values[p]["ap"] for p in periods}, "formula": "Revenue × AP ratio", "format": "number"},
        {"statement": "Balance Sheet", "label": "Debt", "values": {p: balance_values[p]["debt"] for p in periods}, "formula": "Input debt balance", "format": "number"},
        {"statement": "Balance Sheet", "label": "Equity", "values": {p: balance_values[p]["equity"] for p in periods}, "formula": "Prior equity + net income - dividends", "format": "number"},
        {"statement": "Balance Sheet", "label": "Balance Check", "values": {p: balance_values[p]["balance_check"] for p in periods}, "formula": "Total assets - total liabilities & equity", "format": "number"},
    ]
    valuation_rows = [
        {"statement": "Valuation", "label": "EPS", "values": {p: valuation_values[p]["eps"] for p in periods}, "formula": "Linked from income statement", "format": "per_share"},
        {"statement": "Valuation", "label": "Forward PE", "values": {p: valuation_values[p]["forward_pe"] for p in periods}, "formula": "Step 4 assumption matrix", "format": "multiple"},
        {"statement": "Valuation", "label": "Target Price", "values": {p: valuation_values[p]["target_price"] for p in periods}, "formula": "EPS × Forward PE", "format": "per_share"},
    ]

    return {
        "version": 1,
        "ticker": ticker,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "step4_structured_assumptions.json",
        "model_conventions": {
            "unit": "same as source financial statements",
            "periods": periods,
            "case": "P50",
            "note": "Simplified formula-linked forecast model. Use the Checks section to identify where a fuller schedule is required.",
        },
        "inputs": inputs,
        "defaults_used": defaults_used + assumption_defaults,
        "segments": model_segments,
        "statements": {
            "income_statement": income_rows,
            "cash_flow": cashflow_rows,
            "balance_sheet": balance_rows,
            "valuation": valuation_rows,
        },
        "checks": checks,
    }


def render_financial_model_html(model: dict) -> str:
    """Render forecast model as an HTML section body."""
    periods = model["model_conventions"]["periods"]

    def table(rows: list[dict], title: str) -> str:
        head = "".join(f"<th>{escape(p, quote=True)}</th>" for p in periods)
        body = []
        for r in rows:
            kind = r.get("format", "number")
            vals = "".join(f"<td>{_fmt(r['values'].get(p), kind)}</td>" for p in periods)
            body.append(
                "<tr>"
                f"<td><strong>{escape(r['label'], quote=True)}</strong></td>"
                f"{vals}"
                f"<td>{escape(r.get('formula', ''), quote=True)}</td>"
                "</tr>"
            )
        return (
            f"<h4>{escape(title, quote=True)}</h4>"
            "<table class=\"financial-model-table\">"
            f"<thead><tr><th>Line Item</th>{head}<th>Formula / Link</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    seg_rows = []
    for seg in model["segments"]:
        for p in periods:
            f = seg["forecast"][p]
            seg_rows.append(
                "<tr>"
                f"<td>{escape(seg['name'], quote=True)}</td>"
                f"<td>{escape(p, quote=True)}</td>"
                f"<td>{_fmt(f['growth'], 'percent')}</td>"
                f"<td>{_fmt(f['revenue'])}</td>"
                f"<td>{escape(f['formula'], quote=True)}</td>"
                "</tr>"
            )
    checks = []
    for c in model["checks"]:
        checks.append(
            "<tr>"
            f"<td>{escape(c['period'], quote=True)}</td>"
            f"<td>{escape(c['check'], quote=True)}</td>"
            f"<td>{_fmt(c['difference'])}</td>"
            f"<td>{escape(c['status'], quote=True)}</td>"
            f"<td>{escape(c.get('notes', ''), quote=True)}</td>"
            "</tr>"
        )

    return (
        "<div class=\"financial-model\">"
        "<p><strong>Model conventions:</strong> P50 case, three-year forecast, formula-linked from Step 4 structured assumptions.</p>"
        "<h4>Segment Revenue Build</h4>"
        "<table class=\"financial-model-table\"><thead><tr>"
        "<th>Segment</th><th>Period</th><th>Growth</th><th>Revenue</th><th>Formula / Link</th>"
        f"</tr></thead><tbody>{''.join(seg_rows)}</tbody></table>"
        f"{table(model['statements']['income_statement'], 'Income Statement')}"
        f"{table(model['statements']['cash_flow'], 'Cash Flow')}"
        f"{table(model['statements']['balance_sheet'], 'Balance Sheet')}"
        f"{table(model['statements']['valuation'], 'Valuation Bridge')}"
        "<h4>Checks</h4>"
        "<table class=\"financial-model-table\"><thead><tr>"
        "<th>Period</th><th>Check</th><th>Difference</th><th>Status</th><th>Notes</th>"
        f"</tr></thead><tbody>{''.join(checks)}</tbody></table>"
        "</div>"
    )


def generate_financial_model_artifacts(workspace_dir: str | Path, ticker: str = "") -> dict:
    """Generate forecast_model.json and forecast_model.html in the workspace."""
    ws = resolve_workspace_path(workspace_dir)
    model = build_financial_model(ws, ticker=ticker)
    html_body = render_financial_model_html(model)
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>InvestPilot Forecast Model</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:28px;color:#1f2937}"
        "table{border-collapse:collapse;width:100%;margin:14px 0 24px;font-size:13px}"
        "th,td{border:1px solid #d1d5db;padding:7px 9px;text-align:right}"
        "th:first-child,td:first-child,td:last-child{text-align:left}"
        "th{background:#111827;color:white}.financial-model p{color:#4b5563}</style></head><body>"
        "<h1>InvestPilot Forecast Model</h1>"
        f"{html_body}</body></html>"
    )
    store = AtomicJSON(ws)
    json_path = store.save(MODEL_JSON, model)
    html_path = ws / MODEL_HTML
    html_path.write_text(html, encoding="utf-8")
    return {"model": model, "json_path": json_path, "html_path": html_path, "html_body": html_body}
