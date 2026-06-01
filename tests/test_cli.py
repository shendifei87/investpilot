"""Tests for src.cli — CLI entry point.

Covers: detect, analyze, thesis, catalyst, knowledge, report subcommands.
Fetch subcommand requires live Tushare API so is not tested here.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config.ticker_rules import detect_market, normalize_ticker, get_tushare_code


# ---------------------------------------------------------------------------
# detect_market / normalize_ticker / get_tushare_code
# (core routing logic used by CLI detect)
# ---------------------------------------------------------------------------

class TestDetectMarket:
    @pytest.mark.parametrize("ticker,expected", [
        ("AAPL", "US"),
        ("TSLA", "US"),
        ("NVDA", "US"),
        ("0700.HK", "HK"),
        ("9988.HK", "HK"),
        ("600519", "ASHARE"),
        ("000001.SZ", "ASHARE"),
        ("601398.SS", "ASHARE"),
        ("688981", "ASHARE"),  # STAR market
    ])
    def test_market_detection(self, ticker, expected):
        assert detect_market(ticker) == expected


class TestNormalizeTicker:
    def test_a_share_6digit(self):
        normalized, market = normalize_ticker("600519")
        assert normalized == "600519.SS"  # yfinance convention for Shanghai
        assert market == "ASHARE"

    def test_a_share_sz(self):
        normalized, market = normalize_ticker("000001.SZ")
        assert normalized == "000001.SZ"

    def test_hk_stock(self):
        normalized, market = normalize_ticker("0700.HK")
        assert normalized == "0700.HK"
        assert market == "HK"

    def test_us_stock(self):
        normalized, market = normalize_ticker("AAPL")
        assert normalized == "AAPL"
        assert market == "US"

    def test_star_market(self):
        normalized, _ = normalize_ticker("688981")
        assert normalized == "688981.SS"  # yfinance convention for Shanghai


class TestGetTushareCode:
    def test_a_share_shanghai(self):
        assert get_tushare_code("600519.SH", "ASHARE") == "600519.SH"

    def test_a_share_shenzhen(self):
        assert get_tushare_code("000001.SZ", "ASHARE") == "000001.SZ"

    def test_hk_stock(self):
        assert get_tushare_code("0700.HK", "HK") == "00700"

    def test_hk_stock_5digit(self):
        assert get_tushare_code("09992.HK", "HK") == "09992"

    def test_us_stock(self):
        assert get_tushare_code("AAPL", "US") == "AAPL"

    def test_ss_suffix_converted_to_sh(self):
        """yfinance .SS suffix should become Tushare .SH suffix."""
        assert get_tushare_code("601398.SS", "ASHARE") == "601398.SH"


# ---------------------------------------------------------------------------
# CLI cmd_detect
# ---------------------------------------------------------------------------

class TestCmdDetect:
    def test_detect_outputs_json(self, capsys):
        args = MagicMock()
        args.ticker = "600519"
        from src.cli import cmd_detect
        cmd_detect(args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["market"] == "ASHARE"
        assert result["normalized"] == "600519.SS"  # yfinance convention

    def test_detect_us_ticker(self, capsys):
        args = MagicMock()
        args.ticker = "AAPL"
        from src.cli import cmd_detect
        cmd_detect(args)
        result = json.loads(capsys.readouterr().out)
        assert result["market"] == "US"

    def test_detect_hk_ticker(self, capsys):
        args = MagicMock()
        args.ticker = "0700.HK"
        from src.cli import cmd_detect
        cmd_detect(args)
        result = json.loads(capsys.readouterr().out)
        assert result["market"] == "HK"


# ---------------------------------------------------------------------------
# CLI cmd_analyze (with mocked data)
# ---------------------------------------------------------------------------

class TestCmdAnalyze:
    def test_analyze_loads_price_and_computes_indicators(self, tmp_path):
        """Verify cmd_analyze reads price CSV and runs technical analysis."""
        import pandas as pd
        import numpy as np

        ws = tmp_path / "TEST_WS"
        ws.mkdir()

        # Create a sample price CSV
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        prices = pd.DataFrame({
            "Close": np.cumsum(np.random.randn(100)) + 100,
            "Open": np.cumsum(np.random.randn(100)) + 100,
            "High": np.cumsum(np.random.randn(100)) + 101,
            "Low": np.cumsum(np.random.randn(100)) + 99,
        }, index=dates)
        prices.to_csv(ws / "price_history.csv")

        args = MagicMock()
        args.ticker = "TEST"
        args.input = str(ws)
        args.output = None

        from src.cli import cmd_analyze
        with patch("src.cli.WORKSPACES_DIR", tmp_path):
            cmd_analyze(args)

        output_dir = ws / "analysis"
        assert (output_dir / "technical_indicators.csv").exists()


# ---------------------------------------------------------------------------
# CLI cmd_thesis
# ---------------------------------------------------------------------------

class TestCmdThesis:
    def _make_args(self, action, **kwargs):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = action
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def _patch_ws(self, tmp_path):
        """Return context managers patching WORKSPACES_DIR for thesis + catalyst."""
        return (
            patch("src.cli.WORKSPACES_DIR", tmp_path / "workspaces"),
            patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"),
        )

    def _init_ws(self, tmp_path):
        (tmp_path / "workspaces" / "TEST").mkdir(parents=True, exist_ok=True)

    def test_thesis_create(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args("create", thesis="Test thesis: undervalued", hold_months=12)
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_thesis
            cmd_thesis(args)
        assert "Thesis created" in capsys.readouterr().out

    def test_thesis_snapshot(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.thesis_tracker import ThesisTracker
            tracker = ThesisTracker("TEST")
            tracker.create("Snapshot test thesis")

        args = self._make_args("snapshot")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_thesis
            cmd_thesis(args)
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "open"

    def test_thesis_brief(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.thesis_tracker import ThesisTracker
            tracker = ThesisTracker("TEST")
            tracker.create("Brief test thesis")

        args = self._make_args("brief")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_thesis
            cmd_thesis(args)
        assert "Brief test thesis" in capsys.readouterr().out

    def test_thesis_add_hypothesis(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.thesis_tracker import ThesisTracker
            tracker = ThesisTracker("TEST")
            tracker.create("Hypothesis test")

        args = self._make_args(
            "add-hypothesis",
            description="Revenue growth >20%",
            date="2026-07-15",
            impact="high",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_thesis
            cmd_thesis(args)
        assert "Hypothesis added" in capsys.readouterr().out

    def test_thesis_close(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.thesis_tracker import ThesisTracker
            tracker = ThesisTracker("TEST")
            tracker.create("Close test")

        args = self._make_args("close", status="closed_won", reason="Target reached")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_thesis
            cmd_thesis(args)
        assert "closed" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# CLI cmd_catalyst
# ---------------------------------------------------------------------------

class TestCmdCatalyst:
    def _make_args(self, action, **kwargs):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = action
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def _patch_ws(self, tmp_path):
        return (
            patch("src.cli.WORKSPACES_DIR", tmp_path / "workspaces"),
            patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"),
        )

    def _init_ws(self, tmp_path):
        (tmp_path / "workspaces" / "TEST").mkdir(parents=True, exist_ok=True)

    def test_catalyst_add(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args("add", event="Q2 earnings", date="2026-07-15",
                               impact="high", direction="positive")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_catalyst
            cmd_catalyst(args)
        assert "Catalyst added" in capsys.readouterr().out

    def test_catalyst_list(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.catalyst_tracker import CatalystTracker
            tracker = CatalystTracker("TEST")
            tracker.add_catalyst("List event", "2099-01-01")

        args = self._make_args("list")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_catalyst
            cmd_catalyst(args)
        assert "List event" in capsys.readouterr().out

    def test_catalyst_decay(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args("decay")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_catalyst
            cmd_catalyst(args)
        result = json.loads(capsys.readouterr().out)
        assert "conviction_modifier" in result

    def test_catalyst_kill_switch_add(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args(
            "kill-switch",
            trigger=False,
            condition="Gross margin < 10%",
            severity="critical",
            evidence=None,
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_catalyst
            cmd_catalyst(args)
        assert "Kill switch added" in capsys.readouterr().out

    def test_catalyst_kill_switch_trigger(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.catalyst_tracker import CatalystTracker
            tracker = CatalystTracker("TEST")
            tracker.add_kill_switch("Margin drop")

        args = self._make_args(
            "kill-switch",
            trigger=True,
            condition="Margin drop",
            evidence="Q2 margin fell to 8%",
            severity=None,
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_catalyst
            cmd_catalyst(args)
        assert "triggered" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# CLI cmd_knowledge
# ---------------------------------------------------------------------------

class TestCmdKnowledge:
    def _make_args(self, action, **kwargs):
        args = MagicMock()
        args.action = action
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_knowledge_stats(self, tmp_path, capsys):
        args = self._make_args("stats")
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            from src.cli import cmd_knowledge
            cmd_knowledge(args)
        result = json.loads(capsys.readouterr().out)
        assert isinstance(result, dict)

    def test_knowledge_brief(self, tmp_path, capsys):
        args = self._make_args("brief", ticker="600519", industry="白酒", themes="")
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            from src.cli import cmd_knowledge
            cmd_knowledge(args)
        assert isinstance(capsys.readouterr().out, str)

    def test_knowledge_lesson(self, tmp_path, capsys):
        args = self._make_args(
            "lesson",
            lesson="High PE can compress suddenly on guidance miss",
            context="Growth stock trap",
            tickers="AAPL,NVDA",
        )
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            from src.cli import cmd_knowledge
            cmd_knowledge(args)
        assert "Lesson recorded" in capsys.readouterr().out



# ---------------------------------------------------------------------------
# CLI cmd_report (with mocked workspace)
# ---------------------------------------------------------------------------

class TestCmdReport:
    def test_report_subcommand_calls_generator(self, tmp_path):
        ws = tmp_path / "TEST"
        ws.mkdir()
        (ws / "step1_business_analysis.md").write_text("# Step 1\nContent")

        args = MagicMock()
        args.workspace = "TEST"
        args.ticker = "TEST"
        args.name = ""

        with patch("src.cli.WORKSPACES_DIR", tmp_path), \
             patch("src.report.generator.generate_report_html") as mock_gen:
            mock_gen.return_value = ws / "report.html"
            from src.cli import cmd_report
            cmd_report(args)
            mock_gen.assert_called_once()
