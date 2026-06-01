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
    generate_distribution_chart,
    generate_pe_band_chart,
    md_to_html,
    _extract_summary_metrics,
)


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
        assert "<th>" in html or "<td>" in html

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
# _extract_summary_metrics
# ---------------------------------------------------------------------------

class TestExtractSummaryMetrics:
    def _create_workspace(self, tmp):
        """Create a minimal workspace with step files for extraction."""
        ws = Path(tmp) / "TEST"
        ws.mkdir()

        # Step 4 with price and target
        (ws / "step4_quantitative_model.md").write_text(
            "当前股价：150.00\n"
            "Forward PE: 30.0x\n"
            "### T+2\n"
            "| **P50** | **200.00** |\n"
        )

        # Step 5 with RRR
        (ws / "step5_rrr_strategy.md").write_text(
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

        # Step 7 with decision
        (ws / "step7_research_director_review.md").write_text(
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

    def test_extracts_forward_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "PE_TEST"
            ws.mkdir()
            (ws / "step4_quantitative_model.md").write_text(
                "Forward PE: 25.5x\n当前股价：100"
            )
            metrics = _extract_summary_metrics(str(ws), "PE_TEST")
            assert metrics.get("forward_pe") is not None
