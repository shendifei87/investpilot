"""Tests for dual-track Step 4 validation.

Validates:
  - Structured JSON validation path (primary)
  - Legacy regex fallback path (backward compatible)
  - Bridge arithmetic, Q1 constraint, peer apple-to-apple checks
"""

import json
from pathlib import Path

import pytest

from src.analysis.step4_validate import (
    validate_step4,
    _load_structured_json,
    _validate_structured,
)


def _write_step4_md(tmp: Path, content: str = "# Step 4 Quantitative Model\n") -> Path:
    """Write a minimal step4 markdown file and return its path."""
    md_path = tmp / "step4_quantitative_model.md"
    md_path.write_text(content, encoding="utf-8")
    return md_path


def _write_structured_json(tmp: Path, structured: dict) -> Path:
    """Write structured JSON alongside the markdown."""
    json_path = tmp / "step4_structured_assumptions.json"
    json_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def _full_valid_structured() -> dict:
    """Return a complete valid structured JSON that should pass all checks."""
    return {
        "segment_revenues": [
            {"name": "seg1", "base_revenue": 100, "p50_growth": 0.15, "p50_revenue": 115},
            {"name": "seg2", "base_revenue": 200, "p50_growth": 0.10, "p50_revenue": 220},
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
            {"segment": "seg1", "drivers": [{"name": "volume", "contribution_pct": 0.08}]},
            {"segment": "seg2", "drivers": [{"name": "ASP", "contribution_pct": 0.10}]},
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
            {"variable": "margin", "p50": 0.45, "p10": 0.35, "evidence_to_flip": "Price war"},
            {"variable": "PE", "p50": 22, "p10": 15, "evidence_to_flip": "Sector de-rating"},
        ],
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
        # Check 15 requires calculated_valuation.json in workspace
        calc_val = tmp_path / "calculated_valuation.json"
        calc_val.write_text(json.dumps({
            "source": "calculated",
            "pe_trailing": {"pe": 20.0, "valid": True},
            "pb": {"pb": 3.0, "valid": True},
            "ps": {"ps": 5.0, "valid": True},
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


class TestLegacyFallback:
    def test_legacy_mode_when_no_json(self, tmp_path):
        md_path = _write_step4_md(tmp_path, "# Step 4\n驱动因子 analysis here\n")
        result = validate_step4(md_path)
        assert result["validation_mode"] == "regex_markdown"

    def test_legacy_checks_run(self, tmp_path):
        """Legacy path should still run all checks."""
        md_path = _write_step4_md(tmp_path, "# Step 4\nSome content without keywords\n")
        result = validate_step4(md_path)
        assert len(result["checks"]) >= 14  # 14 legacy + 1 (check 15)


class TestFileNotFound:
    def test_missing_file(self):
        result = validate_step4("/nonexistent/path/step4.md")
        assert result["passed"] is False
        assert "error" in result
