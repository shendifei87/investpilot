import json
import tempfile
from pathlib import Path

import pytest

from src.analysis.financial_model import (
    build_financial_model,
    generate_financial_model_artifacts,
    render_financial_model_html,
)
from src.analysis.step4_schema import save_structured_assumptions
from src.report.generator import generate_report_html


def _structured():
    return {
        "forecast_periods": ["2027E", "2028E", "2029E"],
        "segment_revenues": [
            {"name": "Cloud", "base_revenue": 100, "p50_growth": 0.20, "p50_revenue": 120},
            {"name": "Ads", "base_revenue": 200, "p50_growth": 0.10, "p50_revenue": 220},
        ],
        "growth_drivers": [
            {"segment": "Cloud", "drivers": [
                {"name": "volume", "contribution_pct": 0.15, "evidence_ids": ["DATA:usage"]},
                {"name": "price", "contribution_pct": 0.05, "evidence_ids": ["DATA:pricing"]},
            ]},
            {"segment": "Ads", "drivers": [
                {"name": "impressions", "contribution_pct": 0.06, "evidence_ids": ["DATA:traffic"]},
                {"name": "load", "contribution_pct": 0.04, "evidence_ids": ["DATA:adload"]},
            ]},
        ],
        "assumption_matrix": [
            {"variable": "rev_growth", "year": "2028E", "p10": 0.05, "p50": 0.12, "p90": 0.20, "sensitivity": "high", "evidence_ids": ["DATA:usage"]},
            {"variable": "rev_growth", "year": "2029E", "p10": 0.04, "p50": 0.10, "p90": 0.18, "sensitivity": "high", "evidence_ids": ["DATA:usage"]},
            {"variable": "gross_margin", "year": "2027E", "p10": 0.30, "p50": 0.42, "p90": 0.50, "sensitivity": "high", "evidence_ids": ["DATA:cost"]},
            {"variable": "opex_ratio", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "evidence_ids": ["DATA:opex"]},
            {"variable": "tax_rate", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "evidence_ids": ["DATA:tax"]},
            {"variable": "pe", "year": "2027E", "p10": 15, "p50": 24, "p90": 35, "sensitivity": "high", "evidence_ids": ["CALC:valuation"]},
        ],
        "financial_model_inputs": {
            "shares_outstanding": 10,
            "cash": 50,
            "debt": 20,
            "equity": 150,
            "nwc_ratio": 0.08,
            "ppe_ratio": 0.25,
        },
        "bridge_analysis": {"base_total": 300, "delta": 40, "p50_total": 340},
        "q1_constraint": {"feasibility": "REASONABLE"},
        "margin_derivation": {
            "method": "cost_buildup",
            "cost_items": [{"name": "COGS", "growth_pct": 0.08}],
            "p50_margin": 0.42,
        },
        "historical_valuation": {"pe_min": 15, "pe_median": 22, "pe_max": 35},
        "peer_comparison": {
            "metric": "pe",
            "basis": "T+1",
            "n_peers": 3,
            "peers": [
                {"name": "A", "value": 20, "source": "calculated"},
                {"name": "B", "value": 22, "source": "calculated"},
                {"name": "C", "value": 24, "source": "calculated"},
            ],
        },
        "reverse_dcf": {"implied_growth": 0.10},
        "dcf_cross_validation": {"deviation_pct": 0.05},
        "contrarian_checks": [
            {"variable": "rev_growth", "p50": 0.12, "p10": 0.05, "evidence_to_flip": "demand miss"},
            {"variable": "gross_margin", "p50": 0.42, "p10": 0.30, "evidence_to_flip": "cost spike"},
            {"variable": "pe", "p50": 24, "p10": 15, "evidence_to_flip": "sector derating"},
        ],
        "valuation_source": {"pe_calculated": True, "calc_inputs_disclosed": True},
        "assumption_consistency": {
            "post_review_changes": False,
            "pe_moat_aligned": True,
            "revenue_segment_aligned": True,
        },
    }


def _write_validation_sidecars(ws: Path):
    (ws / "step4_quantitative_model.md").write_text("# Step 4\n", encoding="utf-8")
    (ws / "calculated_valuation.json").write_text(json.dumps({
        "source": "calculated",
        "pe_trailing": {"pe": 20.0, "valid": True},
        "pb": {"pb": 3.0, "valid": True},
        "ps": {"ps": 5.0, "valid": True},
    }), encoding="utf-8")
    (ws / "_reviewed_assumptions.json").write_text(json.dumps({
        "reviewed_at": "2026-01-01",
        "assumptions": {
            "rev_growth": {"p10": 0.05, "p50": 0.12, "p90": 0.20},
            "gross_margin": {"p10": 0.30, "p50": 0.42, "p90": 0.50},
            "opex_ratio": {"p10": 0.15, "p50": 0.20, "p90": 0.25},
            "tax_rate": {"p10": 0.15, "p50": 0.20, "p90": 0.25},
            "pe": {"p10": 15, "p50": 24, "p90": 35},
        },
    }), encoding="utf-8")


class TestFinancialModel:
    def test_builds_formula_linked_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            model = build_financial_model(ws, ticker="TEST")
            assert model["ticker"] == "TEST"
            assert "income_statement" in model["statements"]
            assert "cash_flow" in model["statements"]
            assert "balance_sheet" in model["statements"]
            assert "valuation" in model["statements"]
            valuation_formulas = [r["formula"] for r in model["statements"]["valuation"]]
            assert "EPS × Forward PE" in valuation_formulas

    def test_generates_json_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            artifacts = generate_financial_model_artifacts(ws, ticker="TEST")
            assert Path(artifacts["json_path"]).exists()
            assert Path(artifacts["html_path"]).exists()
            html = Path(artifacts["html_path"]).read_text(encoding="utf-8")
            assert "Income Statement" in html
            assert "Balance Sheet" in html

    def test_render_contains_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            model = build_financial_model(ws)
            html = render_financial_model_html(model)
            assert "Segment Revenue Build" in html
            assert "Checks" in html

    def test_report_embeds_forecast_model_when_structured_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_validation_sidecars(ws)
            (ws / "step1_business_analysis.md").write_text("# Step 1: TEST\n", encoding="utf-8")
            report = generate_report_html(ws, ticker="TEST")
            html = Path(report).read_text(encoding="utf-8")
            assert "Forecast Model" in html
            assert (ws / "forecast_model.json").exists()
            assert (ws / "forecast_model.html").exists()


class TestFinancialModelErrors:
    """Error path tests for the financial forecast model."""

    def test_build_fails_without_structured_assumptions(self):
        """build_financial_model raises FileNotFoundError when assumptions file is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            with pytest.raises(FileNotFoundError, match="step4_structured_assumptions"):
                build_financial_model(ws)

    def test_build_with_missing_segments_raises(self):
        """build_financial_model raises ValueError when segment_revenues is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            data["segment_revenues"] = []
            save_structured_assumptions(ws, data)
            with pytest.raises(ValueError, match="No segment_revenues"):
                build_financial_model(ws)

    def test_model_uses_defaults_when_inputs_missing(self):
        """Model falls back to defaults and records them in defaults_used."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            # Remove financial_model_inputs entirely
            del data["financial_model_inputs"]
            save_structured_assumptions(ws, data)

            model = build_financial_model(ws, ticker="DEFTEST")
            # Model should still build (using defaults)
            assert model["ticker"] == "DEFTEST"
            # defaults_used should list the fields that fell back
            assert "defaults_used" in model
            assert len(model["defaults_used"]) > 0
            # shares_outstanding always gets a fallback of 1.0
            assert "shares_outstanding" in model["defaults_used"]
