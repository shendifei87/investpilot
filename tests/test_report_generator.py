"""Tests for src.report.generator — report generation engine.

Covers: format helpers, md_to_html conversion, summary metric extraction,
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
    format_currency,
    format_pct,
    df_to_markdown,
    generate_distribution_chart,
    generate_pe_band_chart,
    md_to_html,
    _extract_summary_metrics,
)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

class TestFormatCurrency:
    def test_usd(self):
        assert "$" in format_currency(1234.56, "USD")

    def test_cny(self):
        assert "¥" in format_currency(10000, "CNY")

    def test_none_returns_na(self):
        assert format_currency(None) == "N/A"

    def test_nan_returns_na(self):
        assert format_currency(float("nan")) == "N/A"


class TestFormatPct:
    def test_positive(self):
        result = format_pct(0.1523)
        assert "15" in result

    def test_none_returns_na(self):
        assert format_pct(None) == "N/A"

    def test_nan_returns_na(self):
        assert format_pct(float("nan")) == "N/A"


class TestDfToMarkdown:
    def test_basic_dataframe(self):
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        md = df_to_markdown(df)
        assert "|" in md
        assert "A" in md
        assert "B" in md

    def test_max_rows_limit(self):
        df = pd.DataFrame({"X": range(100)})
        md = df_to_markdown(df, max_rows=5)
        # Should have header + separator + at most 5 data rows
        lines = [l for l in md.split("\n") if l.strip().startswith("|")]
        assert len(lines) <= 7  # header + sep + 5 rows

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        md = df_to_markdown(df)
        assert isinstance(md, str)


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
        return {
            "dates": dates,
            "close": np.linspace(100, 150, 260),
            "pe_p10": np.full(260, 20),
            "pe_p25": np.full(260, 25),
            "pe_p50": np.full(260, 30),
            "pe_p75": np.full(260, 35),
            "pe_p90": np.full(260, 40),
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
            "Forward PE (T+2): 30.0x\n"
            "### T+2\n"
            "| **P50** | **¥200.00** |\n"
        )

        # Step 5 with RRR
        (ws / "step5_rrr_strategy.md").write_text(
            "## RRR Assessment\n"
            "**RRR = 2.5** (based on T+2 Forward)\n"
        )

        # Step 2 with moat
        (ws / "step2_competitive_moat.md").write_text(
            "### Moat Rating\n"
            "**Wide** | Trend: Widening\n"
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
            assert metrics["current_price"] == 150.00
            assert metrics["target_price"] == 200.00
            assert metrics["rrr"] == 2.5
            assert metrics["moat"] is not None
            assert "Wide" in metrics["moat"]
            assert metrics["edge_score"] == 6.5
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
                "Forward PE (T+1): 25.5x\n当前股价：100"
            )
            metrics = _extract_summary_metrics(str(ws), "PE_TEST")
            assert metrics.get("forward_pe") is not None
