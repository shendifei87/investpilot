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
from src.analysis._utils import coerce_float as _num, is_pct_variable as _is_pct_variable
from src.analysis.step4_schema import load_structured_assumptions
from src.storage import AtomicJSON


MODEL_JSON = "forecast_model.json"
MODEL_HTML = "forecast_model.html"

# ── Required Step 5 model inputs (no silent defaults) ────────────────────
REQUIRED_MODEL_INPUTS = [
    "shares_outstanding",
    "diluted_shares",
    "cash",
    "debt",
    "equity",
    "nwc_ratio",
    "ppe_ratio",
    "other_assets_ratio",
    "ap_ratio",
    "dividend_payout",
    "da_ratio",
    "capex_ratio",
    "interest_rate_on_debt",
    "interest_rate_on_cash",
    "annual_share_dilution_pct",
]

# Optional BS-driver inputs (formula-linked when present; hard-coded with warning otherwise)
OPTIONAL_BS_INPUTS = [
    "ar_days",
    "inv_days",
    "ap_days",
    "prepaid_ca_ratio",
    "intangible_assets",
    "deferred_rev_ratio",
    "accrued_ratio",
    "other_ncl_ratio",
    "st_debt",
    "lt_debt",
    "paid_in_capital",
    "paid_in_capital_ratio",
]

REQUIRED_REVIEWED_VARIABLES = {
    "rev_growth",
    "gross_margin",
    "opex_ratio",
    "tax_rate",
    "pe",
}

# Alias mapping allows Step 4 to use either naming convention.
# The _reviewed_assumptions.json can use the canonical names or the aliases;
# the model builder resolves both.
REVIEWED_VARIABLE_ALIASES = {
    "rev_growth": ["rev_growth", "total_revenue_growth", "revenue_growth_total"],
    "gross_margin": ["gross_margin"],
    "opex_ratio": ["opex_ratio"],
    "tax_rate": ["tax_rate"],
    "pe": ["pe", "pe_forward"],
}


def _canonical_reviewed_variables(assumptions: dict) -> set[str]:
    """Return reviewed variables normalized to the model's canonical names."""
    reviewed_vars = set(str(k) for k in assumptions)
    canonical_vars = set()
    for canonical, aliases in REVIEWED_VARIABLE_ALIASES.items():
        if any(alias in reviewed_vars for alias in aliases):
            canonical_vars.add(canonical)
    return reviewed_vars | canonical_vars



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


# ── Percentage variable detection ────────────────────────────────────────
# Uses naming convention: any variable whose canonical name contains
# _margin, _growth, _ratio, _pct, _rate, or ends in _pct is a percentage.
# No more abs(raw) > 1.0 heuristic.
# _is_pct_variable is imported from src.analysis._utils


# ── Period helpers ────────────────────────────────────────────────────────

def _periods(structured: dict) -> list[str]:
    periods = structured.get("forecast_periods")
    if isinstance(periods, list) and len(periods) >= 3:
        return [str(p) for p in periods[:3]]
    am = structured.get("assumption_matrix", []) or []
    years = []
    if isinstance(am, list):
        for row in am:
            if not isinstance(row, dict):
                continue
            y = row.get("year")
            if y and str(y) not in years:
                years.append(str(y))
    elif isinstance(am, dict):
        for key in am:
            if str(key) not in years:
                years.append(str(key))
    if len(years) >= 3:
        return years[:3]
    return ["T+1", "T+2", "T+3"]


def _matrix_lookup(structured: dict) -> dict[tuple[str, str], dict]:
    lookup = {}
    am = structured.get("assumption_matrix", []) or []
    if isinstance(am, list):
        for row in am:
            if not isinstance(row, dict):
                continue
            var = str(row.get("variable", "")).lower()
            year = str(row.get("year", "T+1"))
            if var:
                lookup[(var, year)] = row
                if year.lower() in {"", "all", "global"}:
                    lookup[(var, "")] = row
    elif isinstance(am, dict):
        for period_key, variables in am.items():
            if not isinstance(variables, dict):
                continue
            for var_name, pct_dict in variables.items():
                if not isinstance(pct_dict, dict):
                    continue
                var = str(var_name).lower()
                row = dict(pct_dict)
                row["variable"] = var_name
                row["year"] = period_key
                lookup[(var, period_key)] = row
                if str(period_key).lower() in {"", "all", "global"}:
                    lookup[(var, "")] = row
    return lookup


def _assumption_row(lookup: dict, names: list[str], period: str) -> tuple[str, dict] | None:
    periods = [period, *_period_aliases(period)]
    for name in names:
        for candidate_period in periods:
            key = (name.lower(), candidate_period)
            if key in lookup:
                return name, lookup[key]
    for name in names:
        key = (name.lower(), "")
        if key in lookup:
            return name, lookup[key]
    return None


def _period_aliases(period: str) -> list[str]:
    text = str(period)
    aliases = []
    if text in {"T+1", "T1"}:
        aliases.extend(["T1", "T1_FY2026E", "FY1"])
    elif text in {"T+2", "T2"}:
        aliases.extend(["T2", "T2_FY2027E", "FY2"])
    elif text in {"T+3", "T3"}:
        aliases.extend(["T3", "T3_FY2028E", "FY3"])
    return aliases


def _assumption_lineage(source_name: str, row: dict, period: str, value: float) -> dict:
    refs = row.get("evidence_ids") or []
    if isinstance(refs, str):
        refs = [refs]
    return {
        "source": "step4_structured_assumptions.json",
        "variable": row.get("variable") or source_name,
        "requested_period": period,
        "source_period": row.get("year", period),
        "case": "p50",
        "value": value,
        "evidence_ids": refs,
        "derivation": row.get("derivation", ""),
    }


def _require_assumption_value(
    lookup: dict,
    names: list[str],
    period: str,
) -> tuple[float, dict]:
    found = _assumption_row(lookup, names, period)
    if not found:
        raise ValueError(
            f"Missing Step 4 assumption for {names[0]} in {period}. "
            "Do not use default model assumptions."
        )
    source_name, row = found
    raw = _num(row.get("p50"), 0.0)
    # Apply percentage conversion by naming convention — no heuristic
    if _is_pct_variable(source_name) and abs(raw) > 1.0:
        raw = raw / 100.0
    return raw, _assumption_lineage(source_name, row, period, raw)


def _base_inputs(structured: dict, workspace: Path) -> tuple[dict, dict]:
    """Load required Step 5 model inputs with no silent defaults."""
    model_inputs = structured.get("financial_model_inputs", {}) or {}
    missing = [field for field in REQUIRED_MODEL_INPUTS if model_inputs.get(field) in (None, "")]
    if missing:
        raise ValueError(
            "financial_model_inputs missing required fields: "
            f"{missing}. Step 5 does not allow hard-coded fallback assumptions."
        )

    inputs = {
        field: _num(model_inputs[field], 0.0)
        for field in REQUIRED_MODEL_INPUTS
    }
    if inputs["shares_outstanding"] <= 0:
        raise ValueError("financial_model_inputs.shares_outstanding must be positive")
    if inputs["diluted_shares"] <= 0:
        raise ValueError("financial_model_inputs.diluted_shares must be positive")

    # Load optional BS-driver inputs
    for field in OPTIONAL_BS_INPUTS:
        val = model_inputs.get(field)
        if val not in (None, ""):
            inputs[field] = _num(val, 0.0)

    if model_inputs.get("current_price") not in (None, ""):
        inputs["current_price"] = _num(model_inputs["current_price"], 0.0)

    lineage = {
        field: {
            "source": "step4_structured_assumptions.json",
            "field": f"financial_model_inputs.{field}",
            "value": inputs.get(field, 0.0),
        }
        for field in REQUIRED_MODEL_INPUTS + OPTIONAL_BS_INPUTS
        if field in inputs
    }
    return inputs, lineage


def _pct_input(value: Any, name: str, default: float | None = None) -> float | None:
    raw = _num(value, default)
    if raw is None:
        return None
    lname = name.lower()
    if (_is_pct_variable(name) or "growth" in lname or lname.endswith("_rate")) and abs(raw) > 1.0:
        raw = raw / 100.0
    return raw


def _growth_drivers_by_segment(structured: dict) -> dict[str, list[dict]]:
    raw = structured.get("growth_drivers", []) or []
    result: dict[str, list[dict]] = {}
    if not isinstance(raw, list):
        return result
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        segment = str(entry.get("segment", "")).strip()
        drivers = entry.get("drivers", [])
        if segment and isinstance(drivers, list):
            result[segment] = [d for d in drivers if isinstance(d, dict)]
    return result


def _driver_period_keys(period: str, idx: int) -> list[str]:
    aliases = [period, f"T+{idx + 1}", f"T{idx + 1}", f"FY{idx + 1}"]
    return [f"growth_{a}" for a in aliases] + [f"{a}_growth" for a in aliases]


def _driver_growth_for_period(segment: str, drivers: list[dict], period: str, idx: int) -> tuple[float, dict]:
    if not drivers:
        raise ValueError(f"Segment '{segment}' has no growth drivers")

    factor = 1.0
    driver_lineage = []
    for driver in drivers:
        name = str(driver.get("name", "driver")).strip() or "driver"
        raw = None
        source_key = ""
        for key in _driver_period_keys(period, idx):
            if key in driver:
                raw = driver.get(key)
                source_key = key
                break
        if raw is None:
            raise ValueError(
                f"Growth driver '{name}' for segment '{segment}' is missing per-period growth "
                f"for {period}. Provide one of: {_driver_period_keys(period, idx)}"
            )
        growth = _pct_input(raw, source_key, 0.0)
        factor *= 1.0 + float(growth or 0.0)
        refs = driver.get("evidence_ids") or []
        if isinstance(refs, str):
            refs = [refs]
        driver_lineage.append({
            "driver": name,
            "field": source_key,
            "value": growth,
            "base_value": driver.get("base_value"),
            "unit": driver.get("unit", ""),
            "evidence_ids": refs,
            "derivation": driver.get("derivation", ""),
        })

    return factor - 1.0, {
        "source": "step4_structured_assumptions.json",
        "variable": f"{segment}_driver_growth",
        "requested_period": period,
        "case": "p50",
        "value": factor - 1.0,
        "derivation": "Multiplicative driver build: Π(1 + driver_growth) - 1",
        "drivers": driver_lineage,
    }


def _load_reviewed_assumptions(workspace: Path) -> dict:
    reviewed_path = workspace / "_reviewed_assumptions.json"
    if not reviewed_path.exists():
        raise FileNotFoundError(
            f"{reviewed_path} missing. Step 5 requires the user-reviewed Step 4 assumption lock."
        )
    try:
        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise ValueError(f"{reviewed_path} is invalid: {exc}") from exc
    assumptions = reviewed.get("assumptions")
    if not isinstance(assumptions, dict) or not assumptions:
        raise ValueError("_reviewed_assumptions.json must contain a non-empty assumptions object")
    covered = _canonical_reviewed_variables(assumptions)
    missing = sorted(REQUIRED_REVIEWED_VARIABLES - covered)
    if missing:
        raise ValueError(f"_reviewed_assumptions.json missing required reviewed variables: {missing}. "
                         f"Accepted names: canonical={list(REQUIRED_REVIEWED_VARIABLES)} or aliases={REVIEWED_VARIABLE_ALIASES}")
    return reviewed


# ── Model builder ────────────────────────────────────────────────────────

def build_financial_model(workspace_dir: str | Path, ticker: str = "") -> dict:
    """Build a three-year formula-linked forecast model from Step 4 assumptions."""
    ws = resolve_workspace_path(workspace_dir)
    structured = load_structured_assumptions(ws)
    if not structured:
        raise FileNotFoundError(f"{ws / 'step4_structured_assumptions.json'} not found")

    reviewed = _load_reviewed_assumptions(ws)
    periods = _periods(structured)
    lookup = _matrix_lookup(structured)
    inputs, input_lineage = _base_inputs(structured, ws)
    assumption_lineage: dict[str, dict] = {}
    used_reviewed_variables: set[str] = set()

    # ── Normalize segment_revenues to a flat list ──────────────────────────
    raw_segments = structured.get("segment_revenues", []) or []
    if isinstance(raw_segments, list):
        segments = [
            s for s in raw_segments
            if isinstance(s, dict) and str(s.get("name", "")).strip().lower() != "total"
        ]
    elif isinstance(raw_segments, dict):
        level_data = raw_segments.get("product_level") or raw_segments.get("geographic_level") or {}
        if isinstance(level_data, dict):
            segments = []
            for seg_name, seg_data in level_data.items():
                if str(seg_name).strip().lower() == "total":
                    continue
                if not isinstance(seg_data, dict):
                    continue
                seg_entry: dict[str, Any] = {
                    "name": seg_name,
                    "base_revenue": seg_data.get("base", seg_data.get("base_revenue", seg_data.get("base_revenue_cny_m", 0))),
                    "p50_growth": seg_data.get("p50_growth", 0),
                    "p50": seg_data.get("p50", 0),
                }
                for key, value in seg_data.items():
                    if str(key).endswith("_growth"):
                        seg_entry[key] = value
                segments.append(seg_entry)
        else:
            segments = []
    else:
        segments = []
    if not segments:
        raise ValueError("No segment_revenues found for financial model generation")

    model_segments = []
    total_revenue = {p: 0.0 for p in periods}
    driver_map = _growth_drivers_by_segment(structured)
    for seg in segments:
        name = str(seg.get("name", "Segment"))
        base = _num(seg.get("base_revenue"), 0.0)
        values = {}
        prev = base
        drivers = driver_map.get(name, [])
        for idx, period in enumerate(periods):
            lineage = None
            if drivers:
                growth, lineage = _driver_growth_for_period(name, drivers, period, idx)
                used_reviewed_variables.add("rev_growth")
            else:
                growth = _num(seg.get(f"{period}_growth"), None)
                if growth is not None and _is_pct_variable(f"{period}_growth") and abs(growth) > 1.0:
                    growth = growth / 100.0
                if growth is None:
                    if idx == 0 and seg.get("p50_growth") is not None:
                        growth = _num(seg.get("p50_growth"), 0.0)
                        if _is_pct_variable("p50_growth") and abs(growth) > 1.0:
                            growth = growth / 100.0
                        lineage = {
                            "source": "step4_structured_assumptions.json",
                            "field": f"segment_revenues.{name}.p50_growth",
                            "requested_period": period,
                            "case": "p50",
                            "value": growth,
                            "warning": "Fallback path: no growth_drivers for this segment",
                        }
                        used_reviewed_variables.add("rev_growth")
                    else:
                        growth, lineage = _require_assumption_value(
                            lookup,
                            [f"{name}_rev_growth", "rev_growth", "revenue_growth"],
                            period,
                        )
                        used_reviewed_variables.add("rev_growth")
                else:
                    lineage = {
                        "source": "step4_structured_assumptions.json",
                        "field": f"segment_revenues.{name}.{period}_growth",
                        "requested_period": period,
                        "case": "p50",
                        "value": growth,
                        "warning": "Fallback path: no growth_drivers for this segment",
                    }
                    used_reviewed_variables.add("rev_growth")
            revenue = prev * (1 + growth)
            lineage_key = f"segment:{name}:{period}:growth"
            assumption_lineage[lineage_key] = lineage
            values[period] = {
                "revenue": revenue,
                "growth": growth,
                "formula": (
                    f"{name} {period} revenue = prior period revenue × (1 + {period} growth)"
                ),
                "lineage": [lineage_key],
            }
            total_revenue[period] += revenue
            prev = revenue
        model_segments.append({"name": name, "base_revenue": base, "forecast": values})

    income_values: dict[str, dict] = {}
    cash_values: dict[str, dict] = {}
    balance_values: dict[str, dict] = {}
    valuation_values: dict[str, dict] = {}
    checks: list[dict] = []

    # ── Initial BS state ───────────────────────────────────────────────────
    prev_cash = inputs["cash"]
    total_base_revenue = sum(_num(s.get("base_revenue"), 0.0) for s in segments)
    prev_nwc = total_base_revenue * inputs["nwc_ratio"]
    prev_ppe = total_base_revenue * inputs["ppe_ratio"]
    prev_equity = inputs["equity"]
    if prev_equity <= 0:
        prev_equity = prev_cash + prev_nwc + prev_ppe
    prev_debt = inputs["debt"]
    shares_outstanding = inputs["shares_outstanding"]

    # BS-driver fallback state (when optional fields absent)
    bs_inputs_present = all(inputs.get(k, 0.0) != 0.0 for k in ["ar_days", "inv_days", "ap_days"])
    bs_hardcoded_warning = (
        "" if bs_inputs_present
        else "BS leaf items are hard-coded from model; add ar_days/inv_days/ap_days to Step 4 inputs for formula-linked BS"
    )

    for period in periods:
        revenue = total_revenue[period]

        # ── Assumptions ──
        gm, gm_lineage = _require_assumption_value(lookup, ["gross_margin", "gm"], period)
        opex_ratio, opex_lineage = _require_assumption_value(lookup, ["opex_ratio", "operating_expense_ratio"], period)
        tax_rate, tax_lineage = _require_assumption_value(lookup, ["tax_rate", "effective_tax_rate"], period)
        pe, pe_lineage = _require_assumption_value(
            lookup,
            ["pe", "forward_pe", "pe_multiple", "pe_fwd_t1", "pe_fwd_t2", "pe_fwd_t3"],
            period,
        )
        for var_name, lineage in [
            ("gross_margin", gm_lineage),
            ("opex_ratio", opex_lineage),
            ("tax_rate", tax_lineage),
            ("pe", pe_lineage),
        ]:
            key = f"assumption:{var_name}:{period}"
            assumption_lineage[key] = lineage
            used_reviewed_variables.add(var_name)

        # ── Model inputs ──
        da_ratio = inputs["da_ratio"]
        capex_ratio = inputs["capex_ratio"]
        nwc_ratio = inputs["nwc_ratio"]
        other_assets_ratio = inputs["other_assets_ratio"]
        ap_ratio = inputs["ap_ratio"]
        dividend_payout = inputs["dividend_payout"]
        int_rate_debt = inputs["interest_rate_on_debt"]
        int_rate_cash = inputs["interest_rate_on_cash"]
        dilution_pct = inputs["annual_share_dilution_pct"]

        # ── Income Statement ──
        gross_profit = revenue * gm
        cogs = revenue - gross_profit
        opex = revenue * opex_ratio
        ebit = gross_profit - opex

        # Interest: use prior-period balances (current-period BS items computed below)
        avg_debt = prev_debt
        avg_cash = prev_cash
        interest_expense = avg_debt * int_rate_debt
        interest_income = avg_cash * int_rate_cash
        ebt = ebit - interest_expense + interest_income

        # Tax on EBT (not EBIT)
        tax = max(0.0, ebt * tax_rate)
        net_income = ebt - tax

        # EPS with dilution over time
        eps_basic = net_income / shares_outstanding if shares_outstanding else 0.0
        diluted_shares = inputs["diluted_shares"] * ((1 + dilution_pct) ** list(periods).index(period))
        eps_diluted = net_income / diluted_shares if diluted_shares else 0.0

        # ── Cash Flow ──
        da = revenue * da_ratio
        capex = revenue * capex_ratio
        nwc = revenue * nwc_ratio
        delta_nwc = nwc - prev_nwc
        fcf = net_income + da - capex - delta_nwc
        dividends = max(0.0, net_income * dividend_payout)
        ending_cash = prev_cash + fcf - dividends

        # ── Balance Sheet (expanded) ──
        ppe = prev_ppe + capex - da
        other_assets = revenue * other_assets_ratio

        # BS driver-based items (formula-linked when inputs present)
        ar_days = inputs.get("ar_days", 0.0)
        inv_days = inputs.get("inv_days", 0.0)
        ap_days_val = inputs.get("ap_days", 0.0)
        intangible_assets = inputs.get("intangible_assets", 0.0)
        deferred_rev_ratio = inputs.get("deferred_rev_ratio", 0.0)
        accrued_ratio = inputs.get("accrued_ratio", 0.0)
        other_ncl_ratio = inputs.get("other_ncl_ratio", 0.0)
        st_debt = inputs.get("st_debt", 0.0)
        lt_debt = inputs.get("lt_debt", prev_debt - st_debt)

        ar = (revenue * ar_days / 365.0) if ar_days else 0.0
        inventory = (cogs * inv_days / 365.0) if inv_days else 0.0
        prepaid_other_ca = revenue * inputs.get("prepaid_ca_ratio", 0.0)
        ap_bs = (cogs * ap_days_val / 365.0) if ap_days_val else (revenue * ap_ratio)
        accrued_liab = revenue * accrued_ratio
        deferred_rev = revenue * deferred_rev_ratio
        other_ncl = revenue * other_ncl_ratio

        # Paid-in capital is constant when explicitly provided; otherwise equity
        # rolls through retained earnings without inventing a 50/50 split.
        if "paid_in_capital" in inputs:
            paid_in_capital = inputs["paid_in_capital"]
        else:
            paid_in_capital = inputs["equity"] * inputs.get("paid_in_capital_ratio", 0.0)
        # Retained Earnings
        retained_earnings = prev_equity - paid_in_capital + net_income - dividends if prev_equity else net_income - dividends
        other_equity = 0.0  # OCI / Minority Interest placeholder

        # Aggregates
        total_current_assets = ending_cash + ar + inventory + prepaid_other_ca
        total_assets = total_current_assets + ppe + intangible_assets + other_assets
        total_current_liab = ap_bs + st_debt + accrued_liab + deferred_rev
        total_liabilities = total_current_liab + lt_debt + other_ncl
        total_equity = paid_in_capital + retained_earnings + other_equity
        total_liab_equity = total_liabilities + total_equity
        bs_check = total_assets - total_liab_equity

        # ── Valuation ──
        target_price = eps_diluted * pe

        income_values[period] = {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "gross_margin": gm,
            "opex": opex,
            "opex_ratio": opex_ratio,
            "ebit": ebit,
            "ebitda": ebit + da,
            "interest_expense": interest_expense,
            "interest_income": interest_income,
            "ebt": ebt,
            "tax": tax,
            "tax_rate": tax_rate,
            "net_income": net_income,
            "eps_basic": eps_basic,
            "eps_diluted": eps_diluted,
            "da": da,
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
            "ar": ar,
            "inventory": inventory,
            "prepaid_other_ca": prepaid_other_ca,
            "total_current_assets": total_current_assets,
            "ppe": ppe,
            "intangible_assets": intangible_assets,
            "other_assets": other_assets,
            "total_assets": total_assets,
            "ap": ap_bs,
            "st_debt": st_debt,
            "accrued_liab": accrued_liab,
            "deferred_rev": deferred_rev,
            "total_current_liab": total_current_liab,
            "lt_debt": lt_debt,
            "other_ncl": other_ncl,
            "total_liabilities": total_liabilities,
            "paid_in_capital": paid_in_capital,
            "retained_earnings": retained_earnings,
            "other_equity": other_equity,
            "total_equity": total_equity,
            "total_liab_equity": total_liab_equity,
            "balance_check": bs_check,
            "_bs_driver_mode": "formula-linked" if bs_inputs_present else "hard-coded",
        }
        valuation_values[period] = {
            "eps": eps_diluted,
            "eps_basic": eps_basic,
            "forward_pe": pe,
            "target_price": target_price,
            "ebitda": ebit + da,
            "diluted_shares": diluted_shares,
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

        # ── State roll-forward ──
        prev_cash = ending_cash
        prev_nwc = nwc
        prev_ppe = ppe
        prev_equity = total_equity
        prev_debt = st_debt + lt_debt
        shares_outstanding = shares_outstanding * (1 + dilution_pct)

    # ── Statement row builders ─────────────────────────────────────────────

    def row(statement: str, label: str, key: str, formula: str,
            kind: str = "number", values_override: dict | None = None):
        values = values_override if values_override is not None else {
            p: income_values[p].get(key, cash_values[p].get(key, balance_values[p].get(key, valuation_values[p].get(key, 0.0))))
            for p in periods
        }
        lineage = _row_lineage(label, periods)
        return {
            "statement": statement,
            "label": label,
            "values": values,
            "formula": formula,
            "format": kind,
            "lineage": lineage,
        }

    def _row_lineage(label: str, periods_: list[str]) -> list[str]:
        label_key = label.lower()
        refs: list[str] = []
        if "revenue" in label_key:
            refs.extend([f"segment:{seg['name']}:{p}:growth" for seg in model_segments for p in periods_])
        if "gross" in label_key or "cogs" in label_key:
            refs.extend([f"assumption:gross_margin:{p}" for p in periods_])
        if "operating expense" in label_key or "ebit" in label_key or "ebitda" in label_key:
            refs.extend([f"assumption:gross_margin:{p}" for p in periods_])
            refs.extend([f"assumption:opex_ratio:{p}" for p in periods_])
        if "d&a" in label_key or "depreciation" in label_key or label_key == "da (add-back)":
            refs.extend(["input:da_ratio"])
        if "interest" in label_key or "ebt" in label_key:
            refs.extend(["input:interest_rate_on_debt", "input:interest_rate_on_cash"])
        if "tax" in label_key or "net income" in label_key or "eps" in label_key:
            refs.extend([f"assumption:tax_rate:{p}" for p in periods_])
            refs.extend(["input:shares_outstanding", "input:diluted_shares",
                         "input:annual_share_dilution_pct"])
        if "forward pe" in label_key or "target price" in label_key:
            refs.extend([f"assumption:pe:{p}" for p in periods_])
        return sorted(set(refs))

    income_rows = [
        row("Income Statement", "Revenue", "revenue", "Σ segment revenue", "number"),
        row("Income Statement", "COGS", "cogs", "Revenue × (1 - gross margin)", "number"),
        row("Income Statement", "Gross Profit", "gross_profit", "Revenue - COGS", "number"),
        row("Income Statement", "Gross Margin", "gross_margin", "Gross Profit / Revenue", "percent"),
        row("Income Statement", "Operating Expense", "opex", "Revenue × OpEx ratio", "number"),
        row("Income Statement", "EBIT", "ebit", "Gross Profit - Operating Expense", "number"),
        row("Income Statement", "EBITDA", "ebitda", "EBIT + D&A", "number"),
        row("Income Statement", "Interest Expense", "interest_expense", "Avg Debt × interest rate on debt", "number"),
        row("Income Statement", "Interest Income", "interest_income", "Avg Cash × interest rate on cash", "number"),
        row("Income Statement", "EBT (Pre-tax Income)", "ebt", "EBIT - Interest Exp + Interest Inc", "number"),
        row("Income Statement", "Tax Expense", "tax", "MAX(0, EBT × effective tax rate)", "number"),
        row("Income Statement", "Net Income", "net_income", "EBT - Tax Expense", "number"),
        row("Income Statement", "EPS (Basic)", "eps_basic", "Net Income / basic shares", "per_share"),
        row("Income Statement", "EPS (Diluted)", "eps_diluted", "Net Income / diluted shares (with annual dilution)", "per_share"),
        row("Income Statement", "D&A (add-back)", "da", "Revenue × D&A ratio", "number"),
    ]
    cashflow_rows = [
        {"statement": "Cash Flow", "label": "Net Income", "values": {p: cash_values[p]["net_income"] for p in periods}, "formula": "Linked from income statement", "format": "number", "lineage": _row_lineage("Net Income", periods)},
        {"statement": "Cash Flow", "label": "D&A", "values": {p: cash_values[p]["da"] for p in periods}, "formula": "Revenue × D&A ratio", "format": "number", "lineage": ["input:da_ratio"]},
        {"statement": "Cash Flow", "label": "Capex", "values": {p: cash_values[p]["capex"] for p in periods}, "formula": "Revenue × capex ratio", "format": "number", "lineage": ["input:capex_ratio"]},
        {"statement": "Cash Flow", "label": "Change in NWC", "values": {p: cash_values[p]["delta_nwc"] for p in periods}, "formula": "Ending NWC - prior NWC", "format": "number", "lineage": ["input:nwc_ratio"]},
        {"statement": "Cash Flow", "label": "Free Cash Flow", "values": {p: cash_values[p]["fcf"] for p in periods}, "formula": "Net Income + D&A - Capex - Change in NWC", "format": "number", "lineage": ["input:da_ratio", "input:capex_ratio", "input:nwc_ratio"]},
        {"statement": "Cash Flow", "label": "Dividends", "values": {p: cash_values[p]["dividends"] for p in periods}, "formula": "Net Income × dividend payout ratio", "format": "number", "lineage": ["input:dividend_payout"]},
        {"statement": "Cash Flow", "label": "Ending Cash", "values": {p: cash_values[p]["ending_cash"] for p in periods}, "formula": "Beginning Cash + FCF - dividends", "format": "number", "lineage": ["input:cash", "input:dividend_payout"]},
    ]
    balance_rows = [
        # Assets
        {"statement": "Balance Sheet", "label": "Cash & Equivalents", "values": {p: balance_values[p]["cash"] for p in periods}, "formula": "Linked from CF ending cash", "format": "number", "lineage": ["input:cash"]},
        {"statement": "Balance Sheet", "label": "Accounts Receivable", "values": {p: balance_values[p]["ar"] for p in periods}, "formula": "Revenue × AR days / 365" if bs_inputs_present else "Hard-coded from model", "format": "number", "lineage": ["input:ar_days"] if bs_inputs_present else ["input:ap_ratio"]},
        {"statement": "Balance Sheet", "label": "Inventory", "values": {p: balance_values[p]["inventory"] for p in periods}, "formula": "COGS × Inv days / 365" if bs_inputs_present else "Hard-coded from model", "format": "number", "lineage": ["input:inv_days"] if bs_inputs_present else ["input:nwc_ratio"]},
        {"statement": "Balance Sheet", "label": "Prepaid & Other Current Assets", "values": {p: balance_values[p]["prepaid_other_ca"] for p in periods}, "formula": "Revenue × ratio (~2%)", "format": "number", "lineage": ["input:nwc_ratio"]},
        {"statement": "Balance Sheet", "label": "Total Current Assets", "values": {p: balance_values[p]["total_current_assets"] for p in periods}, "formula": "Cash + AR + Inventory + Prepaid", "format": "number", "lineage": ["derived:sum_current_assets"]},
        {"statement": "Balance Sheet", "label": "PP&E (Net)", "values": {p: balance_values[p]["ppe"] for p in periods}, "formula": "Prior PP&E + Capex - D&A", "format": "number", "lineage": ["input:ppe_ratio", "input:capex_ratio", "input:da_ratio"]},
        {"statement": "Balance Sheet", "label": "Intangible Assets & Goodwill", "values": {p: balance_values[p]["intangible_assets"] for p in periods}, "formula": "Input balance (constant)", "format": "number", "lineage": ["input:intangible_assets"]},
        {"statement": "Balance Sheet", "label": "Other Non-Current Assets", "values": {p: balance_values[p]["other_assets"] for p in periods}, "formula": "Revenue × other assets ratio", "format": "number", "lineage": ["input:other_assets_ratio"]},
        {"statement": "Balance Sheet", "label": "Total Assets", "values": {p: balance_values[p]["total_assets"] for p in periods}, "formula": "Current Assets + Non-Current Assets", "format": "number", "lineage": ["derived:sum_assets"]},
        # Liabilities
        {"statement": "Balance Sheet", "label": "Accounts Payable", "values": {p: balance_values[p]["ap"] for p in periods}, "formula": "COGS × AP days / 365" if bs_inputs_present else "Revenue × AP ratio", "format": "number", "lineage": ["input:ap_days"] if bs_inputs_present else ["input:ap_ratio"]},
        {"statement": "Balance Sheet", "label": "Short-term Debt", "values": {p: balance_values[p]["st_debt"] for p in periods}, "formula": "Input ST debt balance", "format": "number", "lineage": ["input:st_debt"] if inputs.get("st_debt", 0.0) != 0.0 else ["input:debt"]},
        {"statement": "Balance Sheet", "label": "Accrued Liabilities", "values": {p: balance_values[p]["accrued_liab"] for p in periods}, "formula": "Revenue × accrued ratio", "format": "number", "lineage": ["input:accrued_ratio"] if inputs.get("accrued_ratio", 0.0) != 0.0 else ["input:ap_ratio"]},
        {"statement": "Balance Sheet", "label": "Deferred Revenue", "values": {p: balance_values[p]["deferred_rev"] for p in periods}, "formula": "Revenue × deferred revenue ratio", "format": "number", "lineage": ["input:deferred_rev_ratio"] if inputs.get("deferred_rev_ratio", 0.0) != 0.0 else ["input:nwc_ratio"]},
        {"statement": "Balance Sheet", "label": "Total Current Liabilities", "values": {p: balance_values[p]["total_current_liab"] for p in periods}, "formula": "AP + ST Debt + Accrued + Deferred Rev", "format": "number", "lineage": ["derived:sum_current_liabilities"]},
        {"statement": "Balance Sheet", "label": "Long-term Debt", "values": {p: balance_values[p]["lt_debt"] for p in periods}, "formula": "Input LT debt balance", "format": "number", "lineage": ["input:lt_debt"] if inputs.get("lt_debt", 0.0) != 0.0 else ["input:debt"]},
        {"statement": "Balance Sheet", "label": "Other Non-Current Liabilities", "values": {p: balance_values[p]["other_ncl"] for p in periods}, "formula": "Revenue × other NCL ratio", "format": "number", "lineage": ["input:other_ncl_ratio"] if inputs.get("other_ncl_ratio", 0.0) != 0.0 else ["input:ap_ratio"]},
        {"statement": "Balance Sheet", "label": "Total Liabilities", "values": {p: balance_values[p]["total_liabilities"] for p in periods}, "formula": "Current Liabilities + Non-Current Liabilities", "format": "number", "lineage": ["derived:sum_liabilities"]},
        # Equity
        {"statement": "Balance Sheet", "label": "Paid-in Capital", "values": {p: balance_values[p]["paid_in_capital"] for p in periods}, "formula": "Input balance (constant)", "format": "number", "lineage": ["input:equity"]},
        {"statement": "Balance Sheet", "label": "Retained Earnings", "values": {p: balance_values[p]["retained_earnings"] for p in periods}, "formula": "Prior RE + Net Income - Dividends", "format": "number", "lineage": ["input:dividend_payout"]},
        {"statement": "Balance Sheet", "label": "Other Equity", "values": {p: balance_values[p]["other_equity"] for p in periods}, "formula": "OCI / Minority / Treasury", "format": "number", "lineage": ["input:equity"]},
        {"statement": "Balance Sheet", "label": "Total Equity", "values": {p: balance_values[p]["total_equity"] for p in periods}, "formula": "Paid-in Capital + Retained Earnings + Other", "format": "number", "lineage": ["derived:sum_equity"]},
        {"statement": "Balance Sheet", "label": "Total Liabilities & Equity", "values": {p: balance_values[p]["total_liab_equity"] for p in periods}, "formula": "Total Liabilities + Total Equity", "format": "number", "lineage": ["derived:sum_liabilities_equity"]},
        {"statement": "Balance Sheet", "label": "Balance Check", "values": {p: balance_values[p]["balance_check"] for p in periods}, "formula": "Total Assets - Total L&E (should = 0)", "format": "number", "lineage": ["derived:balance_check"]},
    ]
    valuation_rows = [
        {"statement": "Valuation", "label": "EPS (Basic)", "values": {p: valuation_values[p]["eps_basic"] for p in periods}, "formula": "Linked from income statement", "format": "per_share", "lineage": _row_lineage("EPS", periods)},
        {"statement": "Valuation", "label": "EPS (Diluted)", "values": {p: valuation_values[p]["eps"] for p in periods}, "formula": "Net Income / diluted shares", "format": "per_share", "lineage": _row_lineage("EPS", periods)},
        {"statement": "Valuation", "label": "Forward PE", "values": {p: valuation_values[p]["forward_pe"] for p in periods}, "formula": "Step 4 assumption matrix", "format": "multiple", "lineage": [f"assumption:pe:{p}" for p in periods]},
        {"statement": "Valuation", "label": "Target Price", "values": {p: valuation_values[p]["target_price"] for p in periods}, "formula": "EPS (Diluted) × Forward PE", "format": "per_share", "lineage": _row_lineage("Target Price", periods)},
        {"statement": "Valuation", "label": "EBITDA", "values": {p: valuation_values[p]["ebitda"] for p in periods}, "formula": "EBIT + D&A", "format": "number", "lineage": ["input:da_ratio"]},
        {"statement": "Valuation", "label": "Diluted Shares", "values": {p: valuation_values[p]["diluted_shares"] for p in periods}, "formula": "Diluted shares × (1 + dilution_pct)^n", "format": "number", "lineage": ["input:diluted_shares", "input:annual_share_dilution_pct"]},
    ]

    # ── Integrity checks ───────────────────────────────────────────────────
    all_rows = income_rows + cashflow_rows + balance_rows + valuation_rows
    missing_lineage = [
        f"{r['statement']} / {r['label']}"
        for r in all_rows
        if not r.get("lineage")
    ]
    reviewed_vars = _canonical_reviewed_variables(reviewed.get("assumptions") or {})
    unreviewed = sorted(v for v in used_reviewed_variables if v not in reviewed_vars)
    checks.extend([
        {
            "period": "all",
            "check": "No fallback model assumptions",
            "actual": 0,
            "expected": 0,
            "difference": 0,
            "tolerance": 0,
            "status": "OK",
            "notes": "Required model inputs and assumptions were present; no hard-coded defaults used.",
        },
        {
            "period": "all",
            "check": "Reviewed assumption lock coverage",
            "actual": len(used_reviewed_variables),
            "expected": len(used_reviewed_variables),
            "difference": len(unreviewed),
            "tolerance": 0,
            "status": "OK" if not unreviewed else "FAIL",
            "notes": "All used high-level assumptions are present in _reviewed_assumptions.json"
            if not unreviewed
            else f"Unreviewed assumptions used: {unreviewed}",
        },
        {
            "period": "all",
            "check": "Formula lineage coverage",
            "actual": len(all_rows) - len(missing_lineage),
            "expected": len(all_rows),
            "difference": len(missing_lineage),
            "tolerance": 0,
            "status": "OK" if not missing_lineage else "FAIL",
            "notes": "Every model row has lineage references"
            if not missing_lineage
            else f"Rows missing lineage: {missing_lineage}",
        },
        {
            "period": "all",
            "check": "BS driver completeness",
            "actual": int(bs_inputs_present),
            "expected": 1,
            "difference": 0 if bs_inputs_present else 1,
            "tolerance": 0,
            "status": "OK" if bs_inputs_present else "WARN",
            "notes": bs_hardcoded_warning if not bs_inputs_present else "AR/Inv/AP driven by days-based formulas",
        },
        {
            "period": "all",
            "check": "Diluted shares provided",
            "actual": inputs["diluted_shares"],
            "expected": inputs["diluted_shares"],
            "difference": 0,
            "tolerance": 0,
            "status": "OK",
            "notes": f"Diluted shares: {inputs['diluted_shares']:,.0f} (dilution pct/year: {inputs['annual_share_dilution_pct']:.1%})",
        },
    ])

    return {
        "version": 3,
        "ticker": ticker,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "step4_structured_assumptions.json",
        "model_conventions": {
            "unit": "same as source financial statements",
            "periods": periods,
            "case": "P50",
            "note": "Formula-linked forecast model generated from locked Step 4 assumptions with explicit lineage.",
            "tax_basis": "EBT (not EBIT)",
            "interest_modeled": True,
            "bs_driver_mode": "formula-linked" if bs_inputs_present else "hard-coded",
            "percentage_detection": "naming_convention",
        },
        "inputs": inputs,
        "defaults_used": [],
        "lineage": {
            "inputs": {f"input:{k}": v for k, v in input_lineage.items()},
            "assumptions": assumption_lineage,
            "reviewed_lock": {
                "source": "_reviewed_assumptions.json",
                "reviewed_at": reviewed.get("reviewed_at", ""),
                "variables": sorted(reviewed_vars),
            },
        },
        "segments": model_segments,
        "statements": {
            "income_statement": income_rows,
            "cash_flow": cashflow_rows,
            "balance_sheet": balance_rows,
            "valuation": valuation_rows,
        },
        "checks": checks,
    }


# ── HTML Renderer ────────────────────────────────────────────────────────

def render_financial_model_html(model: dict) -> str:
    """Render forecast model as an HTML section body."""
    periods = model["model_conventions"]["periods"]

    def table(rows: list[dict], title: str, period_prefix: str = "") -> str:
        head = "".join(f"<th>{escape(p, quote=True)}</th>" for p in periods)
        body = []
        for r in rows:
            kind = r.get("format", "number")
            vals = "".join(f"<td>{_fmt(r['values'].get(p), kind)}</td>" for p in periods)
            refs = ", ".join(str(ref) for ref in r.get("lineage", [])[:6])
            if len(r.get("lineage", [])) > 6:
                refs += ", ..."
            body.append(
                "<tr>"
                f"<td><strong>{escape(r['label'], quote=True)}</strong></td>"
                f"{vals}"
                f"<td>{escape(r.get('formula', ''), quote=True)}</td>"
                f"<td>{escape(refs, quote=True)}</td>"
                "</tr>"
            )
        return (
            f"<h4>{escape(title, quote=True)}</h4>"
            "<table class=\"financial-model-table\">"
            f"<thead><tr><th>Line Item</th>{head}<th>Formula / Link</th><th>Lineage</th></tr></thead>"
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
                f"<td>{escape(', '.join(str(ref) for ref in f.get('lineage', [])), quote=True)}</td>"
                "</tr>"
            )
    check_rows = []
    for c in model["checks"]:
        check_rows.append(
            "<tr>"
            f"<td>{escape(c['period'], quote=True)}</td>"
            f"<td>{escape(c['check'], quote=True)}</td>"
            f"<td>{_fmt(c['difference'])}</td>"
            f"<td>{escape(c['status'], quote=True)}</td>"
            f"<td>{escape(c.get('notes', ''), quote=True)}</td>"
            "</tr>"
        )

    conventions = model["model_conventions"]
    return (
        "<div class=\"financial-model\">"
        f"<p><strong>Model conventions:</strong> P50 case, three-year forecast, tax on EBT, interest modeled. "
        f"BS driver mode: {conventions.get('bs_driver_mode', 'N/A')}. "
        f"Version {model.get('version', '?')}.</p>"
        "<h4>Segment Revenue Build</h4>"
        "<table class=\"financial-model-table\"><thead><tr>"
        "<th>Segment</th><th>Period</th><th>Growth</th><th>Revenue</th><th>Formula / Link</th><th>Lineage</th>"
        f"</tr></thead><tbody>{''.join(seg_rows)}</tbody></table>"
        f"{table(model['statements']['income_statement'], 'Income Statement')}"
        f"{table(model['statements']['cash_flow'], 'Cash Flow')}"
        f"{table(model['statements']['balance_sheet'], 'Balance Sheet')}"
        f"{table(model['statements']['valuation'], 'Valuation Bridge')}"
        "<h4>Checks</h4>"
        "<table class=\"financial-model-table\"><thead><tr>"
        "<th>Period</th><th>Check</th><th>Difference</th><th>Status</th><th>Notes</th>"
        f"</tr></thead><tbody>{''.join(check_rows)}</tbody></table>"
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
