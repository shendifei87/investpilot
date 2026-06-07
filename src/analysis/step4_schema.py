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
        ],
        "note": "diluted_shares is required (not defaulted). ar_days/inv_days/ap_days drive BS formula-linked items; if absent, BS items are hard-coded with a warning.",
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
