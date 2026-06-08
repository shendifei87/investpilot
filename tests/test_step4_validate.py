"""Tests for structured Step 4 validation.

Validates:
  - Structured JSON validation path
  - Markdown-only Step 4 rejection
  - Bridge arithmetic, Q1 constraint, peer apple-to-apple checks
"""

import json
from pathlib import Path

import pytest

from src.analysis.step4_validate import (
    validate_contrarian_checks,
    validate_step4,
    validate_step4_with_guard,
    _load_structured_json,
    _validate_structured,
)


def _write_step4_md(tmp: Path, content: str = "# Step 4 Assumption Research\n") -> Path:
    """Write a minimal Step 4 markdown file and return its path."""
    md_path = tmp / "step4_assumption_research.md"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def _write_structured_json(tmp: Path, structured: dict) -> Path:
    """Write structured JSON alongside the markdown."""
    json_path = tmp / "step4_structured_assumptions.json"
    json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def _write_material_sidecar(tmp: Path) -> None:
    """Write minimal annual-report MD&A evidence required by Step 4."""
    payload = {
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
                "evidence": "Management discussion and analysis describes segment volume and ASP drivers.",
                "page": "MD&A p.12",
                "confidence": "high",
                "impact": "neutral",
                "tags": ["mda"],
            }
        ],
    }
    (tmp / "material_extracts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _full_valid_structured() -> dict:
    """Return a complete valid structured JSON that should pass all checks."""
    return {
        "segment_revenues": [
            {
                "name": "seg1", "base_revenue": 100,
                "p10_growth": 0.05, "p30_growth": 0.10, "p50_growth": 0.15,
                "p70_growth": 0.18, "p90_growth": 0.22, "p50_revenue": 115,
            },
            {
                "name": "seg2", "base_revenue": 200,
                "p10_growth": 0.02, "p30_growth": 0.06, "p50_growth": 0.10,
                "p70_growth": 0.13, "p90_growth": 0.16, "p50_revenue": 220,
            },
        ],
        "bridge_analysis": {
            "base_total": 300,
            "p50_total": 335,
            "delta": 35,
            "components": [{"name": "seg1", "p50_contribution": 15}],
        },
        "q1_constraint": {
            "q1_actual": 80,
            "q1_last_year": 70,
            "full_year_estimate": 335,
            "full_year_last_year": 300,
            "feasibility": "REASONABLE",
        },
        "margin_derivation": {
            "method": "cost_buildup",
            "cost_items": [
                {"name": "COGS", "growth_pct": 0.08},
                {"name": "Labor", "growth_pct": 0.05},
            ],
            "p50_margin": 0.45,
        },
        "growth_drivers": [
            {
                "segment": "seg1",
                "drivers": [
                    {
                        "name": "volume",
                        "contribution_pct": 0.10,
                        "evidence_ids": ["DATA:orders"],
                        "derivation": "Order backlog converts into unit volume contribution.",
                    },
                    {
                        "name": "ASP",
                        "contribution_pct": 0.05,
                        "evidence_ids": ["DATA:pricing"],
                        "derivation": "ASP uplift from price ladder and mix shift evidence.",
                    },
                ],
            },
            {
                "segment": "seg2",
                "drivers": [
                    {
                        "name": "market_size",
                        "contribution_pct": 0.06,
                        "evidence_ids": ["WEB:industry"],
                        "derivation": "Industry volume growth converted into segment contribution.",
                    },
                    {
                        "name": "share_gain",
                        "contribution_pct": 0.04,
                        "evidence_ids": ["DATA:customers"],
                        "derivation": "New customer wins imply incremental share gain.",
                    },
                ],
            },
        ],
        "assumption_matrix": [
            {
                "variable": "rev_growth", "segment": "total", "year": "T+1",
                "p10": 0.03, "p30": 0.07, "p50": 0.1167, "p70": 0.15, "p90": 0.19,
                "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:orders"],
                "derivation": "Weighted segment growth from volume, ASP, market size, and share drivers.",
                "what_would_change_this": "Order intake drops below prior-year run rate.",
            },
            {
                "variable": "gross_margin", "segment": "total", "year": "T+1",
                "p10": 0.35, "p30": 0.40, "p50": 0.45, "p70": 0.48, "p90": 0.52,
                "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:costs"],
                "derivation": "Cost buildup from COGS and labor inflation offset by pricing.",
                "what_would_change_this": "Input cost inflation exceeds pricing pass-through.",
            },
            {
                "variable": "opex_ratio", "segment": "total", "year": "T+1",
                "p10": 0.18, "p30": 0.20, "p50": 0.22, "p70": 0.24, "p90": 0.26,
                "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:costs"],
                "derivation": "Operating expense ratio derived from historical cost structure.",
                "what_would_change_this": "Hiring and R&D spend ramps faster than revenue.",
            },
            {
                "variable": "tax_rate", "segment": "total", "year": "T+1",
                "p10": 0.15, "p30": 0.18, "p50": 0.20, "p70": 0.22, "p90": 0.25,
                "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"],
                "derivation": "Effective tax rate anchored to recent statutory and effective rates.",
                "what_would_change_this": "Jurisdiction mix or tax policy changes materially.",
            },
            {
                "variable": "pe", "segment": "company", "year": "T+1",
                "p10": 15, "p30": 18, "p50": 22, "p70": 27, "p90": 35,
                "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:calculated_valuation.json"],
                "derivation": "Forward PE anchored to self-calculated history and peer distribution.",
                "what_would_change_this": "Sector multiple derates or moat evidence weakens.",
            },
        ],
        "historical_valuation": {
            "pe_min": 15,
            "pe_median": 22,
            "pe_max": 35,
            "current_percentile": 0.60,
            "period_years": 5,
        },
        "peer_comparison": {
            "metric": "pe",
            "basis": "T+1",
            "n_peers": 3,
            "peers": [
                {"name": "PeerA", "value": 25, "source": "calculated"},
                {"name": "PeerB", "value": 20, "source": "calculated"},
                {"name": "PeerC", "value": 22, "source": "calculated"},
            ],
        },
        "reverse_dcf": {
            "implied_growth": 0.12,
            "current_price": 100,
        },
        "dcf_cross_validation": {
            "dcf_intrinsic_value": 105,
            "mc_p50_price": 100,
            "deviation_pct": 0.05,
        },
        "contrarian_checks": [
            {"variable": "revenue", "p50": 0.15, "p10": 0.05, "evidence_to_flip": "Q1 miss"},
            {"variable": "rev_growth", "p50": 0.1167, "p10": 0.03, "evidence_to_flip": "Q1 miss"},
            {"variable": "gross_margin", "p50": 0.45, "p10": 0.35, "evidence_to_flip": "Price war"},
            {"variable": "pe", "p50": 22, "p10": 15, "evidence_to_flip": "Sector de-rating"},
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
        },
        "assumption_consistency": {
            "post_review_changes": False,
            "pe_moat_aligned": True,
            "revenue_segment_aligned": True,
        },
        "valuation_source": {
            "pe_calculated": True,
            "calc_inputs_disclosed": True,
        },
    }


class TestLoadStructuredJson:
    def test_loads_when_exists(self, tmp_path):
        structured = {"segment_revenues": []}
        _write_structured_json(tmp_path, structured)
        md_path = _write_step4_md(tmp_path)
        result = _load_structured_json(md_path)
        assert result is not None
        assert "segment_revenues" in result

    def test_returns_none_when_missing(self, tmp_path):
        md_path = _write_step4_md(tmp_path)
        assert _load_structured_json(md_path) is None

    def test_returns_none_on_invalid_json(self, tmp_path):
        bad_path = tmp_path / "step4_structured_assumptions.json"
        bad_path.write_text("not valid json{{{", encoding="utf-8")
        md_path = _write_step4_md(tmp_path)
        assert _load_structured_json(md_path) is None


class TestStructuredValidation:
    def test_full_valid_passes(self, tmp_path):
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, _full_valid_structured())
        _write_material_sidecar(tmp_path)
        # Check 15 requires calculated_valuation.json in workspace
        calc_val = tmp_path / "calculated_valuation.json"
        calc_val.write_text(json.dumps({
            "source": "calculated",
            "pe_trailing": {"pe": 20.0, "valid": True},
            "pb": {"pb": 3.0, "valid": True},
            "ps": {"ps": 5.0, "valid": True},
        }), encoding="utf-8")
        reviewed = tmp_path / "_reviewed_assumptions.json"
        reviewed.write_text(json.dumps({
            "reviewed_at": "2026-01-01",
            "assumptions": {
                "rev_growth": {"p10": 0.03, "p50": 0.1167, "p90": 0.19},
                "gross_margin": {"p10": 0.35, "p50": 0.45, "p90": 0.52},
                "opex_ratio": {"p10": 0.18, "p50": 0.22, "p90": 0.26},
                "tax_rate": {"p10": 0.15, "p50": 0.20, "p90": 0.25},
                "pe": {"p10": 15, "p50": 22, "p90": 35},
            },
        }), encoding="utf-8")
        result = validate_step4(md_path)
        assert result["validation_mode"] == "structured_json"
        assert result["passed"] is True, f"Unexpected failures: {result['fix_required'][:3]}"

    def test_bridge_arithmetic_fail(self, tmp_path):
        structured = _full_valid_structured()
        # base 300 + delta 35 = 335, but we say p50_total = 500
        structured["bridge_analysis"]["p50_total"] = 500
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        bridge = [c for c in result["checks"] if c["check"] == "bridge_arithmetic"]
        assert bridge[0]["status"] == "FAIL"

    def test_segment_sum_fail(self, tmp_path):
        structured = _full_valid_structured()
        # segments sum to 335 but bridge says 500
        structured["bridge_analysis"]["p50_total"] = 500
        structured["bridge_analysis"]["delta"] = 200
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        seg = [c for c in result["checks"] if c["check"] == "segment_sum"]
        assert seg[0]["status"] == "FAIL"

    def test_segment_sum_ignores_total_row(self, tmp_path):
        structured = _full_valid_structured()
        structured["segment_revenues"].append({
            "name": "Total",
            "base_revenue": 300,
            "p50_growth": 0.1167,
            "p50_revenue": 335,
        })
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        seg = [c for c in result["checks"] if c["check"] == "segment_sum"]
        assert seg[0]["status"] == "PASS"

    def test_numeric_strings_are_coerced_for_structured_arithmetic(self, tmp_path):
        structured = _full_valid_structured()
        structured["bridge_analysis"]["base_total"] = "300"
        structured["bridge_analysis"]["delta"] = "35"
        structured["bridge_analysis"]["p50_total"] = "335"
        structured["dcf_cross_validation"]["deviation_pct"] = "5%"
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        bridge = [c for c in result["checks"] if c["check"] == "bridge_arithmetic"]
        dcf = [c for c in result["checks"] if c["check"] == "dcf_cross_validation"]
        assert bridge[0]["status"] == "PASS"
        assert dcf[0]["status"] == "PASS"

    def test_q1_unreasonable(self, tmp_path):
        structured = _full_valid_structured()
        structured["q1_constraint"]["feasibility"] = "UNREASONABLE"
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        q1 = [c for c in result["checks"] if c["check"] == "q1_constraint"]
        assert q1[0]["status"] == "FAIL"

    def test_dcf_deviation_too_large(self, tmp_path):
        structured = _full_valid_structured()
        structured["dcf_cross_validation"]["deviation_pct"] = 0.50
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        dcf = [c for c in result["checks"] if c["check"] == "dcf_cross_validation"]
        assert dcf[0]["status"] == "FAIL"

    def test_too_few_contrarian_checks(self, tmp_path):
        structured = _full_valid_structured()
        structured["contrarian_checks"] = [
            {"variable": "rev", "p50": 0.15, "p10": 0.05, "evidence_to_flip": "miss"},
        ]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        cc = [c for c in result["checks"] if c["check"] == "contrarian_per_variable"]
        assert cc[0]["status"] == "FAIL"

    def test_assumption_consistency_post_review_changes(self, tmp_path):
        structured = _full_valid_structured()
        structured["assumption_consistency"]["post_review_changes"] = True
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        ac = [c for c in result["checks"] if c["check"] == "assumption_consistency"]
        assert ac[0]["status"] == "FAIL"

    def test_valuation_source_not_calculated(self, tmp_path):
        structured = _full_valid_structured()
        structured["valuation_source"]["pe_calculated"] = False
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        vs = [c for c in result["checks"] if c["check"] == "valuation_ratios_calculated"]
        assert vs[0]["status"] == "FAIL"

    def test_valuation_source_string_must_be_calculated_not_news(self, tmp_path):
        structured = _full_valid_structured()
        structured["valuation_source"] = "PE copied from news article"
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        vs = [c for c in result["checks"] if c["check"] == "valuation_ratios_calculated"]
        assert vs[0]["status"] == "FAIL"

    def test_missing_section_fails(self, tmp_path):
        structured = _full_valid_structured()
        del structured["segment_revenues"]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        sr = [c for c in result["checks"] if c["check"] == "required_section:segment_revenues"]
        assert sr[0]["status"] == "MISSING"

    def test_peer_apple_to_apple_mixed_sources(self, tmp_path):
        structured = _full_valid_structured()
        structured["peer_comparison"]["peers"][0]["source"] = "news_article"
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        apple = [c for c in result["checks"] if c["check"] == "apple_to_apple_valuation"]
        assert apple[0]["status"] == "FAIL"

    def test_driver_evidence_missing_fails(self, tmp_path):
        structured = _full_valid_structured()
        structured["growth_drivers"][0]["drivers"][0]["evidence_ids"] = []
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        evidence = [c for c in result["checks"] if c["check"] == "driver_evidence_links"]
        assert evidence[0]["status"] == "FAIL"

    def test_too_many_growth_drivers_fails(self, tmp_path):
        structured = _full_valid_structured()
        structured["growth_drivers"][0]["drivers"].extend([
            {
                "name": "channel",
                "contribution_pct": 0.00,
                "evidence_ids": ["DATA:channel"],
                "derivation": "Channel checks show no incremental contribution.",
            },
            {
                "name": "fx",
                "contribution_pct": 0.00,
                "evidence_ids": ["DATA:fx"],
                "derivation": "FX contribution is neutral in base case.",
            },
            {
                "name": "other",
                "contribution_pct": 0.00,
                "evidence_ids": ["DATA:other"],
                "derivation": "Other items are immaterial.",
            },
        ])
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        depth = [c for c in result["checks"] if c["check"] == "driver_minimum_depth"]
        bare = [c for c in result["checks"] if c["check"] == "no_bare_growth_rates"]
        assert depth[0]["status"] == "FAIL"
        assert bare[0]["status"] == "FAIL"

    def test_driver_missing_derivation_fails(self, tmp_path):
        structured = _full_valid_structured()
        del structured["growth_drivers"][0]["drivers"][0]["derivation"]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        quantified = [c for c in result["checks"] if c["check"] == "driver_quantified_decomposition"]
        assert quantified[0]["status"] == "FAIL"

    def test_driver_contribution_sum_mismatch_fails(self, tmp_path):
        structured = _full_valid_structured()
        structured["growth_drivers"][0]["drivers"][0]["contribution_pct"] = 0.20
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        arithmetic = [c for c in result["checks"] if c["check"] == "driver_arithmetic"]
        assert arithmetic[0]["status"] == "FAIL"

    def test_assumption_missing_derivation_fails(self, tmp_path):
        structured = _full_valid_structured()
        del structured["assumption_matrix"][0]["derivation"]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        required = [c for c in result["checks"] if c["check"] == "assumption_matrix_required_fields"]
        assert required[0]["status"] == "FAIL"

    def test_missing_financial_model_inputs_fails(self, tmp_path):
        structured = _full_valid_structured()
        del structured["financial_model_inputs"]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        required = [c for c in result["checks"] if c["check"] == "financial_model_inputs_required_fields"]
        assert required[0]["status"] == "FAIL"

    def test_missing_step5_model_variable_fails(self, tmp_path):
        structured = _full_valid_structured()
        structured["assumption_matrix"] = [
            row for row in structured["assumption_matrix"]
            if row.get("variable") != "tax_rate"
        ]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        coverage = [c for c in result["checks"] if c["check"] == "assumption_matrix_model_variable_coverage"]
        assert coverage[0]["status"] == "FAIL"

    def test_missing_material_sidecar_fails_evidence_contract(self, tmp_path):
        structured = _full_valid_structured()
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)

        result = validate_step4(md_path)

        evidence = [c for c in result["checks"] if c["check"] == "evidence_registry_material_coverage"]
        assert evidence[0]["status"] == "FAIL"

    def test_high_sensitivity_missing_contrarian_fails(self, tmp_path):
        structured = _full_valid_structured()
        structured["contrarian_checks"] = [
            c for c in structured["contrarian_checks"]
            if c.get("variable") != "gross_margin"
        ]
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        coverage = [c for c in result["checks"] if c["check"] == "high_sensitivity_contrarian_coverage"]
        assert coverage[0]["status"] == "FAIL"

    def test_reviewed_lock_missing_fails(self, tmp_path):
        structured = _full_valid_structured()
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, structured)
        result = validate_step4(md_path)
        lock = [c for c in result["checks"] if c["check"] == "reviewed_assumption_lock_coverage"]
        assert lock[0]["status"] == "FAIL"


class TestStructuredOnlyValidation:
    def test_missing_json_requires_structured(self, tmp_path):
        """Without step4_structured_assumptions.json, validation reports structured_json_required."""
        md_path = _write_step4_md(tmp_path, "# Step 4\n驱动因子 analysis here\n")
        result = validate_step4(md_path)
        assert result["validation_mode"] == "structured_json_required"
        assert result["passed"] is False

    def test_structured_json_missing_reports_checks(self, tmp_path):
        """When structured JSON is absent, a clear MISSING check is produced."""
        md_path = _write_step4_md(tmp_path, "# Step 4\nSome content without keywords\n")
        result = validate_step4(md_path)
        assert len(result["checks"]) >= 1
        structured_check = [c for c in result["checks"] if c["check"] == "structured_assumptions"]
        assert structured_check[0]["status"] == "MISSING"

    def test_deprecated_combined_step4_rejected(self, tmp_path):
        md_path = tmp_path / "step4_quantitative_model.md"
        md_path.write_text("# Step 4\n", encoding="utf-8")
        result = validate_step4(md_path)
        assert result["passed"] is False
        assert "Deprecated Step 4 artifact is not accepted" in result["error"]

    def test_all_steps_contrarian_checks_pass(self, tmp_path):
        """All Steps 1-9 have contrarian check sections present."""
        (tmp_path / "step1_business_analysis.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step2_competitive_moat.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step3_marginal_changes.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step4_assumption_research.md").write_text(
            "P50 / P10 downside. Contrarian Check.\n",
            encoding="utf-8",
        )
        (tmp_path / "step5_financial_model.md").write_text(
            "模型公式 Contrarian Check.\n",
            encoding="utf-8",
        )
        (tmp_path / "step6_monte_carlo_simulation.md").write_text(
            "P50 / P10 压力测试 场景压力 Contrarian Check.\n",
            encoding="utf-8",
        )
        (tmp_path / "step7_rrr_strategy.md").write_text("逆向检验 RRR Edge Score\n", encoding="utf-8")
        (tmp_path / "step8_auditing.md").write_text("Red Team 自我批判\n", encoding="utf-8")
        (tmp_path / "step9_research_director_review.md").write_text("Director Override\n", encoding="utf-8")

        result = validate_contrarian_checks(tmp_path)
        assert result["passed"] is True
        assert result["steps"]["4"]["status"] == "PASS"
        assert result["steps"]["5"]["status"] == "PASS"
        assert result["steps"]["6"]["status"] == "PASS"
        assert result["steps"]["7"]["status"] == "PASS"
        assert result["steps"]["8"]["status"] == "PASS"
        assert result["steps"]["9"]["status"] == "PASS"

    def test_contrarian_checks_can_stop_at_step8(self, tmp_path):
        """Step 8 audit can run before Step 9 exists."""
        (tmp_path / "step1_business_analysis.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step2_competitive_moat.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step3_marginal_changes.md").write_text("Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step4_assumption_research.md").write_text("P50 P10 Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step5_financial_model.md").write_text("模型公式 Contrarian Check\n", encoding="utf-8")
        (tmp_path / "step6_monte_carlo_simulation.md").write_text("P50 P10 压力测试\n", encoding="utf-8")
        (tmp_path / "step7_rrr_strategy.md").write_text("逆向检验 RRR Edge Score\n", encoding="utf-8")
        (tmp_path / "step8_auditing.md").write_text("Red Team 自我批判\n", encoding="utf-8")

        result = validate_contrarian_checks(tmp_path, through_step=8)
        assert result["passed"] is True
        assert "9" not in result["steps"]


class TestFileNotFound:
    def test_missing_file(self):
        result = validate_step4("/nonexistent/path/step4.md")
        assert result["passed"] is False
        assert "error" in result


class TestStep4Guard:
    def test_writes_blocker_after_max_attempts(self, tmp_path):
        md_path = _write_step4_md(tmp_path, "# Step 4\nIncomplete\n")
        first = validate_step4_with_guard(md_path, max_attempts=2)
        assert first["passed"] is False
        assert first["guard"]["attempt_count"] == 1
        assert first["guard"]["should_stop"] is False

        second = validate_step4_with_guard(md_path, max_attempts=2)
        assert second["passed"] is False
        assert second["guard"]["attempt_count"] == 2
        assert second["guard"]["should_stop"] is True
        assert (tmp_path / "step4_blockers.md").exists()

    def test_resets_guard_on_pass(self, tmp_path):
        md_path = _write_step4_md(tmp_path)
        _write_structured_json(tmp_path, _full_valid_structured())
        _write_material_sidecar(tmp_path)
        (tmp_path / "calculated_valuation.json").write_text(json.dumps({
            "source": "calculated",
            "pe_trailing": {"pe": 20.0, "valid": True},
            "pb": {"pb": 3.0, "valid": True},
            "ps": {"ps": 5.0, "valid": True},
        }), encoding="utf-8")
        (tmp_path / "_reviewed_assumptions.json").write_text(json.dumps({
            "reviewed_at": "2026-01-01",
            "assumptions": {
                "rev_growth": {"p10": 0.03, "p50": 0.1167, "p90": 0.19},
                "gross_margin": {"p10": 0.35, "p50": 0.45, "p90": 0.52},
                "opex_ratio": {"p10": 0.18, "p50": 0.22, "p90": 0.26},
                "tax_rate": {"p10": 0.15, "p50": 0.20, "p90": 0.25},
                "pe": {"p10": 15, "p50": 22, "p90": 35},
            },
        }), encoding="utf-8")
        result = validate_step4_with_guard(md_path, max_attempts=2)
        assert result["passed"] is True
        state = json.loads((tmp_path / "step4_guard_state.json").read_text(encoding="utf-8"))
        assert state["attempt_count"] == 0
