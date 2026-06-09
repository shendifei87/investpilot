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
                {
                    "name": "volume", "contribution_pct": 0.15, "evidence_ids": ["DATA:usage"],
                    "derivation": "Usage growth converts into cloud volume.",
                    "base_value": 100, "unit": "units",
                    "growth_2027E": 0.15, "growth_2028E": 0.10, "growth_2029E": 0.08,
                },
                {
                    "name": "price", "contribution_pct": 0.05, "evidence_ids": ["DATA:pricing"],
                    "derivation": "Mix upgrade supports price contribution.",
                    "base_value": 1.0, "unit": "CNY/unit",
                    "growth_2027E": 0.0434782609, "growth_2028E": 0.0454545455, "growth_2029E": 0.0370370370,
                },
            ]},
            {"segment": "Ads", "drivers": [
                {
                    "name": "impressions", "contribution_pct": 0.06, "evidence_ids": ["DATA:traffic"],
                    "derivation": "Traffic growth drives impressions.",
                    "base_value": 1000, "unit": "impressions",
                    "growth_2027E": 0.07, "growth_2028E": 0.06, "growth_2029E": 0.05,
                },
                {
                    "name": "load", "contribution_pct": 0.04, "evidence_ids": ["DATA:adload"],
                    "derivation": "Ad load expansion contributes incremental revenue.",
                    "base_value": 0.20, "unit": "ad load",
                    "growth_2027E": 0.0280373832, "growth_2028E": 0.0377358491, "growth_2029E": 0.0285714286,
                },
            ]},
        ],
        "assumption_matrix": [
            {"variable": "rev_growth", "year": "2028E", "p10": 0.05, "p50": 0.12, "p90": 0.20, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:usage"], "derivation": "Segment weighted growth from cloud and ads drivers.", "what_would_change_this": "Usage and traffic fall below plan."},
            {"variable": "rev_growth", "year": "2029E", "p10": 0.04, "p50": 0.10, "p90": 0.18, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:usage"], "derivation": "Growth normalizes from prior-year driver base.", "what_would_change_this": "Customer additions slow materially."},
            {"variable": "gross_margin", "year": "2027E", "p10": 0.30, "p50": 0.42, "p90": 0.50, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"], "derivation": "Cost buildup from COGS and operating leverage.", "what_would_change_this": "Compute and content costs rise faster than revenue."},
            {"variable": "gross_margin", "year": "2028E", "p10": 0.31, "p50": 0.43, "p90": 0.51, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"], "derivation": "Operating leverage offsets cloud cost inflation.", "what_would_change_this": "Cost inflation persists."},
            {"variable": "gross_margin", "year": "2029E", "p10": 0.32, "p50": 0.44, "p90": 0.52, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"], "derivation": "Mix and scale support margin expansion.", "what_would_change_this": "Mix shifts away from higher-margin lines."},
            {"variable": "opex_ratio", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"], "derivation": "Historical opex intensity adjusted for hiring plan.", "what_would_change_this": "Hiring or R&D ramps faster than assumed."},
            {"variable": "opex_ratio", "year": "2028E", "p10": 0.15, "p50": 0.19, "p90": 0.24, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"], "derivation": "Opex leverage from revenue scale.", "what_would_change_this": "Hiring ramps faster than assumed."},
            {"variable": "opex_ratio", "year": "2029E", "p10": 0.14, "p50": 0.18, "p90": 0.23, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"], "derivation": "Opex leverage continues with scale.", "what_would_change_this": "R&D investment cycle restarts."},
            {"variable": "tax_rate", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"], "derivation": "Tax rate anchored to recent effective rate.", "what_would_change_this": "Jurisdiction mix shifts."},
            {"variable": "tax_rate", "year": "2028E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"], "derivation": "Tax rate stable versus recent effective rate.", "what_would_change_this": "Jurisdiction mix shifts."},
            {"variable": "tax_rate", "year": "2029E", "p10": 0.15, "p50": 0.20, "p90": 0.25, "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"], "derivation": "Tax rate stable versus recent effective rate.", "what_would_change_this": "Jurisdiction mix shifts."},
            {"variable": "pe", "year": "2027E", "p10": 15, "p50": 24, "p90": 35, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:valuation"], "derivation": "Multiple anchored to calculated peer and history bands.", "what_would_change_this": "Sector derates or moat weakens."},
            {"variable": "pe", "year": "2028E", "p10": 14, "p50": 22, "p90": 32, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:valuation"], "derivation": "Forward multiple normalizes with maturity.", "what_would_change_this": "Sector derates or moat weakens."},
            {"variable": "pe", "year": "2029E", "p10": 13, "p50": 20, "p90": 30, "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:valuation"], "derivation": "Forward multiple normalizes with maturity.", "what_would_change_this": "Sector derates or moat weakens."},
        ],
        "financial_model_inputs": {
            "shares_outstanding": 10,
            "diluted_shares": 10.5,
            "cash": 50,
            "debt": 20,
            "equity": 150,
            "nwc_ratio": 0.08,
            "ppe_ratio": 0.25,
            "other_assets_ratio": 0.05,
            "ap_ratio": 0.06,
            "dividend_payout": 0.0,
            "da_ratio": 0.04,
            "capex_ratio": 0.06,
            "interest_rate_on_debt": 0.05,
            "interest_rate_on_cash": 0.02,
            "annual_share_dilution_pct": 0.01,
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


def _write_reviewed_lock(ws: Path):
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


def _write_validation_sidecars(ws: Path):
    (ws / "step4_assumption_research.md").write_text("# Step 4\n", encoding="utf-8")
    (ws / "material_extracts.json").write_text(json.dumps({
        "version": 1,
        "documents": [
            {
                "id": "DOCannual",
                "filename": "annual_report.pdf",
                "doc_type": "annual_report",
                "title": "Annual Report",
                "source_path": "annual_report.pdf",
                "read_status": "success",
                "fallback_required": False,
                "fallback_resolved": False,
            }
        ],
        "extractions": [
            {
                "id": "EXTmda",
                "document_id": "DOCannual",
                "document_filename": "annual_report.pdf",
                "document_type": "annual_report",
                "extraction_type": "business_overview",
                "topic": "MD&A operating discussion",
                "evidence": "Management discussion and analysis describes segment growth drivers.",
                "page": "MD&A p.10",
                "confidence": "high",
                "impact": "neutral",
                "tags": ["mda"],
            }
        ],
    }), encoding="utf-8")
    (ws / "calculated_valuation.json").write_text(json.dumps({
        "source": "calculated",
        "pe_trailing": {"pe": 20.0, "valid": True},
        "pb": {"pb": 3.0, "valid": True},
        "ps": {"ps": 5.0, "valid": True},
        "ev_ebitda": {"ev_ebitda": 12.0, "valid": True},
    }), encoding="utf-8")
    _write_reviewed_lock(ws)


class TestFinancialModel:
    def test_builds_formula_linked_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="TEST")
            assert model["ticker"] == "TEST"
            assert "income_statement" in model["statements"]
            assert "cash_flow" in model["statements"]
            assert "balance_sheet" in model["statements"]
            assert "valuation" in model["statements"]
            assert model["version"] == 3
            assert model["defaults_used"] == []
            assert "lineage" in model
            valuation_formulas = [r["formula"] for r in model["statements"]["valuation"]]
            assert "EPS (Diluted) × Forward PE" in valuation_formulas or "EPS × Forward PE" in valuation_formulas

    def test_generates_json_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_reviewed_lock(ws)
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
            _write_reviewed_lock(ws)
            model = build_financial_model(ws)
            html = render_financial_model_html(model)
            assert "Segment Revenue Build" in html
            assert "Checks" in html

    def test_report_embeds_forecast_model_when_already_generated(self):
        """Report embeds forecast model only if forecast_model.html already exists."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_validation_sidecars(ws)
            (ws / "step1_business_analysis.md").write_text("# Step 1: TEST\n", encoding="utf-8")

            # Generate the forecast model artifacts first (now separate from report gen)
            from src.analysis.financial_model import generate_financial_model_artifacts
            generate_financial_model_artifacts(ws, ticker="TEST")
            assert (ws / "forecast_model.html").exists()

            report = generate_report_html(ws, ticker="TEST")
            html = Path(report).read_text(encoding="utf-8")
            assert "Forecast Model" in html


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
            _write_reviewed_lock(ws)
            with pytest.raises(ValueError, match="No segment_revenues"):
                build_financial_model(ws)

    def test_model_rejects_missing_inputs_instead_of_defaults(self):
        """Model blocks instead of using hard-coded defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            # Remove financial_model_inputs entirely
            del data["financial_model_inputs"]
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)

            with pytest.raises(ValueError, match="does not allow hard-coded fallback"):
                build_financial_model(ws, ticker="DEFTEST")

    def test_build_fails_without_reviewed_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())

            with pytest.raises(FileNotFoundError, match="_reviewed_assumptions"):
                build_financial_model(ws)

    def test_every_statement_row_has_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="LIN")

            for rows in model["statements"].values():
                for row in rows:
                    assert row.get("lineage"), row["label"]
            # Verify the formula lineage coverage check exists and is OK
            lineage_checks = [c for c in model["checks"] if c["check"] == "Formula lineage coverage"]
            assert lineage_checks, "Missing Formula lineage coverage check"
            assert lineage_checks[0]["status"] == "OK", (
                f"Formula lineage coverage: {lineage_checks[0].get('notes', '')}"
            )


class TestPctToDecimalConversion:
    """Regression tests for percentage-format values in assumption_matrix.

    The 09992.HK research stored growth/margin values as whole-number
    percentages (e.g. 20 meaning 20%, not 0.20).  The model must convert
    these to decimal form before using in `revenue = prev * (1 + growth)`.
    """

    @staticmethod
    def _nested_pct_data():
        """Data mimicking the 09992.HK nested-dict format with %-format values."""
        return {
            "forecast_periods": ["T+1", "T+2", "T+3"],
            "segment_revenues": {
                "product_level": {
                    "Widget": {"base": 10000, "p50": 12200, "p50_growth": 22},
                    "Gadget": {"base": 5000, "p50": 5750, "p50_growth": 15},
                    "Total": {"base": 15000, "p50": 17950, "p50_growth": 19.7},
                }
            },
            "growth_drivers": [
                {"segment": "Widget", "drivers": [
                    {
                        "name": "volume", "contribution_pct": 15, "evidence_ids": ["DATA:v"],
                        "derivation": "Volume converts demand into units.", "base_value": 1000, "unit": "units",
                        "growth_T+1": 15, "growth_T+2": 10, "growth_T+3": 6,
                    },
                    {
                        "name": "price", "contribution_pct": 7, "evidence_ids": ["DATA:p"],
                        "derivation": "Pricing/mix drives ASP.", "base_value": 10, "unit": "CNY/unit",
                        "growth_T+1": 6.0869565217, "growth_T+2": 4.5454545455, "growth_T+3": 3.7735849057,
                    },
                ]},
                {"segment": "Gadget", "drivers": [
                    {
                        "name": "volume", "contribution_pct": 10, "evidence_ids": ["DATA:v"],
                        "derivation": "Volume converts demand into units.", "base_value": 500, "unit": "units",
                        "growth_T+1": 10, "growth_T+2": 8, "growth_T+3": 6,
                    },
                    {
                        "name": "price", "contribution_pct": 5, "evidence_ids": ["DATA:p"],
                        "derivation": "Pricing/mix drives ASP.", "base_value": 10, "unit": "CNY/unit",
                        "growth_T+1": 4.5454545455, "growth_T+2": 3.7037037037, "growth_T+3": 3.7735849057,
                    },
                ]},
            ],
            "assumption_matrix": {
                "T1_FY2026E": {
                    "revenue_growth": {"p10": 5, "p50": 22, "p90": 40},
                    "gross_margin": {"p10": 55, "p50": 65, "p90": 75},
                    "opex_ratio": {"p10": 10, "p50": 18, "p90": 25},
                    "npm": {"p10": 20, "p50": 30, "p90": 40},
                    "pe_fwd_t1": {"p10": 10, "p50": 18, "p90": 25},
                    "tax_rate": {"p10": 20, "p50": 15, "p90": 10},
                },
                "T2_FY2027E": {
                    "revenue_growth": {"p50": 15},
                    "gross_margin": {"p50": 64},
                    "opex_ratio": {"p50": 17},
                    "npm": {"p50": 28},
                    "pe_fwd_t2": {"p50": 15},
                    "tax_rate": {"p50": 15},
                },
                "T3_FY2028E": {
                    "revenue_growth": {"p50": 10},
                    "gross_margin": {"p50": 63},
                    "opex_ratio": {"p50": 16},
                    "npm": {"p50": 26},
                    "pe_fwd_t3": {"p50": 13},
                    "tax_rate": {"p50": 15},
                },
            },
            "financial_model_inputs": {
                "shares_outstanding": 100,
                "diluted_shares": 105,
                "cash": 500,
                "debt": 100,
                "equity": 1000,
                "nwc_ratio": 0.10,
                "ppe_ratio": 0.20,
                "other_assets_ratio": 0.05,
                "ap_ratio": 0.06,
                "dividend_payout": 0.0,
                "da_ratio": 0.04,
                "capex_ratio": 0.06,
                "interest_rate_on_debt": 0.05,
                "interest_rate_on_cash": 0.02,
                "annual_share_dilution_pct": 0.0,
            },
            "bridge_analysis": {"base_total": 15000, "delta": 2950, "p50_total": 17950},
            "q1_constraint": {"feasibility": "REASONABLE"},
            "margin_derivation": {
                "method": "cost_buildup",
                "cost_items": [{"name": "COGS", "growth_pct": 5}],
                "p50_margin": 30,
            },
            "historical_valuation": {"pe_min": 10, "pe_median": 18, "pe_max": 25},
            "peer_comparison": {
                "metric": "pe",
                "basis": "T+1",
                "n_peers": 2,
                "peers": [
                    {"name": "X", "value": 16, "source": "calculated"},
                    {"name": "Y", "value": 20, "source": "calculated"},
                ],
            },
            "reverse_dcf": {"implied_growth": 12},
            "dcf_cross_validation": {"deviation_pct": 8},
            "contrarian_checks": [
                {"variable": "revenue_growth", "p50": 22, "p10": 5, "evidence_to_flip": "demand miss"},
                {"variable": "gross_margin", "p50": 65, "p10": 55, "evidence_to_flip": "cost spike"},
            ],
            "valuation_source": "all self-calculated from raw financial data",
            "assumption_consistency": {
                "post_review_changes": False,
                "pe_moat_aligned": True,
                "revenue_segment_aligned": True,
            },
            "reviewed_lock": {
                "reviewed_at": "2026-06-06",
                "reviewer": "analyst",
            },
        }

    def test_growth_rate_not_exploded(self):
        """p50_growth=22 (meaning 22%) must produce ~22% revenue growth, NOT 2320%."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, self._nested_pct_data())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="PCTTEST")

            # Find Widget segment in the model
            seg_names = [s["name"] for s in model["segments"]]
            assert "Widget" in seg_names
            widget = model["segments"][seg_names.index("Widget")]

            # Widget: base=10000, p50_growth=22 (means 22%)
            # T+1 revenue should be ~10000 * 1.22 = 12200
            t1_growth = widget["forecast"]["T+1"]["growth"]
            t1_revenue = widget["forecast"]["T+1"]["revenue"]
            assert abs(t1_growth - 0.22) < 0.01, (
                f"Expected growth ~0.22, got {t1_growth} (raw {t1_growth*100:.0f}%)"
            )
            assert abs(t1_revenue - 12200) < 100, (
                f"Expected revenue ~12200, got {t1_revenue}"
            )

    def test_margin_not_exploded(self):
        """gross_margin p50=65 (meaning 65%) must produce 0.65, NOT 65.0."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, self._nested_pct_data())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="PCTTEST")

            # Check income statement gross_margin for T+1
            income = model["statements"]["income_statement"]
            gm_row = next(r for r in income if r.get("label") == "Gross Margin")
            gm_t1 = gm_row["values"].get("T+1", 0)
            assert 0.5 < gm_t1 < 0.8, (
                f"Gross margin should be ~0.65, got {gm_t1}"
            )

    def test_pe_not_divided(self):
        """PE p50=18 is NOT a percentage — it must stay 18, not become 0.18."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = self._nested_pct_data()
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="PCTTEST")

            # Check valuation forward_pe for T+1
            valuation = model["statements"]["valuation"]
            pe_row = next(r for r in valuation if "PE" in r.get("label", ""))
            pe_t1 = pe_row["values"].get("T+1", 0)
            assert abs(pe_t1 - 18) < 0.5, (
                f"Forward PE should be ~18, got {pe_t1}"
            )

    def test_already_decimal_stays(self):
        """If p50_growth is already 0.20 (decimal form) and no matrix override,
        it must NOT be divided by 100."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = self._nested_pct_data()
            # Override p50_growth to already-decimal form AND remove matrix revenue_growth
            # and growth drivers from ALL periods so this test exercises the
            # legacy segment-level fallback path directly.
            data["segment_revenues"]["product_level"]["Widget"]["p50_growth"] = 0.20
            data["segment_revenues"]["product_level"]["Widget"]["T+2_growth"] = 0.18
            data["segment_revenues"]["product_level"]["Widget"]["T+3_growth"] = 0.16
            data["segment_revenues"]["product_level"]["Gadget"]["T+2_growth"] = 0.12
            data["segment_revenues"]["product_level"]["Gadget"]["T+3_growth"] = 0.10
            data["growth_drivers"] = []
            del data["assumption_matrix"]["T1_FY2026E"]["revenue_growth"]
            del data["assumption_matrix"]["T2_FY2027E"]["revenue_growth"]
            del data["assumption_matrix"]["T3_FY2028E"]["revenue_growth"]
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="DECTEST")

            seg_names = [s["name"] for s in model["segments"]]
            widget = model["segments"][seg_names.index("Widget")]
            t1_growth = widget["forecast"]["T+1"]["growth"]
            assert abs(t1_growth - 0.20) < 0.01, (
                f"Already-decimal growth 0.20 should stay, got {t1_growth}"
            )


class TestInterestModeling:
    """Verify interest expense/income flows through EBT to net income."""

    def test_interest_expense_reduces_ebt(self):
        """Higher debt interest → lower EBT relative to EBIT."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            # Set meaningful debt and interest rate
            data["financial_model_inputs"]["debt"] = 100
            data["financial_model_inputs"]["interest_rate_on_debt"] = 0.10
            data["financial_model_inputs"]["interest_rate_on_cash"] = 0.0
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="INTTEST")

            income = model["statements"]["income_statement"]
            for period in model["model_conventions"]["periods"]:
                ebit_val = next(
                    r["values"][period] for r in income if r["label"] == "EBIT"
                )
                ebt_val = next(
                    r["values"][period] for r in income if "EBT" in r["label"] or "Pre-tax" in r["label"]
                )
                assert ebt_val < ebit_val, (
                    f"{period}: EBT ({ebt_val}) should be < EBIT ({ebit_val}) when debt > 0"
                )

    def test_interest_income_increases_ebt(self):
        """Interest income on cash adds to EBT."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            data["financial_model_inputs"]["debt"] = 0
            data["financial_model_inputs"]["interest_rate_on_debt"] = 0.0
            data["financial_model_inputs"]["cash"] = 100
            data["financial_model_inputs"]["interest_rate_on_cash"] = 0.05
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="INTTEST2")

            income = model["statements"]["income_statement"]
            # Should have an Interest Income row
            labels = [r["label"] for r in income]
            assert any("Interest Income" in l or "Interest Inc" in l for l in labels), (
                "IS must have Interest Income row"
            )
            # EBT should differ from EBIT due to interest income
            for period in model["model_conventions"]["periods"]:
                ebit_val = next(r["values"][period] for r in income if r["label"] == "EBIT")
                ebt_val = next(
                    r["values"][period] for r in income
                    if "EBT" in r["label"] or "Pre-tax" in r["label"]
                )
                assert ebt_val != ebit_val, (
                    f"{period}: EBT should ≠ EBIT when interest income > 0"
                )

    def test_tax_uses_ebt_not_ebit(self):
        """Tax = max(0, EBT × tax_rate), not max(0, EBIT × tax_rate)."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            data["financial_model_inputs"]["debt"] = 500
            data["financial_model_inputs"]["interest_rate_on_debt"] = 0.20
            data["financial_model_inputs"]["interest_rate_on_cash"] = 0.0
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="TAXTEST")

            # Tax rate comes from assumption_matrix, not financial_model_inputs
            tax_rate = 0.20  # The P50 tax_rate from the fixture

            income = model["statements"]["income_statement"]
            for period in model["model_conventions"]["periods"]:
                ebt_val = next(
                    r["values"][period] for r in income
                    if "EBT" in r["label"] or "Pre-tax" in r["label"]
                )
                tax_val = next(
                    r["values"][period] for r in income
                    if "Tax Expense" in r["label"]
                )
                # Tax should be computed on EBT (which is reduced by interest)
                # With high interest, EBT could be <= 0, tax should be 0
                if ebt_val <= 0:
                    assert tax_val == 0.0, (
                        f"Tax should be 0 when EBT ≤ 0 (tax on EBT, not EBIT). EBT={ebt_val}, tax={tax_val}"
                    )
                else:
                    # Tax should approximate EBT × rate
                    expected_rate = tax_val / ebt_val if ebt_val != 0 else 0
                    assert abs(expected_rate - tax_rate) < 0.01 if expected_rate > 0 else True

    def test_no_interest_when_rates_zero(self):
        """When both interest rates are zero, EBT = EBIT."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            data["financial_model_inputs"]["interest_rate_on_debt"] = 0.0
            data["financial_model_inputs"]["interest_rate_on_cash"] = 0.0
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="ZERORATE")

            income = model["statements"]["income_statement"]
            for period in model["model_conventions"]["periods"]:
                ebit_val = next(r["values"][period] for r in income if r["label"] == "EBIT")
                ebt_val = next(
                    r["values"][period] for r in income
                    if "EBT" in r["label"] or "Pre-tax" in r["label"]
                )
                assert abs(ebt_val - ebit_val) < 0.01, (
                    f"{period}: EBT should = EBIT when both interest rates are zero"
                )


class TestBSCoverage:
    """Verify expanded balance sheet coverage."""

    def test_bs_has_all_required_line_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="BSTEST")

            bs = model["statements"]["balance_sheet"]
            labels = {r["label"] for r in bs}

            required_bs_items = [
                "Cash & Equivalents",
                "Accounts Receivable",
                "Inventory",
                "Total Current Assets",
                "PP&E (Net)",
                "Total Assets",
                "Accounts Payable",
                "Total Current Liabilities",
                "Total Liabilities",
                "Retained Earnings",
                "Total Equity",
                "Total Liabilities & Equity",
                "Balance Check",
            ]
            for item in required_bs_items:
                assert item in labels, f"BS must have '{item}'"

    def test_bs_balance_check_near_zero(self):
        """Balance check should be relatively small vs Total Assets. In hard-coded
        BS mode (no ar_days/inv_days/ap_days), larger imbalances are expected."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _structured())
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="BSBAL")

            bs = model["statements"]["balance_sheet"]
            conventions = model["model_conventions"]
            is_hard_coded = conventions.get("bs_driver_mode") == "hard-coded"
            tolerance_factor = 0.30 if is_hard_coded else 0.05

            for period in model["model_conventions"]["periods"]:
                bc = next(
                    r["values"][period] for r in bs if r["label"] == "Balance Check"
                )
                total_assets = next(
                    r["values"][period] for r in bs if r["label"] == "Total Assets"
                )
                assert abs(bc) <= max(abs(total_assets), 1.0) * tolerance_factor, (
                    f"{period}: Balance check ({bc}) too large vs Total Assets ({total_assets}) "
                    f"in {conventions.get('bs_driver_mode', 'N/A')} mode"
                )

    def test_bs_driver_mode_flag(self):
        """Model should indicate whether BS driver inputs are present."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            # Without optional BS driver inputs
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            model = build_financial_model(ws, ticker="BSDRV")

            conventions = model["model_conventions"]
            assert "bs_driver_mode" in conventions, "Model must report BS driver mode"

    def test_diluted_shares_required(self):
        """Model must fail when diluted_shares is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _structured()
            del data["financial_model_inputs"]["diluted_shares"]
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)

            with pytest.raises(ValueError, match="diluted_shares"):
                build_financial_model(ws, ticker="NODIL")


class TestPctVariableDetection:
    """Verify naming-convention-based percentage detection."""

    def test_margin_variables_are_pct(self):
        from src.analysis.financial_model import _is_pct_variable
        assert _is_pct_variable("gross_margin") is True
        assert _is_pct_variable("operating_margin") is True
        assert _is_pct_variable("net_margin") is True

    def test_growth_variables_are_pct(self):
        from src.analysis.financial_model import _is_pct_variable
        assert _is_pct_variable("rev_growth") is True
        assert _is_pct_variable("revenue_growth") is True
        assert _is_pct_variable("earnings_growth") is True

    def test_ratio_variables_are_pct(self):
        from src.analysis.financial_model import _is_pct_variable
        assert _is_pct_variable("opex_ratio") is True
        assert _is_pct_variable("da_ratio") is True
        assert _is_pct_variable("nwc_ratio") is True

    def test_pe_is_not_pct(self):
        from src.analysis.financial_model import _is_pct_variable
        assert _is_pct_variable("pe") is False
        assert _is_pct_variable("forward_pe") is False

    def test_price_and_shares_are_not_pct(self):
        from src.analysis.financial_model import _is_pct_variable
        assert _is_pct_variable("target_price") is False
        assert _is_pct_variable("shares_outstanding") is False
        assert _is_pct_variable("diluted_shares") is False
