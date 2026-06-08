"""Tests for src.cli — CLI entry point.

Covers: detect, analyze, thesis, catalyst, knowledge, report subcommands.
Fetch subcommand requires live Tushare API so is not tested here.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import pandas as pd

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
        ("600584.SH", "ASHARE"),
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

    def test_a_share_sh_suffix(self):
        normalized, market = normalize_ticker("600584.SH")
        assert normalized == "600584.SH"
        assert market == "ASHARE"


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

    def test_sh_suffix_preserved_for_tushare(self):
        assert get_tushare_code("600584.SH", "ASHARE") == "600584.SH"


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


class TestAutoCalculateValuation:
    def test_handles_financials_dataframe_without_boolean_ambiguity(self, tmp_path):
        from src.cli import _auto_calculate_valuation
        from src.data.base import FetchResult

        dates = ["2025-12-31", "2024-12-31"]
        income = pd.DataFrame({
            "Total Revenue": [1000.0, 900.0],
            "Net Income": [100.0, 90.0],
        }, index=pd.to_datetime(dates))
        balance = pd.DataFrame({
            "Total Stockholder Equity": [500.0, 460.0],
            "Total Assets": [1000.0, 950.0],
        }, index=pd.to_datetime(dates))

        results = {
            "valuation": FetchResult(
                success=True,
                data={"current_price": 20.0, "shares_outstanding": 100.0, "eps_forward": 1.2},
            ),
            "financials": FetchResult(
                success=True,
                data={"financials": income, "balance_sheet": balance},
            ),
        }

        _auto_calculate_valuation(results, tmp_path)

        assert (tmp_path / "calculated_valuation.json").exists()
        data = json.loads((tmp_path / "calculated_valuation.json").read_text(encoding="utf-8"))
        assert data["source"] == "calculated"


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
# CLI cmd_consensus
# ---------------------------------------------------------------------------

class TestCmdConsensus:
    def _make_args(self, action, **kwargs):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = action
        defaults = {
            "source": None,
            "source_type": None,
            "as_of": None,
            "metrics_json": None,
            "rating_json": None,
            "target_price": None,
            "confidence": None,
            "notes": None,
            "metric": None,
            "period": None,
            "consensus": None,
            "our": None,
            "unit": None,
            "consensus_source": None,
            "our_source": None,
            "catalyst": None,
            "lower_is_better": False,
            "old": None,
            "new": None,
            "reason": None,
            "gap": None,
            "outcome": None,
            "actual": None,
            "status": None,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(args, k, v)
        return args

    def _patch_ws(self, tmp_path):
        return (
            patch("src.cli.WORKSPACES_DIR", tmp_path / "workspaces"),
            patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"),
        )

    def _init_ws(self, tmp_path):
        (tmp_path / "workspaces" / "TEST").mkdir(parents=True, exist_ok=True)

    def test_consensus_add_snapshot(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args(
            "add-snapshot",
            source="Broker A",
            metrics_json='{"eps": {"2026E": {"value": 2.0, "unit": "CNY/share"}}}',
            rating_json='{"buy": 5, "hold": 2, "sell": 0}',
            target_price=30,
            confidence="high",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_consensus
            cmd_consensus(args)
        out = capsys.readouterr().out
        assert "Consensus snapshot recorded" in out
        assert (tmp_path / "workspaces" / "TEST" / "consensus_snapshot.json").exists()

    def test_consensus_add_gap_and_brief(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        with self._patch_ws(tmp_path)[1]:
            from src.analysis.consensus_tracker import ConsensusTracker
            tracker = ConsensusTracker("TEST")
            tracker.record_snapshot("Broker A", {"eps": {"2026E": 2.0}})

        gap_args = self._make_args(
            "add-gap",
            metric="eps",
            period="2026E",
            consensus=2.0,
            our=2.4,
            catalyst="Q2 earnings",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_consensus
            cmd_consensus(gap_args)
        assert "Expectation gap recorded" in capsys.readouterr().out

        brief_args = self._make_args("brief")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_consensus
            cmd_consensus(brief_args)
        assert "Open Expectation Gaps" in capsys.readouterr().out

    def test_consensus_revision(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        args = self._make_args(
            "revise",
            metric="eps",
            period="2026E",
            old=1.0,
            new=1.2,
            source="Broker update",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_consensus
            cmd_consensus(args)
        assert "Consensus revision recorded" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI cmd_materials
# ---------------------------------------------------------------------------

class TestCmdMaterials:
    def _make_args(self, action, **kwargs):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = action
        defaults = {
            "focus": None,
            "file": None,
            "doc_type": None,
            "title": None,
            "issuer": None,
            "publish_date": None,
            "period": None,
            "source_path": None,
            "pages": None,
            "language": None,
            "document": None,
            "extract_type": None,
            "topic": None,
            "value": None,
            "evidence": None,
            "page": None,
            "confidence": None,
            "impact": None,
            "tags": None,
            "quote": None,
            "notes": None,
            "status": None,
            "method": None,
            "error": None,
            "max_attempts": None,
            "url": None,
            "source_kind": None,
            "complete_report": False,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(args, k, v)
        return args

    def _patch_ws(self, tmp_path):
        return (
            patch("src.cli.WORKSPACES_DIR", tmp_path / "workspaces"),
            patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"),
        )

    def _init_ws(self, tmp_path):
        (tmp_path / "workspaces" / "TEST").mkdir(parents=True, exist_ok=True)

    def test_materials_index(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        ws = tmp_path / "workspaces" / "TEST"
        (ws / "annual_report.pdf").write_bytes(b"%PDF fake")

        args = self._make_args("index")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(args)
        result = json.loads(capsys.readouterr().out)
        assert result["n_indexed"] == 1

    def test_materials_add_doc_extract_and_brief(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        add_doc_args = self._make_args(
            "add-doc",
            file="broker.pdf",
            doc_type="broker_report",
            title="Broker Initiation",
            pages=20,
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(add_doc_args)
        assert "Document recorded" in capsys.readouterr().out

        add_ext_args = self._make_args(
            "add-extract",
            document="broker.pdf",
            extract_type="broker_assumption",
            topic="2026E EPS",
            value="2.4",
            evidence="Model table",
            page="p.5",
            tags="step3,consensus",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(add_ext_args)
        assert "Extraction recorded" in capsys.readouterr().out

        brief_args = self._make_args("brief")
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(brief_args)
        assert "Broker Assumption" in capsys.readouterr().out

    def test_materials_read_attempt_and_web_fallback(self, tmp_path, capsys):
        self._init_ws(tmp_path)
        add_doc_args = self._make_args(
            "add-doc",
            file="annual.pdf",
            doc_type="annual_report",
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(add_doc_args)
        capsys.readouterr()

        read_args = self._make_args(
            "read-attempt",
            document="annual.pdf",
            status="encoding_error",
            error="Chinese text extraction failed",
            max_attempts=1,
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(read_args)
        assert "blocked_pdf_read" in capsys.readouterr().out

        fallback_args = self._make_args(
            "web-fallback",
            document="annual.pdf",
            url="https://example.com/annual-report.pdf",
            source_kind="company_ir",
            complete_report=True,
        )
        with self._patch_ws(tmp_path)[0], self._patch_ws(tmp_path)[1]:
            from src.cli import cmd_materials
            cmd_materials(fallback_args)
        assert "web_fallback_complete_report" in capsys.readouterr().out


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

        with patch("src.analysis._base.WORKSPACES_DIR", tmp_path), \
             patch("src.report.generator.generate_report_html") as mock_gen:
            mock_gen.return_value = ws / "report.html"
            from src.cli import cmd_report
            cmd_report(args)
            mock_gen.assert_called_once()

    def test_report_subcommand_accepts_prefixed_workspace_path(self, tmp_path):
        root = tmp_path / "workspaces"
        ws = root / "TEST"
        ws.mkdir(parents=True)
        (ws / "step1_business_analysis.md").write_text("# Step 1\nContent", encoding="utf-8")

        args = MagicMock()
        args.workspace = "workspaces/TEST"
        args.ticker = "TEST"
        args.name = ""

        with patch("src.analysis._base.WORKSPACES_DIR", root), \
             patch("src.report.generator.generate_report_html") as mock_gen:
            mock_gen.return_value = ws / "report.html"
            from src.cli import cmd_report
            cmd_report(args)

        called_workspace = mock_gen.call_args.kwargs["workspace_dir"]
        assert called_workspace == str(ws)


class TestCmdModel:
    def test_model_blocks_when_step4_validation_fails(self, tmp_path, capsys):
        args = MagicMock()
        args.workspace = "TEST"
        args.ticker = "TEST"
        args.max_attempts = 2

        with patch("src.cli.WORKSPACES_DIR", tmp_path), \
             patch("src.analysis.step4_validate.validate_step4_with_guard") as mock_validate, \
             patch("src.analysis.financial_model.generate_financial_model_artifacts") as mock_model:
            mock_validate.return_value = {
                "passed": False,
                "summary": "blocked",
                "fix_required": ["missing drivers"],
                "guard": {"should_stop": False, "attempt_count": 1},
            }
            from src.cli import cmd_model
            with pytest.raises(SystemExit):
                cmd_model(args)
            mock_model.assert_not_called()
        out = capsys.readouterr().out
        assert "Forecast model generation blocked" in out


class TestCmdExcelModel:
    def test_excel_model_passes_resolved_workspace_path(self, tmp_path, capsys):
        root = tmp_path / "workspaces"
        ws = root / "TEST"
        ws.mkdir(parents=True)

        args = MagicMock()
        args.workspace = "TEST"
        args.ticker = "TEST"

        with patch("src.analysis._base.WORKSPACES_DIR", root), \
             patch("src.analysis.excel_model.generate_excel_model") as mock_excel:
            mock_excel.return_value = ws / "step5_3statement_model.xlsx"
            from src.cli import cmd_excel_model
            cmd_excel_model(args)

        called_workspace = mock_excel.call_args.args[0]
        assert called_workspace == ws
        result = json.loads(capsys.readouterr().out)
        assert result["excel_path"].endswith("step5_3statement_model.xlsx")


class TestCmdWorkflow:
    def test_workflow_status_outputs_state(self, tmp_path, capsys):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = "status"
        args.step = None
        args.artifact = None
        args.summary = ""
        args.reason = ""
        args.force = False

        with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
            from src.cli import cmd_workflow
            cmd_workflow(args)
        result = json.loads(capsys.readouterr().out)
        assert "steps" in result

    def test_workflow_start_rejects_missing_dependency(self, tmp_path, capsys):
        args = MagicMock()
        args.workspace = "TEST"
        args.action = "start"
        args.step = 2
        args.artifact = None
        args.summary = ""
        args.reason = ""
        args.force = False

        with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
            from src.cli import cmd_workflow
            with pytest.raises(SystemExit):
                cmd_workflow(args)
        result = json.loads(capsys.readouterr().out)
        assert result["started"] is False
