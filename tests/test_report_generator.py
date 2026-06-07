"""Tests for src.report.generator — report generation engine.

Covers: md_to_html conversion, summary metric extraction,
distribution chart and PE band chart generation.
"""

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.report.generator import (
    generate_report_html,
    generate_distribution_chart,
    generate_pe_band_chart,
    md_to_html,
    _extract_summary_metrics,
    _read_json_safe,
    _embed_image_as_base64,
    _auto_embed_workspace_images,
)
from src.report._html_templates import STEP_CONFIG


# ---------------------------------------------------------------------------
# md_to_html
# ---------------------------------------------------------------------------

class TestMdToHtml:
    def test_headings(self):
        md = "## Section Title\n### Subsection"
        html = md_to_html(md)
        assert "<h3>" in html
        assert "<h4>" in html

    def test_table_conversion(self):
        md = "| Col1 | Col2 |\n|:-----|:-----|\n| A | B |"
        html = md_to_html(md)
        assert "<table>" in html
        assert "<th" in html or "<td" in html

    def test_bold_inline(self):
        md = "This is **bold** text."
        html = md_to_html(md)
        assert "<strong>bold</strong>" in html

    def test_code_inline(self):
        md = "Use `calc_pe()` function."
        html = md_to_html(md)
        assert "<code>calc_pe()</code>" in html

    def test_list_unordered(self):
        md = "- Item 1\n- Item 2"
        html = md_to_html(md)
        assert "<li>" in html

    def test_blockquote(self):
        md = "> This is a quote"
        html = md_to_html(md)
        assert "<blockquote>" in html

    def test_h1_skipped(self):
        md = "# Step Title\n## Real heading"
        html = md_to_html(md)
        # H1 should be skipped; only H2+ converted
        assert "Step Title" not in html or "<h2>" not in html.split("Step Title")[0] if "Step Title" in html else True

    def test_image_base64_embedding(self):
        """Image references should be resolved and embedded as base64."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # Create a minimal 1x1 PNG
            import struct, zlib
            def _make_png():
                header = b"\x89PNG\r\n\x1a\n"
                ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
                ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
                raw = b"\x00\x00\x00\x00"
                compressed = zlib.compress(raw)
                idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
                idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
                iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
                iend = struct.pack(">I", 0) + b"IEND" + iend_crc
                return header + struct.pack(">I", 13) + b"IHDR" + ihdr + ihdr_crc + idat + iend

            (ws / "chart.png").write_bytes(_make_png())
            md = "![Chart](chart.png)"
            html = md_to_html(md, workspace_dir=str(ws))
            assert "data:image/png;base64," in html

    def test_image_missing_graceful(self):
        md = "![Missing](nonexistent.png)"
        html = md_to_html(md, workspace_dir="/tmp/nope")
        # Should not crash; just handle gracefully
        assert isinstance(html, str)

    def test_escapes_raw_html(self):
        md = "Hello <script>alert('x')</script>"
        html = md_to_html(md)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_image_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            outside = Path(tmp) / "outside.png"
            outside.write_bytes(_make_minimal_png())
            html = md_to_html("![Outside](../outside.png)", workspace_dir=str(ws))
            assert "data:image" not in html
            assert "Image not found" in html


# ---------------------------------------------------------------------------
# generate_distribution_chart
# ---------------------------------------------------------------------------

class TestGenerateDistributionChart:
    def test_produces_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(42)
            data = rng.normal(100, 10, size=10000)
            path = generate_distribution_chart(
                data,
                title="Test Distribution",
                current_price=95,
                save_path=Path(tmp) / "test_dist.png",
            )
            assert Path(path).exists()
            assert Path(path).suffix == ".png"
            assert Path(path).stat().st_size > 0

    def test_chart_without_current_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(0)
            data = rng.normal(50, 5, size=5000)
            path = generate_distribution_chart(
                data,
                title="No Price Line",
                save_path=Path(tmp) / "no_price.png",
            )
            assert Path(path).exists()


# ---------------------------------------------------------------------------
# generate_pe_band_chart
# ---------------------------------------------------------------------------

class TestGeneratePeBandChart:
    def _sample_pe_band(self):
        dates = pd.date_range("2021-01-01", periods=260, freq="W")
        pe_series = np.linspace(25, 35, 260)
        return {
            "dates": dates,
            "pe_series": pe_series,
            "bands": {
                "p10": 20.0,
                "p25": 25.0,
                "p50": 30.0,
                "p75": 35.0,
                "p90": 40.0,
            },
            "current_pe": 32.0,
            "current_percentile": 65.0,
            "forward_eps": 5.0,
        }

    def test_produces_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_pe_band_chart(
                self._sample_pe_band(),
                title="Test PE Band",
                save_path=Path(tmp) / "pe_band.png",
            )
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0


# ---------------------------------------------------------------------------
# generate_report_html
# ---------------------------------------------------------------------------

class TestGenerateReportHtml:
    def test_step0_configured_before_core_steps(self):
        assert STEP_CONFIG[0]["key"] == "step0"
        assert STEP_CONFIG[0]["file"] == "step0_quick_triage.md"

    def test_embeds_step0_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "TEST"
            ws.mkdir()
            (ws / "step0_quick_triage.md").write_text(
                "# Step 0: Quick Triage - TEST\n\n"
                "**Decision: FULL_RESEARCH**\n",
                encoding="utf-8",
            )
            (ws / "step1_business_analysis.md").write_text(
                "# Step 1: TEST\n\nBusiness content.\n",
                encoding="utf-8",
            )

            path = generate_report_html(ws, ticker="TEST")
            html = Path(path).read_text(encoding="utf-8")

            assert "Step 0: 快速筛选" in html
            assert "FULL_RESEARCH" in html


# ---------------------------------------------------------------------------
# _extract_summary_metrics
# ---------------------------------------------------------------------------

class TestExtractSummaryMetrics:
    def _create_workspace(self, tmp):
        """Create a minimal workspace with step files for extraction."""
        ws = Path(tmp) / "TEST"
        ws.mkdir()

        # Step 6 with price and target
        (ws / "step6_monte_carlo_simulation.md").write_text(
            "当前股价：150.00\n"
            "Forward PE: 30.0x\n"
            "### T+2\n"
            "| 指标 | 数值 |\n"
            "|:--|--:|\n"
            "| P50 目标价 | **200.00** |\n"
        )

        # Step 7 with RRR
        (ws / "step7_rrr_strategy.md").write_text(
            "## RRR Assessment\n"
            "**RRR = 2.5** (based on T+2 Forward)\n"
        )

        # Step 2 with moat
        (ws / "step2_competitive_moat.md").write_text(
            "### Moat Rating\n"
            "Wide, Widening\n"
        )

        # Edge score JSON
        (ws / "edge_score.json").write_text(json.dumps([{
            "composite": 6.5,
            "composite_grade": "B — Meaningful edge",
        }]))

        # Step 9 with decision
        (ws / "step9_research_director_review.md").write_text(
            "## Investment Committee\n"
            "**Decision: Buy**\n"
        )

        return ws

    def test_extracts_all_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_workspace(tmp)
            metrics = _extract_summary_metrics(str(ws), "TEST")
            assert metrics["current_price"] == "150.00"
            assert metrics["target_price"] == "200.00"
            assert metrics["rrr"] == "2.5"
            assert metrics["moat"] is not None
            assert "Wide" in metrics["moat"]
            assert metrics["edge_score"] == "6.5"
            assert metrics["decision"] == "Buy"

    def test_handles_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "EMPTY"
            ws.mkdir()
            metrics = _extract_summary_metrics(str(ws), "EMPTY")
            # Should not crash, just return defaults
            assert isinstance(metrics, dict)
            assert metrics.get("current_price") is None or metrics.get("current_price") == "-"

    def test_summary_metrics_json_overrides_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "SUMMARY_OVERRIDE"
            ws.mkdir()
            (ws / "summary_metrics.json").write_text(json.dumps({
                "current_price": "10.00",
                "target_price": "15.00",
                "rrr": "2.20",
            }))
            (ws / "step6_monte_carlo_simulation.md").write_text(
                "当前股价：999.00\n| P50 目标价 | 888.00 |\n"
            )
            metrics = _extract_summary_metrics(str(ws), "SUMMARY_OVERRIDE")
            assert metrics["current_price"] == "10.00"
            assert metrics["target_price"] == "15.00"
            assert metrics["rrr"] == "2.20"

    def test_unlabeled_p50_row_not_used_as_target_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "P50_UNLABELED"
            ws.mkdir()
            (ws / "step6_monte_carlo_simulation.md").write_text(
                "当前股价：100.00\n"
                "| **P50** | **2.50** |\n"  # EPS-like row, not target price
            )
            metrics = _extract_summary_metrics(str(ws), "P50_UNLABELED")
            assert metrics["current_price"] == "100.00"
            assert "target_price" not in metrics

    def test_extracts_forward_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "PE_TEST"
            ws.mkdir()
            (ws / "step6_monte_carlo_simulation.md").write_text(
                "Forward PE: 25.5x\n当前股价：100"
            )
            metrics = _extract_summary_metrics(str(ws), "PE_TEST")
            assert metrics.get("forward_pe") is not None

    def test_extracts_forward_pe_from_calculated_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "PE_CALC"
            ws.mkdir()
            (ws / "calculated_valuation.json").write_text(json.dumps({
                "source": "calculated",
                "pe_forward": {"pe": 18.25, "valid": True},
            }))
            metrics = _extract_summary_metrics(str(ws), "PE_CALC")
            assert metrics["forward_pe"] == "18.2x"


# ---------------------------------------------------------------------------
# JSON-first metric extraction (new tests)
# ---------------------------------------------------------------------------

def _make_minimal_png():
    """Create a minimal valid 1x1 PNG."""
    import struct, zlib
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    raw = b"\x00\x00\x00\x00"
    compressed = zlib.compress(raw)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    return header + struct.pack(">I", 13) + b"IHDR" + ihdr + ihdr_crc + idat + iend


class TestJsonFirstExtraction:
    """Test that _extract_summary_metrics reads JSON files first, before regex."""

    def _create_json_workspace(self, tmp, schema="A"):
        """Create workspace with structured JSON files (no step markdown)."""
        ws = Path(tmp) / "JSON_TEST"
        ws.mkdir()

        if schema == "A":
            # Schema A (600707-style): p50_target, current_price, rrr at top level
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "current_price": 9.88,
                "p50_target": 8.34,
                "rrr": 1.53,
                "kelly_f": 0.149,
                "kelly_half": 0.074,
                "kelly_after_edge": 0.037,
                "p50_eps": 0.387,
                "upside_prob": 0.43,
                "downside_prob": 0.57,
            }))
        elif schema == "B":
            # Schema B (600036-style): target_price_percentiles
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "current_price": 35.0,
                "target_price_percentiles": {"50": 42.0, "10": 25.0, "90": 55.0},
                "mean_target_price": 41.5,
            }))
        elif schema == "C":
            # Schema C (09992-style): target_price dict, no current_price
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "target_price": {"50": 8.5, "10": 4.0, "90": 15.0},
                "rrr": 2.1,
                "kelly_half_pct": 5.0,
            }))
        elif schema == "D":
            # Schema D (300685-style): singular filename, nested rrr
            (ws / "monte_carlo_result.json").write_text(json.dumps({
                "current_price": 50.0,
                "target_price_percentiles": {"50": 65.0},
                "rrr": {"rrr": 1.8, "kelly_half": 6.0},
            }))

        # pe_band_data.json
        (ws / "pe_band_data.json").write_text(json.dumps({
            "current_forward_pe": 25.5,
            "current_percentile": 98.0,
            "forward_eps": 0.387,
            "bands": {"p10": 6.8, "p25": 10.2, "p50": 16.5, "p75": 22.1, "p90": 28.5},
        }))

        # edge_score.json (list format)
        (ws / "edge_score.json").write_text(json.dumps([{
            "raw_scores": {"analytical": 6, "informational": 4},
            "composite": 5.55,
            "composite_grade": "B — Meaningful edge",
        }]))

        # Minimal step files (for moat/decision only)
        (ws / "step2_competitive_moat.md").write_text("Narrow Moat, Widening\n")
        (ws / "step9_research_director_review.md").write_text("Decision: Hold / Wait\n")

        return ws

    def test_schema_a_json_takes_priority(self):
        """Schema A: p50_target + current_price + rrr from JSON, not regex."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_json_workspace(tmp, schema="A")
            # Also create Step 6 markdown with wrong values to prove JSON wins
            (ws / "step6_monte_carlo_simulation.md").write_text(
                "当前股价：999.00\nForward PE: 99.0x\n"
            )
            metrics = _extract_summary_metrics(str(ws), "JSON_TEST")
            assert metrics["current_price"] == "9.88"   # from JSON, not 999
            assert metrics["target_price"] == "8.34"     # from JSON p50_target
            assert metrics["rrr"] == "1.53"              # from JSON rrr
            assert metrics["forward_pe"] == "25.5x"      # from pe_band_data.json

    def test_schema_b_target_price_percentiles(self):
        """Schema B: target_price_percentiles.50."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_json_workspace(tmp, schema="B")
            metrics = _extract_summary_metrics(str(ws), "JSON_TEST")
            assert metrics["current_price"] == "35.0"
            assert metrics["target_price"] == "42.00"

    def test_schema_c_target_price_dict(self):
        """Schema C: target_price dict, no current_price in MC JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_json_workspace(tmp, schema="C")
            metrics = _extract_summary_metrics(str(ws), "JSON_TEST")
            assert metrics["target_price"] == "8.50"
            assert metrics["rrr"] == "2.10"

    def test_schema_d_singular_filename(self):
        """Schema D: monte_carlo_result.json (singular), nested rrr."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_json_workspace(tmp, schema="D")
            metrics = _extract_summary_metrics(str(ws), "JSON_TEST")
            assert metrics["current_price"] == "50.0"
            assert metrics["target_price"] == "65.00"
            assert metrics["rrr"] == "1.80"

    def test_no_json_falls_back_to_regex(self):
        """When no JSON files exist, regex extraction still works."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "REGEX_TEST"
            ws.mkdir()
            (ws / "step6_monte_carlo_simulation.md").write_text(
                "当前股价：150.00\nForward PE: 30.0x\n"
            )
            (ws / "step7_rrr_strategy.md").write_text("RRR = 2.5\n")
            (ws / "step2_competitive_moat.md").write_text("Wide, Widening\n")
            (ws / "step9_research_director_review.md").write_text("Buy\n")

            metrics = _extract_summary_metrics(str(ws), "REGEX_TEST")
            assert metrics["current_price"] == "150.00"
            assert metrics["rrr"] == "2.5"
            assert "Wide" in metrics.get("moat", "")

    def test_pe_band_json_overrides_calculated_valuation(self):
        """pe_band_data.json forward_pe takes priority over calculated_valuation.json."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "PE_PRIORITY"
            ws.mkdir()
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "current_price": 10.0, "p50_target": 12.0, "rrr": 2.0,
            }))
            (ws / "calculated_valuation.json").write_text(json.dumps({
                "pe_trailing": {"pe": 50.0, "price": 10.0},
            }))
            (ws / "pe_band_data.json").write_text(json.dumps({
                "current_forward_pe": 22.5,
                "current_percentile": 75.0,
            }))
            (ws / "step2_competitive_moat.md").write_text("")
            (ws / "step9_research_director_review.md").write_text("")

            metrics = _extract_summary_metrics(str(ws), "PE_PRIORITY")
            assert metrics["forward_pe"] == "22.5x"  # from pe_band_data, not calculated_val

    def test_edge_score_from_thesis_json_fallback(self):
        """edge_score falls back to thesis.json if edge_score.json missing."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "EDGE_FB"
            ws.mkdir()
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "current_price": 5.0, "p50_target": 7.0, "rrr": 1.5,
            }))
            (ws / "thesis.json").write_text(json.dumps({
                "edge_score": 7.0,
                "edge_grade": "A",
            }))
            (ws / "step2_competitive_moat.md").write_text("")
            (ws / "step9_research_director_review.md").write_text("")

            metrics = _extract_summary_metrics(str(ws), "EDGE_FB")
            assert metrics["edge_score"] == "7.0"
            assert metrics["edge_grade"] == "A"

    def test_edge_score_from_thesis_history(self):
        """edge_score from thesis.json history array (latest revision)."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "EDGE_HIST"
            ws.mkdir()
            (ws / "monte_carlo_results.json").write_text(json.dumps({
                "current_price": 5.0, "p50_target": 7.0, "rrr": 1.5,
            }))
            (ws / "thesis.json").write_text(json.dumps({
                "history": [
                    {"edge_score": 5.0, "edge_grade": "C"},
                    {"edge_score": 6.5, "edge_grade": "B"},
                ]
            }))
            (ws / "step2_competitive_moat.md").write_text("")
            (ws / "step9_research_director_review.md").write_text("")

            metrics = _extract_summary_metrics(str(ws), "EDGE_HIST")
            assert metrics["edge_score"] == "6.5"
            assert metrics["edge_grade"] == "B"


class TestReadJsonSafe:
    def test_reads_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "test.json").write_text('{"a": 1}')
            result = _read_json_safe(ws, "test.json")
            assert result == {"a": 1}

    def test_returns_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _read_json_safe(Path(tmp), "nonexistent.json")
            assert result is None

    def test_returns_none_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "bad.json").write_text("not json at all")
            result = _read_json_safe(ws, "bad.json")
            assert result is None


class TestAutoEmbedImages:
    def test_embeds_unreferenced_pngs(self):
        """PNGs not referenced in step HTML should be auto-embedded."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            png_data = _make_minimal_png()

            # Create a PNG that is NOT referenced in any markdown
            (ws / "monte_carlo_distribution.png").write_bytes(png_data)

            sections_html = (
                '<div id="step6" class="section-card">'
                '<div class="section-header"><h2>Step 6</h2></div>'
                '<div class="section-body"><p>Some content</p>'
                '<!-- AUTO_IMAGES:step6 --></div></div>'
            )

            result = _auto_embed_workspace_images(ws, sections_html)
            assert "data:image/png;base64," in result
            assert "Monte Carlo Distribution" in result

    def test_skips_already_embedded_pngs(self):
        """PNGs already referenced in HTML should NOT be double-embedded."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            png_data = _make_minimal_png()
            (ws / "monte_carlo_distribution.png").write_bytes(png_data)

            # Simulate already-embedded chart (filename stem present in HTML)
            sections_html = (
                '<div id="step6" class="section-card">'
                '<div class="section-body">'
                '<p>monte_carlo_distribution already here</p>'
                '</div></div>'
            )

            result = _auto_embed_workspace_images(ws, sections_html)
            # Should not add a second chart-container
            assert result.count("chart-container") == 0

    def test_skips_png_embedded_from_markdown_image(self):
        """A markdown image embed should not be duplicated by auto-embed."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            png_data = _make_minimal_png()
            (ws / "monte_carlo_distribution.png").write_bytes(png_data)

            body = md_to_html("![Distribution](monte_carlo_distribution.png)", workspace_dir=str(ws))
            sections_html = (
                '<div id="step6" class="section-card">'
                '<div class="section-header"><h2>Step 6</h2></div>'
                f'<div class="section-body">{body}</div></div>'
            )

            result = _auto_embed_workspace_images(ws, sections_html)
            assert result.count("chart-container") == 1

    def test_unknown_pngs_go_to_appendix(self):
        """PNGs not in _IMAGE_STEP_MAP should go to Charts & Exhibits appendix."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            png_data = _make_minimal_png()
            (ws / "custom_chart.png").write_bytes(png_data)

            sections_html = (
                '<div id="step4" class="section-card">'
                '<div class="section-body"><p>Content</p></div></div>'
            )

            result = _auto_embed_workspace_images(ws, sections_html)
            assert "charts-appendix" in result
            assert "Charts & Exhibits" in result
            assert "Custom Chart" in result

    def test_no_pngs_no_change(self):
        """Workspace with no PNGs should return HTML unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            sections_html = '<div id="step4"><p>No charts</p></div>'
            result = _auto_embed_workspace_images(ws, sections_html)
            assert result == sections_html

    def test_embed_image_as_base64_missing_file(self):
        """_embed_image_as_base64 returns empty string for missing file."""
        result = _embed_image_as_base64(Path("/nonexistent/chart.png"), "Test")
        assert result == ""

    def test_embed_image_as_base64_valid_file(self):
        """_embed_image_as_base64 produces valid HTML with base64 data."""
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "chart.png"
            img_path.write_bytes(_make_minimal_png())
            result = _embed_image_as_base64(img_path, "Test Chart")
            assert "data:image/png;base64," in result
            assert "Test Chart" in result
            assert "chart-container" in result


# ---------------------------------------------------------------------------
# Regression: nested-dict format support (09992.HK bug fix)
# ---------------------------------------------------------------------------

class TestNestedDictFormat:
    """Tests for nested-dict assumption_matrix / segment_revenues format.

    Regression tests for: P50 target showing 6.4 instead of 248.5,
    and 'str' object has no attribute 'get' in forecast model.
    """

    def _create_09992_workspace(self, tmp):
        """Create workspace mimicking 09992.HK nested-dict format."""
        ws = Path(tmp) / "09992"
        ws.mkdir()

        # step4_structured_assumptions.json — nested dict format
        (ws / "step4_structured_assumptions.json").write_text(json.dumps({
            "ticker": "09992.HK",
            "base_year": "FY2025",
            "forward_year": "T1",
            "hkd_cny": 0.92,
            "shares_outstanding": 1331723150,
            "current_price_hkd": 176.4,
            "current_price_cny": 162.29,
            "base_revenue_cny_m": 37120,
            "financial_model_inputs": {
                "p50_target_hkd": 248.5,
                "p50_eps_cny": 11.43,
                "shares_outstanding": 1331723150,
                "diluted_shares": 1331723150,
                "hkd_cny": 0.92,
                "cash": 5000,
                "debt": 1000,
                "equity": 22000,
                "nwc_ratio": 0.10,
                "ppe_ratio": 0.20,
                "other_assets_ratio": 0.05,
                "ap_ratio": 0.06,
                "dividend_payout": 0.0,
                "da_ratio": 0.04,
                "capex_ratio": 0.06,
                "interest_rate_on_debt": 0.00,
                "interest_rate_on_cash": 0.00,
                "annual_share_dilution_pct": 0.0,
            },
            "assumption_matrix": {
                "T1_FY2026E": {
                    "revenue_growth": {"p10": 0.08, "p30": 0.15, "p50": 0.22, "p70": 0.30, "p90": 0.40},
                    "gross_margin": {"p10": 0.55, "p50": 0.65, "p90": 0.75},
                    "opex_ratio": {"p10": 0.10, "p50": 0.18, "p90": 0.25},
                    "tax_rate": {"p10": 0.10, "p50": 0.15, "p90": 0.20},
                    "pe_multiple": {"p10": 15, "p30": 18, "p50": 22, "p70": 28, "p90": 35},
                    "overseas_growth": {"p10": 0.20, "p30": 0.30, "p50": 0.45, "p70": 0.60, "p90": 0.80},
                },
                "T2_FY2027E": {
                    "revenue_growth": {"p10": 0.05, "p30": 0.12, "p50": 0.18, "p70": 0.25, "p90": 0.35},
                    "gross_margin": {"p50": 0.64},
                    "opex_ratio": {"p50": 0.17},
                    "tax_rate": {"p50": 0.15},
                    "pe_multiple": {"p10": 13, "p30": 16, "p50": 20, "p70": 26, "p90": 32},
                },
                "T3_FY2028E": {
                    "revenue_growth": {"p10": 0.03, "p30": 0.08, "p50": 0.12, "p70": 0.18, "p90": 0.25},
                    "gross_margin": {"p50": 0.63},
                    "opex_ratio": {"p50": 0.16},
                    "tax_rate": {"p50": 0.15},
                    "pe_multiple": {"p10": 12, "p30": 15, "p50": 18, "p70": 24, "p90": 30},
                },
            },
            "segment_revenues": {
                "product_level": {
                    "Plush": {"base": 15000, "p50": 18300, "p50_growth": 0.22},
                    "Figurines": {"base": 10000, "p50": 12000, "p50_growth": 0.20},
                    "MEGA": {"base": 8000, "p50": 11000, "p50_growth": 0.375},
                    "Derivatives": {"base": 4120, "p50": 5000, "p50_growth": 0.213},
                }
            },
            "valuation_source": "all self-calculated from raw financial data",
            "assumption_consistency": {
                "revenue_vs_segments": "consistent",
            },
            "bridge_analysis": {
                "base_total": 37120,
                "p50_total": 46300,
                "delta": 9180,
            },
            "growth_drivers": [],
            "margin_derivation": {"method": "historical_average"},
            "contrarian_checks": [],
        }))

        # Step 6 markdown with a line that used to confuse regex, plus Step 4 for validation.
        step4_content = (
            "# Step 6: Monte Carlo Simulation\n\n"
            "当前股价：176.4 HKD\n\n"
            "### Monte Carlo Results\n"
            "| Scenario | PE | EPS | Target (HKD) |\n"
            "|:---------|:---|:----|:-------------|\n"
            "| P50 Target | 265.4 HKD | **248.5 HKD** | -6.4% |\n"
        )
        (ws / "step6_monte_carlo_simulation.md").write_text(step4_content)
        (ws / "step4_assumption_research.md").write_text(step4_content)
        (ws / "_reviewed_assumptions.json").write_text(json.dumps({
            "reviewed_at": "2026-01-01",
            "assumptions": {
                "rev_growth": {"p10": 0.08, "p50": 0.22, "p90": 0.40},
                "gross_margin": {"p10": 0.55, "p50": 0.65, "p90": 0.75},
                "opex_ratio": {"p10": 0.10, "p50": 0.18, "p90": 0.25},
                "tax_rate": {"p10": 0.10, "p50": 0.15, "p90": 0.20},
                "pe": {"p10": 15, "p50": 22, "p90": 35},
            },
        }), encoding="utf-8")

        # Step 7
        (ws / "step7_rrr_strategy.md").write_text(
            "## RRR Assessment\n**RRR = 3.2**\n"
            "P50 Target | 248.5 HKD\n"
        )

        # Step 2
        (ws / "step2_competitive_moat.md").write_text("Wide Moat, Widening\n")

        # Step 9
        (ws / "step9_research_director_review.md").write_text("Decision: Buy\n")

        return ws

    def test_target_price_from_structured_assumptions_json(self):
        """P50 target must come from step4_structured_assumptions.json, not regex.

        Regression: the regex used to match -6.4% from the table and return 6.4.
        The JSON has p50_target_hkd: 248.5 — this MUST win.
        """
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_09992_workspace(tmp)
            metrics = _extract_summary_metrics(str(ws), "09992")

            assert metrics["target_price"] is not None
            tp = float(metrics["target_price"])
            assert tp > 100, f"Target price {tp} looks wrong — should be ~248.5, not 6.4"
            assert abs(tp - 248.5) < 1.0, f"Expected ~248.5, got {tp}"

    def test_regex_does_not_pick_percentage_as_target(self):
        """The -6.4% in the markdown table must NOT become the target price."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_09992_workspace(tmp)
            # Remove JSON to force regex fallback
            (ws / "step4_structured_assumptions.json").unlink()
            # Also remove any MC JSON
            for f in ws.glob("monte_carlo_result*.json"):
                f.unlink()

            metrics = _extract_summary_metrics(str(ws), "09992")

            # If target_price is extracted from regex, it must NOT be 6.4
            tp = metrics.get("target_price")
            if tp is not None:
                tp_val = float(tp)
                assert tp_val != 6.4, "Regex picked 6.4 from -6.4% — regression!"
                assert tp_val >= 100, f"Target {tp_val} too low for 176.4 current price"

    def test_financial_model_handles_nested_dict(self):
        """build_financial_model must not crash on nested-dict assumption_matrix.

        Regression: 'str' object has no attribute 'get'
        """
        from src.analysis.financial_model import build_financial_model

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_09992_workspace(tmp)
            # Should NOT raise AttributeError
            model = build_financial_model(str(ws))
            assert isinstance(model, dict)
            assert "statements" in model or "segments" in model

    def test_step4_validate_handles_nested_dict(self):
        """validate_step4 must not crash on nested-dict assumption_matrix.

        Regression: 'str' object has no attribute 'get' in _validate_assumption_matrix
        """
        from src.analysis.step4_validate import validate_step4

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_09992_workspace(tmp)
            # Should NOT raise AttributeError
            result = validate_step4(str(ws / "step4_assumption_research.md"))
            assert isinstance(result, dict)
            assert "passed" in result
            assert "checks" in result

    def test_step4_validate_handles_dict_valuation_source(self):
        """valuation_source can be a string — must not crash on .get()."""
        from src.analysis.step4_validate import validate_step4

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._create_09992_workspace(tmp)
            result = validate_step4(str(ws / "step4_assumption_research.md"))
            # Find the valuation_ratios_calculated check
            val_checks = [c for c in result["checks"]
                          if c["check"] == "valuation_ratios_calculated"]
            assert len(val_checks) == 1
            assert val_checks[0]["status"] == "PASS"

    def test_report_generates_mc_chart_from_p_keys_decimal_ratios(self):
        """Auto chart generation must support p10/p50 keys and decimal ratios."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "CHART"
            ws.mkdir()
            (ws / "step1_business_analysis.md").write_text("# Step 1: CHART\n", encoding="utf-8")
            (ws / "step4_structured_assumptions.json").write_text(json.dumps({
                "base_revenue_cny_m": 10000,
                "current_price_hkd": 100,
                "financial_model_inputs": {
                    "shares_outstanding": 100000000,
                    "diluted_shares": 100000000,
                    "hkd_cny": 1.0,
                    "cash": 5000,
                    "debt": 1000,
                    "equity": 22000,
                    "nwc_ratio": 0.10,
                    "ppe_ratio": 0.20,
                    "other_assets_ratio": 0.05,
                    "ap_ratio": 0.06,
                    "dividend_payout": 0.0,
                    "da_ratio": 0.04,
                    "capex_ratio": 0.06,
                    "interest_rate_on_debt": 0.00,
                    "interest_rate_on_cash": 0.00,
                    "annual_share_dilution_pct": 0.0,
                },
                "assumption_matrix": {
                    "T1_FY2026E": {
                        "revenue_growth": {"p10": 0.05, "p30": 0.10, "p50": 0.15, "p70": 0.20, "p90": 0.25},
                        "npm": {"p10": 0.10, "p30": 0.12, "p50": 0.15, "p70": 0.18, "p90": 0.20},
                        "pe_multiple": {"p10": 10, "p30": 12, "p50": 15, "p70": 18, "p90": 22},
                    },
                },
            }), encoding="utf-8")

            generate_report_html(ws, ticker="CHART")

            assert (ws / "monte_carlo_distribution.png").exists()


class TestHtmlReportIntegrity:
    """End-to-end HTML report validation tests.

    These verify that a generated HTML report meets basic integrity standards.
    Run as a regression suite after any report generator changes.
    """

    def _minimal_workspace(self, tmp, ticker="TEST"):
        """Create a workspace with just enough files to generate a report."""
        ws = Path(tmp) / ticker
        ws.mkdir()

        # Step 1
        (ws / "step1_business_analysis.md").write_text(
            "# Step 1: Business Analysis\n\nTest business description.\n"
        )
        # Step 6 with data
        (ws / "step6_monte_carlo_simulation.md").write_text(
            "# Step 6: Monte Carlo Simulation\n\n"
            "当前股价：100.00\nForward PE: 20.0x\n"
            "### Monte Carlo Results\n"
            "| P50 Target | 150.00 |\n"
        )
        # Step 7
        (ws / "step7_rrr_strategy.md").write_text(
            "## RRR Assessment\n**RRR = 2.5**\n"
        )
        # Step 2
        (ws / "step2_competitive_moat.md").write_text("Wide Moat\n")
        # Step 9
        (ws / "step9_research_director_review.md").write_text("Decision: Buy\n")

        return ws

    def test_report_html_no_crash_errors(self):
        """Generated HTML must not contain Python crash error messages."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._minimal_workspace(tmp)
            path = generate_report_html(ws, ticker="TEST")
            html = Path(path).read_text(encoding="utf-8")

            # These patterns indicate unhandled exceptions
            forbidden = [
                "Traceback (most recent",
                "AttributeError",
                "TypeError",
                "KeyError",
                "IndexError",
                "object has no attribute",
                "not subscriptable",
            ]
            for pattern in forbidden:
                assert pattern not in html, f"HTML contains crash error: {pattern}"

    def test_report_html_has_valid_structure(self):
        """HTML must have basic structural elements."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._minimal_workspace(tmp)
            path = generate_report_html(ws, ticker="TEST")
            html = Path(path).read_text(encoding="utf-8")

            assert "<!DOCTYPE html>" in html
            assert "<html" in html
            assert "</html>" in html
            assert "<head>" in html
            assert "<body" in html

    def test_report_html_no_broken_target_price(self):
        """If current price is 100, target should not be <10 or >10000."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._minimal_workspace(tmp)
            metrics = _extract_summary_metrics(str(ws), "TEST")

            cp = float(metrics.get("current_price", 0))
            tp = float(metrics.get("target_price", 0))
            if cp > 0 and tp > 0:
                ratio = tp / cp
                assert 0.2 <= ratio <= 10.0, (
                    f"Target/Current ratio {ratio:.2f} is suspicious — "
                    f"target={tp}, current={cp}"
                )

    def test_report_summary_card_has_key_metrics(self):
        """Summary card must show at least current_price and decision."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._minimal_workspace(tmp)
            path = generate_report_html(ws, ticker="TEST")
            html = Path(path).read_text(encoding="utf-8")

            assert "100.00" in html  # current price
            assert "Buy" in html     # decision
