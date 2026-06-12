"""Bank-specific financial model for NIM-driven earnings projection.

Standard financial models (EPS = Revenue × Margin) don't work for banks.
Banks earn via Net Interest Margin (NIM) on interest-earning assets,
fee/commission income, and are constrained by capital adequacy ratios.

This module provides a lightweight NIM-driven earnings model:
  Net Interest Income = Average Earning Assets × NIM
  Non-Interest Income = Fee income + Trading income + Other
  Operating Expense   = Cost-to-Income ratio × Operating Income
  Credit Cost         = Average Loans × Credit Cost Rate
  Provision for Credit Losses = Credit Cost - Provision Release
  Net Profit = (NII + Non-NII) - OpEx - Credit Cost - Tax

Key outputs:
  - EPS projection (T+1 / T+2 / T+3)
  - ROE projection
  - NIM sensitivity analysis
  - Credit cost impact analysis
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

BANK_MODEL_INPUTS = [
    # Balance sheet (beginning of period)
    "total_assets",             # 总资产
    "earning_assets",           # 生息资产 (loans + investments + interbank)
    "total_loans",              # 客户贷款总额
    "total_deposits",           # 客户存款总额
    "interest_bearing_debt",    # 付息负债
    "shareholders_equity",      # 股东权益 (归属母公司)
    "shares_outstanding",       # 总股本

    # Income drivers
    "nim",                      # 净息差 (Net Interest Margin)
    "fee_income_ratio",         # 手续费收入 / 总资产
    "cost_to_income_ratio",     # 成本收入比
    "credit_cost_rate",         # 信用成本率 (bps, e.g. 50 = 0.50%)
    "tax_rate",                 # 有效税率

    # Growth assumptions
    "earning_assets_growth",    # 生息资产增速 %
    "loan_growth",              # 贷款增速 %
    "deposit_growth",           # 存款增速 %
    "nim_change_bp",            # NIM 变动 (bp, e.g. -5 = 下降5bp)
    "fee_growth",               # 非息收入增速 %

    # Capital
    "dividend_payout_ratio",    # 分红比率
    "target_car",               # 目标资本充足率
]

# ---------------------------------------------------------------------------
# Variable naming & unit conventions for Monte Carlo integration
# ---------------------------------------------------------------------------

# Mapping: step4 assumption_matrix variable name → canonical model input name.
# Used to translate between Step 4 naming and forecast_model/Monte Carlo naming.
BANK_VARIABLE_ALIASES = {
    "credit_cost": "credit_cost_rate",
    "payout_ratio": "dividend_payout_ratio",
    "fee_income_ratio": "fee_income_ratio",
}

# Reverse mapping: canonical → step4 name
BANK_VARIABLE_ALIASES_REV = {v: k for k, v in BANK_VARIABLE_ALIASES.items()}

# Variables stored as decimal in step4 but needed as percent in Monte Carlo.
# All others (nim, credit_cost_rate, npl) are already in percent.
BANK_DECIMAL_VARS = frozenset({
    "cost_to_income_ratio",
    "tax_rate",
    "roe",
    "dividend_payout_ratio",
})

# Variables where lower values are better (p10=worst/high, p90=best/low).
BANK_LOWER_IS_BETTER_VARS = frozenset({
    "credit_cost_rate",
    "cost_to_income_ratio",
    "tax_rate",
    "npl",
})

BANK_MODEL_OUTPUTS = [
    "interest_income",
    "interest_expense",
    "net_interest_income",
    "non_interest_income",
    "total_operating_income",
    "operating_expense",
    "credit_cost",
    "pre_provision_profit",
    "provision_for_credit_losses",
    "profit_before_tax",
    "income_tax",
    "net_profit",
    "eps",
    "bps",
    "roe",
    "nim_actual",
    "cost_to_income_actual",
    "dividend_per_share",
    "retained_earnings_addition",
]


# ---------------------------------------------------------------------------
# Step 4 → Monte Carlo normalization helpers
# ---------------------------------------------------------------------------

def normalize_step4_to_percent(
    assumption_matrix: list[dict],
    mc_variables: set[str] | None = None,
) -> dict[str, dict]:
    """Convert step4 assumption_matrix entries to uniform percent convention.

    Returns {canonical_name: {10: p10, 30: p30, 50: p50, 70: p70, 90: p90}}
    where ALL values are in percent (e.g. cost_to_income_ratio = 53.0 means 53%).

    Handles:
    1. Decimal→percent conversion for BANK_DECIMAL_VARS (×100).
    2. Alias resolution via BANK_VARIABLE_ALIASES (e.g. credit_cost → credit_cost_rate).
    3. Optional filtering to only mc_variables.

    Does NOT reverse lower_is_better — that is handled by
    fit_distribution_from_percentiles(direction="lower_is_better").
    """
    # If no filter specified, process all entries
    if mc_variables is None:
        mc_variables = None  # process all

    result = {}
    for entry in assumption_matrix:
        var = entry["variable"]
        # Resolve alias: step4 may use "credit_cost" but model uses "credit_cost_rate"
        canonical = BANK_VARIABLE_ALIASES.get(var, var)

        # If a filter is specified, skip variables not in it
        if mc_variables is not None and canonical not in mc_variables and var not in mc_variables:
            continue

        pctls = {
            10: entry["p10"],
            30: entry["p30"],
            50: entry["p50"],
            70: entry["p70"],
            90: entry["p90"],
        }

        # Convert decimal→percent for variables stored as decimal in step4
        if canonical in BANK_DECIMAL_VARS:
            pctls = {k: v * 100 for k, v in pctls.items()}

        result[canonical] = pctls
    return result


# Canonical set of variables used in bank Monte Carlo.
BANK_MC_VARIABLES = frozenset({
    "pb_forward", "nim", "credit_cost_rate", "cost_to_income_ratio",
    "roe", "npl", "tax_rate", "dividend_payout_ratio",
})


def build_bank_mc_distributions(
    assumption_matrix: list[dict],
    extra_bounds: dict | None = None,
    mc_variables: set[str] | None = None,
) -> dict:
    """Build Monte Carlo distributions from step4 assumption_matrix for a bank.

    Uses fit_distribution_from_percentiles with automatic direction handling
    from step4's ``direction`` field and decimal→percent unit normalization.

    Args:
        assumption_matrix: step4_structured_assumptions.json["assumption_matrix"]
        extra_bounds: optional {variable: {"lower": ..., "upper": ...}} overrides
        mc_variables: set of canonical variable names to include.
                      Defaults to BANK_MC_VARIABLES. Pass None to process all.

    Returns:
        {variable_name: NormalDist|LogNormalDist}
    """
    from src.analysis.monte_carlo import fit_distribution_from_percentiles

    if mc_variables is None:
        mc_variables = set(BANK_MC_VARIABLES)

    # Build lookup by original step4 variable name (for direction field)
    step4_by_var = {entry["variable"]: entry for entry in assumption_matrix}

    # Normalize units and resolve aliases, filtering to mc_variables only
    pctls_map = normalize_step4_to_percent(assumption_matrix, mc_variables=mc_variables)
    extra_bounds = extra_bounds or {}
    distributions = {}

    for canonical_var, pctls in pctls_map.items():
        dist_type = "lognormal" if canonical_var == "pb_forward" else "normal"

        # Look up direction from step4 entry (may be under alias name)
        step4_entry = step4_by_var.get(canonical_var)
        # If not found by canonical name, try alias reverse lookup
        if step4_entry is None:
            for orig, canon in BANK_VARIABLE_ALIASES.items():
                if canon == canonical_var and orig in step4_by_var:
                    step4_entry = step4_by_var[orig]
                    break

        raw_direction = "higher_is_better"
        if step4_entry and step4_entry.get("direction") == "lower_is_better":
            raw_direction = "lower_is_better"

        dist = fit_distribution_from_percentiles(
            pctls, dist_type=dist_type, direction=raw_direction,
        )

        # Apply extra bounds if provided
        if canonical_var in extra_bounds:
            bounds = extra_bounds[canonical_var]
            if "lower" in bounds:
                dist.lower = bounds["lower"]
            if "upper" in bounds:
                dist.upper = bounds["upper"]

        distributions[canonical_var] = dist

    return distributions


# ---------------------------------------------------------------------------
# Core projection engine
# ---------------------------------------------------------------------------

def project_bank_earnings(
    inputs: dict,
    periods: int = 3,
) -> dict:
    """Project bank earnings for T+1 through T+periods.

    Args:
        inputs: Dict with keys from BANK_MODEL_INPUTS.
        periods: Number of forward periods (default 3 for T+1/T+2/T+3).

    Returns:
        Dict with:
          - "periods": list of per-period projections
          - "summary": aggregate statistics
          - "sensitivity": NIM and credit cost sensitivity tables
    """
    results = []
    # Carry-forward state
    earning_assets = inputs["earning_assets"]
    total_loans = inputs["total_loans"]
    total_deposits = inputs["total_deposits"]
    equity = inputs["shareholders_equity"]
    nim = inputs["nim"]

    for i in range(1, periods + 1):
        # Growth
        ea_growth = _pct(inputs, "earning_assets_growth", i) / 100
        loan_growth = _pct(inputs, "loan_growth", i) / 100
        dep_growth = _pct(inputs, "deposit_growth", i) / 100
        nim_chg = _bp(inputs, "nim_change_bp", i)
        fee_gr = _pct(inputs, "fee_growth", i) / 100

        earning_assets *= (1 + ea_growth)
        total_loans *= (1 + loan_growth)
        total_deposits *= (1 + dep_growth)
        nim += nim_chg / 10000  # bp to decimal

        # Income
        nii = earning_assets * nim
        fee_base = nii * (inputs.get("fee_income_ratio", 0.08) / (nim if nim > 0 else 0.01))
        non_interest = fee_base * (1 + fee_gr)
        total_income = nii + non_interest

        # Expense
        cti = inputs["cost_to_income_ratio"] / 100
        opex = total_income * cti

        # Credit cost
        cc_rate = inputs["credit_cost_rate"] / 100  # bps to %
        credit_cost = total_loans * cc_rate

        # Profit
        ppop = total_income - opex
        pbt = ppop - credit_cost
        tax = pbt * (inputs["tax_rate"] / 100)
        net_profit = pbt - tax

        # Per-share
        shares = inputs["shares_outstanding"]
        eps = net_profit / shares
        dpr = inputs["dividend_payout_ratio"] / 100
        dps = eps * dpr
        retained = net_profit * (1 - dpr)
        equity += retained
        bps = equity / shares
        roe = net_profit / equity * 100

        results.append({
            "period": f"T+{i}",
            "earning_assets": round(earning_assets, 0),
            "total_loans": round(total_loans, 0),
            "total_deposits": round(total_deposits, 0),
            "nim": round(nim * 100, 4),  # as percentage
            "net_interest_income": round(nii, 0),
            "non_interest_income": round(non_interest, 0),
            "total_operating_income": round(total_income, 0),
            "operating_expense": round(opex, 0),
            "credit_cost": round(credit_cost, 0),
            "profit_before_tax": round(pbt, 0),
            "net_profit": round(net_profit, 0),
            "eps": round(eps, 4),
            "bps": round(bps, 4),
            "roe": round(roe, 2),
            "dps": round(dps, 4),
            "cost_to_income": round(cti * 100, 2),
        })

    # Sensitivity: NIM ±10bp
    sensitivity_nim = {}
    for delta_bp in [-10, -5, 0, 5, 10]:
        eps_list = []
        for p in results:
            adj_nii = p["earning_assets"] * (p["nim"] / 100 + delta_bp / 10000)
            adj_ni = p["total_operating_income"] - p["net_interest_income"] + adj_nii
            adj_pbt = adj_ni - p["operating_expense"] - p["credit_cost"]
            adj_tax = adj_pbt * (inputs["tax_rate"] / 100)
            adj_np = adj_pbt - adj_tax
            eps_list.append(round(adj_np / inputs["shares_outstanding"], 4))
        sensitivity_nim[f"nim_{delta_bp:+d}bp"] = eps_list

    # Sensitivity: credit cost ±10bp
    sensitivity_cc = {}
    for delta_bp in [-10, -5, 0, 5, 10]:
        eps_list = []
        for p in results:
            adj_cc = p["total_loans"] * (inputs["credit_cost_rate"] / 100 + delta_bp / 10000)
            adj_pbt = p["profit_before_tax"] + p["credit_cost"] - adj_cc
            adj_tax = adj_pbt * (inputs["tax_rate"] / 100)
            adj_np = adj_pbt - adj_tax
            eps_list.append(round(adj_np / inputs["shares_outstanding"], 4))
        sensitivity_cc[f"cc_{delta_bp:+d}bp"] = eps_list

    return {
        "periods": results,
        "sensitivity": {
            "nim_sensitivity": sensitivity_nim,
            "credit_cost_sensitivity": sensitivity_cc,
        },
        "inputs_used": inputs,
    }


def save_bank_model(model_output: dict, output_dir: Path, ticker: str) -> Path:
    """Save bank model output to JSON."""
    path = output_dir / f"{ticker}_bank_model.json"
    path.write_text(
        json.dumps(model_output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    # Auto-generate forecast_model.html if forecast_model.json exists
    _try_generate_forecast_html(output_dir)
    return path


def _try_generate_forecast_html(output_dir: Path) -> None:
    """Generate forecast_model.html from forecast_model.json if it exists."""
    forecast_path = output_dir / "forecast_model.json"
    html_path = output_dir / "forecast_model.html"
    if not forecast_path.exists():
        return

    try:
        data = json.loads(forecast_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    periods = data.get("periods", {})
    pkeys = sorted(periods.keys())
    if not pkeys:
        return

    price = data.get("price", 0)
    pb_p50 = data.get("valuation", {}).get("pb_forward_p50", 0)
    ddm = data.get("valuation", {})
    sens = data.get("sensitivity", {})

    def _b(v: float) -> str:
        """Format as 亿."""
        return f"{v / 1e8:,.0f}" if v else "—"

    rows = []
    # ── Income Statement section ──
    rows.append("<h2>Income Statement (亿元)</h2>")
    rows.append('<table><tr><th>Item</th>')
    for pk in pkeys:
        rows.append(f'<th>{pk}</th>')
    rows.append('</tr>')

    for label, key, is_total in [
        ("净利息收入 NII", "net_interest_income", True),
        ("非利息收入", "non_interest_income", False),
        ("营业收入合计", "total_operating_income", True),
        ("营业支出", "operating_expense", False),
        ("信用减值损失", "credit_cost", False),
        ("税前利润", "profit_before_tax", True),
        ("净利润", "net_profit", True),
    ]:
        cls = ' class="total"' if is_total else ''
        rows.append(f'<tr{cls}><td>{label}</td>')
        for pk in pkeys:
            v = periods[pk].get(key, 0)
            rows.append(f'<td>{_b(v)}</td>')
        rows.append('</tr>')

    # Per-share
    for label, key in [("EPS (元)", "eps"), ("BPS (元)", "bps")]:
        rows.append(f'<tr class="grand"><td>{label}</td>')
        for pk in pkeys:
            rows.append(f'<td>{periods[pk].get(key, 0):.4f}</td>')
        rows.append('</tr>')
    rows.append('<tr class="total"><td>ROE (%)</td>')
    for pk in pkeys:
        rows.append(f'<td>{periods[pk].get("roe_pct", 0):.2f}</td>')
    rows.append('</tr></table>')

    # ── Key Ratios ──
    rows.append("<h2>Key Banking Ratios</h2><table>")
    rows.append('<tr><th>Ratio</th>')
    for pk in pkeys:
        rows.append(f'<th>{pk}</th>')
    rows.append('</tr>')
    for label, key in [("NIM (%)", "nim_pct"), ("ROE (%)", "roe_pct"), ("Cost-to-Income (%)", "cost_to_income_pct")]:
        rows.append(f'<tr><td>{label}</td>')
        for pk in pkeys:
            rows.append(f'<td>{periods[pk].get(key, 0):.2f}</td>')
        rows.append('</tr>')
    rows.append('</table>')

    # ── Valuation ──
    rows.append("<h2>Valuation Bridge</h2><table>")
    rows.append('<tr><th>Method</th><th>Value</th><th>vs Price</th></tr>')
    if pb_p50 and pkeys:
        bps0 = periods[pkeys[0]].get("bps", 0)
        tgt = bps0 * pb_p50
        rows.append(f'<tr><td>PB×BPS (P50={pb_p50}x)</td><td>{tgt:.2f}</td><td>+{(tgt/price-1)*100:.1f}%</td></tr>')
    for label, key in [("DDM Gordon", "ddm_gordon"), ("DDM 2-Stage", "ddm_2stage")]:
        v = ddm.get(key)
        if v:
            rows.append(f'<tr><td>{label}</td><td>{v:.2f}</td><td>+{(v/price-1)*100:.1f}%</td></tr>')
    rows.append('</table>')

    # ── Sensitivity ──
    for section, key in [("NIM Sensitivity (EPS)", "nim_sensitivity"), ("Credit Cost Sensitivity (EPS)", "credit_cost_sensitivity")]:
        tbl = sens.get(key, {})
        if not tbl:
            continue
        rows.append(f"<h2>{section}</h2><table><tr><th>Scenario</th>")
        for pk in pkeys:
            rows.append(f'<th>{pk}</th>')
        rows.append('</tr>')
        for scenario, vals in tbl.items():
            rows.append(f'<tr><td>{scenario}</td>')
            for v in vals:
                rows.append(f'<td>{v:.4f}</td>')
            rows.append('</tr>')
        rows.append('</table>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>Bank Forecast Model</title>
<style>
body {{font-family:'Microsoft YaHei',Arial,sans-serif;margin:20px;background:#f8f9fa;}}
h1 {{color:#1a1a2e;border-bottom:2px solid #16213e;padding-bottom:8px;}}
h2 {{color:#0f3460;margin-top:30px;}}
table {{border-collapse:collapse;width:100%;margin:10px 0;background:white;box-shadow:0 1px 3px rgba(0,0,0,0.1);}}
th {{background:#1a1a2e;color:white;padding:10px 12px;text-align:right;font-size:13px;}}
th:first-child {{text-align:left;}}
td {{padding:8px 12px;border-bottom:1px solid #e0e0e0;text-align:right;font-size:13px;}}
td:first-child {{text-align:left;font-weight:500;}}
tr:hover {{background:#f0f4ff;}}
.total {{font-weight:bold;background:#e8f4fd;}}
.grand {{font-weight:bold;background:#d4e6f1;border-top:2px solid #2980b9;}}
footer {{margin-top:40px;padding-top:10px;border-top:1px solid #ccc;color:#999;font-size:11px;}}
</style></head><body>
<h1>Bank Forecast Model</h1>
<p style="color:#666;font-size:12px;">Model: NIM-Driven | Price: {price} | Valuation: PB-primary</p>
{''.join(rows)}
<footer>Generated by InvestPilot Bank Model Engine | source: calculated</footer>
</body></html>"""

    html_path.write_text(html, encoding="utf-8")


def ddm_valuation(
    dps_t1: float,
    growth_rate: float,
    required_return: float,
    terminal_growth: Optional[float] = None,
) -> dict:
    """Dividend Discount Model (Gordon Growth / 2-stage).

    Used as auxiliary valuation for bank stocks alongside PB.

    Args:
        dps_t1: Expected dividend per share in T+1.
        growth_rate: Expected dividend growth rate (%, e.g. 3 = 3%).
        required_return: Required rate of return (%, e.g. 8 = 8%).
        terminal_growth: Terminal growth rate (%, default = growth_rate - 1%).

    Returns:
        dict with intrinsic_value, assumptions, and model type.
    """
    g = growth_rate / 100
    r = required_return / 100

    if terminal_growth is None:
        terminal_growth = max(growth_rate - 1.0, 0.5)
    gt = terminal_growth / 100

    # Single-stage Gordon Growth
    if r <= g:
        return {
            "model": "DDM (Gordon Growth)",
            "intrinsic_value": None,
            "valid": False,
            "error": f"Required return ({required_return}%) <= growth ({growth_rate}%), model invalid",
        }

    intrinsic = dps_t1 / (r - g)

    # Also compute 2-stage (high growth for 5 years, then terminal)
    pv_dividends = 0.0
    dps = dps_t1
    for year in range(1, 6):
        pv = dps / (1 + r) ** year
        pv_dividends += pv
        dps *= (1 + g)

    terminal_value = dps / (r - gt)
    pv_terminal = terminal_value / (1 + r) ** 5
    intrinsic_2stage = pv_dividends + pv_terminal

    return {
        "model": "DDM (Gordon Growth + 2-Stage)",
        "intrinsic_value_gordon": round(intrinsic, 2),
        "intrinsic_value_2stage": round(intrinsic_2stage, 2),
        "dps_t1": dps_t1,
        "growth_rate": growth_rate,
        "terminal_growth": round(terminal_growth, 2),
        "required_return": required_return,
        "valid": True,
        "source": "calculated",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(inputs: dict, key: str, period: int) -> float:
    """Get a percentage value, supporting per-period overrides.

    If inputs[key] is a list, use inputs[key][period-1].
    Otherwise, use the scalar value.
    """
    val = inputs.get(key, 0)
    if isinstance(val, list):
        idx = min(period - 1, len(val) - 1)
        return float(val[idx])
    return float(val)


def _bp(inputs: dict, key: str, period: int) -> float:
    """Get a basis-point value, supporting per-period overrides."""
    val = inputs.get(key, 0)
    if isinstance(val, list):
        idx = min(period - 1, len(val) - 1)
        return float(val[idx])
    return float(val)
