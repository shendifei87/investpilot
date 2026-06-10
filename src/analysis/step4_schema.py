"""Structured Step 4 assumption artifact helpers.

The markdown report is useful for humans, but Monte Carlo assumptions need a
typed artifact that validators can inspect.  This module defines the expected
shape and gives agents a small helper for saving it consistently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.analysis._base import resolve_workspace_path
from src.storage import AtomicJSON

STEP4_STRUCTURED_FILENAME = "step4_structured_assumptions.json"


STEP4_SCHEMA_DESCRIPTION = {
    "version": 2,
    "required_top_level_keys": [
        "segment_revenues",
        "growth_drivers",
        "bridge_analysis",
        "q1_constraint",
        "margin_derivation",
        "assumption_matrix",
        "contrarian_checks",
        "peer_comparison",
        "historical_valuation",
        "valuation_source",
        "financial_model_inputs",
        "reverse_dcf",
        "dcf_cross_validation",
        "assumption_consistency",
    ],
    "segment_revenues": {
        "required": ["name", "base_revenue", "p50_growth", "p50_revenue"],
        "optional_percentiles": ["p10_growth", "p30_growth", "p70_growth", "p90_growth"],
    },
    "growth_drivers": {
        "required": ["segment", "drivers"],
        "driver_required": ["name", "contribution_pct", "evidence_ids", "derivation"],
        "driver_encouraged": ["base_value", "unit", "growth_T+1", "growth_T+2", "growth_T+3"],
        "minimum_drivers_per_segment": 2,
        "maximum_drivers_per_segment": 4,
        "note": "Drivers MUST include explicit base_value + per-period growth_* for formula-linked Excel. contribution_pct-only mode is blocked in Step 5.",
    },
    "assumption_matrix": {
        "required": [
            "variable",
            "p10",
            "p50",
            "p90",
            "sensitivity",
            "confidence",
            "evidence_ids",
            "derivation",
            "what_would_change_this",
        ],
        "recommended": ["p30", "p70", "segment", "year"],
        "percentile_format_note": "All growth/margin/ratio values must be in decimal form (0.20 = 20%). Values > 1.0 for percentage-type variables are rejected at validation.",
    },
    "financial_model_inputs": {
        "required": [
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
        ],
        "recommended": [
            "ar_days",
            "inv_days",
            "ap_days",
            "intangible_assets",
            "deferred_rev_ratio",
            "accrued_ratio",
            "other_ncl_ratio",
            "st_debt",
            "lt_debt",
            "fx_rate",
        ],
        "note": "diluted_shares is required (not defaulted). ar_days/inv_days/ap_days drive BS formula-linked items; if absent, BS items are hard-coded with a warning. fx_rate is required for non-A-share stocks (HK/US) — converts RMB financials to trading currency.",
    },
}


def generate_step4_template() -> dict[str, Any]:
    """Generate a minimal valid Step 4 structured assumptions template.

    Agents can call this to get a correctly-formatted skeleton, then fill in
    the actual values.  All required fields are present with placeholder values.
    Percentage values are in decimal form (0.20 = 20%).
    """
    return {
        "schema_version": 2,
        "segment_revenues": [
            {
                "name": "SegmentName",
                "base_revenue": 100.0,
                "p50_growth": 0.20,
                "p50_revenue": 120.0,
                "p10_growth": 0.10,
                "p30_growth": 0.15,
                "p70_growth": 0.25,
                "p90_growth": 0.35,
                "currency": "RMB",
                "unit": "B",
            },
        ],
        "growth_drivers": [
            {
                "segment": "SegmentName",
                "drivers": [
                    {
                        "name": "driver_1",
                        "contribution_pct": 0.10,
                        "base_value": 100.0,
                        "unit": "units",
                        "derivation": "Explain how this driver is quantified with evidence",
                        "evidence_ids": ["E001"],
                        "growth_T+1": 0.10,
                        "growth_T+2": 0.08,
                        "growth_T+3": 0.06,
                    },
                    {
                        "name": "driver_2",
                        "contribution_pct": 0.10,
                        "base_value": 50.0,
                        "unit": "RMB",
                        "derivation": "Explain how this driver is quantified with evidence",
                        "evidence_ids": ["E002"],
                        "growth_T+1": 0.10,
                        "growth_T+2": 0.08,
                        "growth_T+3": 0.06,
                    },
                ],
            },
        ],
        "assumption_matrix": [
            {
                "variable": "total_revenue_growth",
                "year": "2026E",
                "p10": 0.10, "p30": 0.15, "p50": 0.20, "p70": 0.28, "p90": 0.35,
                "sensitivity": "high", "confidence": "medium",
                "evidence_ids": ["E001"],
                "derivation": "Weighted average of segment growth rates",
                "what_would_change_this": "Q2 data below expectations",
            },
            {
                "variable": "gross_margin",
                "year": "2026E",
                "p10": 0.65, "p30": 0.68, "p50": 0.70, "p70": 0.72, "p90": 0.74,
                "sensitivity": "high", "confidence": "medium",
                "evidence_ids": ["E002"],
                "derivation": "Base margin adjusted for cost factors",
                "what_would_change_this": "Raw material costs >+5%",
            },
            {
                "variable": "opex_ratio",
                "year": "2026E",
                "p10": 0.30, "p30": 0.29, "p50": 0.28, "p70": 0.27, "p90": 0.26,
                "sensitivity": "medium", "confidence": "medium",
                "evidence_ids": ["E002"],
                "derivation": "Historical ratio minus operating leverage",
                "what_would_change_this": "Rapid expansion pushes costs higher",
            },
            {
                "variable": "tax_rate",
                "year": "2026E",
                "p10": 0.22, "p30": 0.20, "p50": 0.18, "p70": 0.16, "p90": 0.15,
                "sensitivity": "low", "confidence": "high",
                "evidence_ids": ["E002"],
                "derivation": "Blended effective tax rate",
                "what_would_change_this": "Tax policy changes",
            },
            {
                "variable": "pe_forward",
                "year": "2026E",
                "p10": 12.0, "p30": 15.0, "p50": 18.0, "p70": 22.0, "p90": 25.0,
                "sensitivity": "high", "confidence": "low",
                "evidence_ids": ["Step 2 Comps"],
                "derivation": "Peer median + moat premium. PE multiples are NOT percentage values.",
                "what_would_change_this": "Moat downgrade",
            },
        ],
        "bridge_analysis": {
            "t1_2026E": {"revenue_growth": 0.20, "gross_margin": 0.70, "opex_ratio": 0.28, "tax_rate": 0.18, "eps": 10.0, "pe_forward": 18.0, "target_price_rmb": 180},
            "t2_2027E": {"revenue_growth": 0.17, "gross_margin": 0.695, "opex_ratio": 0.275, "tax_rate": 0.18, "eps": 12.0, "pe_forward": 16.0, "target_price_rmb": 192},
            "t3_2028E": {"revenue_growth": 0.14, "gross_margin": 0.69, "opex_ratio": 0.27, "tax_rate": 0.18, "eps": 14.0, "pe_forward": 15.0, "target_price_rmb": 210},
        },
        "q1_constraint": {
            "q1_2026_growth": 0.50,
            "q1_weight": 0.20,
            "implied_q2q4_growth": 0.15,
            "feasibility": "Explain why Q2-Q4 growth is achievable",
            "evidence_ids": ["E001"],
        },
        "margin_derivation": {
            "base_gm_2025": 0.70,
            "method": "cost_structure_bottom_up",
            "cost_items": [
                {"factor": "raw_material_cost", "impact": -0.01},
                {"factor": "mix_shift", "impact": 0.005},
            ],
            "gm_2026e": 0.695,
        },
        "historical_valuation": {
            "pe_min": 15.0, "pe_median": 20.0, "pe_max": 30.0,
            "data_points": [
                {"date": "YYYY-MM-DD", "price_rmb": 100.0, "eps": 5.0, "pe": 20.0, "source": "calculated"},
            ],
        },
        "peer_comparison": {
            "n_peers": 3,
            "metric": "pe",
            "basis": "TTM",
            "peers": [
                {"name": "Peer1 (TICKER)", "metric": "pe", "basis": "TTM", "value": 15.0, "source": "calculated", "gm": 0.40, "nm": 0.10, "rev_growth": 0.15},
                {"name": "Peer2 (TICKER)", "metric": "pe", "basis": "TTM", "value": 18.0, "source": "calculated", "gm": 0.45, "nm": 0.12, "rev_growth": 0.20},
                {"name": "Target (TICKER)", "metric": "pe", "basis": "TTM", "value": 20.0, "source": "calculated", "gm": 0.60, "nm": 0.20, "rev_growth": 0.30},
            ],
            "peer_median_pe": 18.0,
            "premium_justification": "Higher margins and growth justify premium",
        },
        "reverse_dcf": {
            "current_price_rmb": 100.0,
            "implied_growth": "~15% 5-year CAGR",
            "assumptions": "WACC 10%, terminal growth 3%",
            "interpretation": "Market pricing lower growth than our estimate",
        },
        "dcf_cross_validation": {
            "status": "pending_step5",
            "deviation_pct": 0.10,
            "note": "DCF cross-validation to be performed in Step 5",
        },
        "contrarian_checks": [
            {"variable": "total_revenue_growth", "trigger": "Q2 growth <10%", "impact": "P50 → P10"},
            {"variable": "gross_margin", "trigger": "H1 GM <65%", "impact": "P50 → P10"},
            {"variable": "pe_forward", "trigger": "Moat downgrade", "impact": "P50 → P10"},
        ],
        "financial_model_inputs": {
            "shares_outstanding": 1000000000,
            "diluted_shares": 1020000000,
            "cash": 5000000000,
            "debt": 1000000000,
            "equity": 20000000000,
            "nwc_ratio": 0.05,
            "ppe_ratio": 0.08,
            "other_assets_ratio": 0.04,
            "ap_ratio": 0.05,
            "dividend_payout": 0.30,
            "da_ratio": 0.02,
            "capex_ratio": 0.04,
            "interest_rate_on_debt": 0.05,
            "interest_rate_on_cash": 0.02,
            "annual_share_dilution_pct": 0.01,
            "fx_rate": None,
        },
        "valuation_source": {
            "pe_calculated": True,
            "pb_calculated": True,
            "ps_calculated": True,
            "method": "All ratios self-calculated from raw financial data",
            "disclaimer": "No news/broker pre-computed ratios used as conclusions",
        },
        "assumption_consistency": {
            "q1_vs_full_year": "Check Q1 vs full year consistency",
            "segment_vs_total": "Verify segment sum matches total",
            "margin_vs_growth": "Verify margin assumptions align with growth",
            "pe_vs_moat": "Verify PE aligns with moat rating",
        },
    }


def save_structured_assumptions(workspace_dir: str | Path, data: dict[str, Any]) -> Path:
    """Save Step 4 structured assumptions into the workspace.

    The helper stamps a schema version but otherwise does not mutate the model
    assumptions. Validation is handled by ``validate_step4``.
    """
    ws = resolve_workspace_path(workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": STEP4_SCHEMA_DESCRIPTION["version"], **data}
    store = AtomicJSON(ws)
    return store.save(STEP4_STRUCTURED_FILENAME, payload)


def load_structured_assumptions(workspace_dir: str | Path) -> dict[str, Any]:
    """Load Step 4 structured assumptions from a workspace."""
    ws = resolve_workspace_path(workspace_dir)
    store = AtomicJSON(ws)
    data = store.load(STEP4_STRUCTURED_FILENAME, default={})
    return data if isinstance(data, dict) else {}
