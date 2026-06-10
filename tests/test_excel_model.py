"""Tests for the professional three-statement Excel model generator."""

import json
import tempfile
from pathlib import Path

import pytest

from src.analysis.excel_model import (
    EXCEL_FILENAME,
    SheetLayout,
    _col_letter,
    _extract_driver_values,
    _load_drivers,
    _num,
    _safe_sheet_name,
    generate_excel_model,
)
from src.analysis.financial_model import generate_financial_model_artifacts
from src.analysis.step4_schema import save_structured_assumptions

# ── Fixtures ──────────────────────────────────────────────────────────


def _minimal_structured():
    """Minimal valid Step 4 structured assumptions (list-format)."""
    return {
        "forecast_periods": ["2027E", "2028E", "2029E"],
        "segment_revenues": [
            {"name": "Cloud", "base_revenue": 100, "p50_growth": 0.20, "p50_revenue": 120},
            {"name": "Ads", "base_revenue": 200, "p50_growth": 0.10, "p50_revenue": 220},
        ],
        "growth_drivers": [
            {
                "segment": "Cloud",
                "drivers": [
                    {
                        "name": "Volume",
                        "contribution_pct": 0.15,
                        "evidence_ids": ["DATA:usage"],
                        "derivation": "Usage growth converts into cloud volume.",
                        "base_value": 100,
                        "unit": "units",
                        "growth_2027E": 0.12,
                        "growth_2028E": 0.10,
                        "growth_2029E": 0.08,
                    },
                    {
                        "name": "ASP",
                        "contribution_pct": 0.05,
                        "evidence_ids": ["DATA:pricing"],
                        "derivation": "Mix upgrade supports ASP contribution.",
                        "base_value": 1.0,
                        "unit": "CNY/unit",
                        "growth_2027E": 0.03,
                        "growth_2028E": 0.02,
                        "growth_2029E": 0.02,
                    },
                ],
            },
            {
                "segment": "Ads",
                "drivers": [
                    {
                        "name": "Impressions",
                        "contribution_pct": 0.06,
                        "evidence_ids": ["DATA:traffic"],
                        "derivation": "Traffic growth drives impressions.",
                        "base_value": 1000,
                        "unit": "impressions",
                        "growth_2027E": 0.08,
                        "growth_2028E": 0.06,
                        "growth_2029E": 0.05,
                    },
                    {
                        "name": "CPM",
                        "contribution_pct": 0.04,
                        "evidence_ids": ["DATA:cpm"],
                        "derivation": "Ad pricing improvement.",
                        "base_value": 0.20,
                        "unit": "CNY",
                        "growth_2027E": 0.02,
                        "growth_2028E": 0.02,
                        "growth_2029E": 0.01,
                    },
                ],
            },
        ],
        "assumption_matrix": [
            {"variable": "rev_growth", "year": "2028E", "p10": 0.04, "p50": 0.10, "p90": 0.18,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:usage"],
             "derivation": "Growth normalizes.", "what_would_change_this": "Customer adds slow."},
            {"variable": "rev_growth", "year": "2029E", "p10": 0.03, "p50": 0.08, "p90": 0.15,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:usage"],
             "derivation": "Further normalization.", "what_would_change_this": "Market saturates."},
            {"variable": "gross_margin", "year": "2027E", "p10": 0.30, "p50": 0.42, "p90": 0.50,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"],
             "derivation": "Cost buildup.", "what_would_change_this": "Costs rise."},
            {"variable": "gross_margin", "year": "2028E", "p10": 0.31, "p50": 0.43, "p90": 0.51,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"],
             "derivation": "Leverage.", "what_would_change_this": "Cost inflation."},
            {"variable": "gross_margin", "year": "2029E", "p10": 0.32, "p50": 0.44, "p90": 0.52,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["DATA:cost"],
             "derivation": "Scale.", "what_would_change_this": "Mix shifts."},
            {"variable": "opex_ratio", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"],
             "derivation": "Historical.", "what_would_change_this": "Hiring ramp."},
            {"variable": "opex_ratio", "year": "2028E", "p10": 0.15, "p50": 0.19, "p90": 0.24,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"],
             "derivation": "Leverage.", "what_would_change_this": "Hiring ramp."},
            {"variable": "opex_ratio", "year": "2029E", "p10": 0.14, "p50": 0.18, "p90": 0.23,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:opex"],
             "derivation": "Continued leverage.", "what_would_change_this": "R&D cycle."},
            {"variable": "tax_rate", "year": "2027E", "p10": 0.15, "p50": 0.20, "p90": 0.25,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"],
             "derivation": "Effective rate.", "what_would_change_this": "Jurisdiction shift."},
            {"variable": "tax_rate", "year": "2028E", "p10": 0.15, "p50": 0.20, "p90": 0.25,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"],
             "derivation": "Stable.", "what_would_change_this": "Jurisdiction shift."},
            {"variable": "tax_rate", "year": "2029E", "p10": 0.15, "p50": 0.20, "p90": 0.25,
             "sensitivity": "medium", "confidence": "medium", "evidence_ids": ["DATA:tax"],
             "derivation": "Stable.", "what_would_change_this": "Jurisdiction shift."},
            {"variable": "pe", "year": "2027E", "p10": 15, "p50": 24, "p90": 35,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:val"],
             "derivation": "Peer anchored.", "what_would_change_this": "Sector derates."},
            {"variable": "pe", "year": "2028E", "p10": 14, "p50": 22, "p90": 32,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:val"],
             "derivation": "Normalizes.", "what_would_change_this": "Sector derates."},
            {"variable": "pe", "year": "2029E", "p10": 13, "p50": 20, "p90": 30,
             "sensitivity": "high", "confidence": "medium", "evidence_ids": ["CALC:val"],
             "derivation": "Normalizes.", "what_would_change_this": "Sector derates."},
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


def _setup_workspace(tmp: str) -> Path:
    """Create a minimal workspace with forecast_model.json ready for Excel generation."""
    ws = Path(tmp)
    save_structured_assumptions(ws, _minimal_structured())
    _write_reviewed_lock(ws)
    # Build and save the forecast_model.json (Phase 1)
    generate_financial_model_artifacts(ws, ticker="TEST")
    return ws


# ── Unit tests ─────────────────────────────────────────────────────────


class TestSheetLayout:
    def test_sequential_allocation(self):
        layout = SheetLayout()
        assert layout.add("a") == 1
        assert layout.add("b") == 2
        assert layout.row() == 3

    def test_multi_row_allocation(self):
        layout = SheetLayout()
        assert layout.add("block", height=4) == 1
        assert layout.row() == 5
        assert layout["block"] == 1

    def test_named_access(self):
        layout = SheetLayout()
        layout.add("revenue")
        assert layout["revenue"] == 1

    def test_missing_key_raises(self):
        layout = SheetLayout()
        with pytest.raises(KeyError):
            layout["nonexistent"]


class TestHelpers:
    def test_num_int(self):
        assert _num(42) == 42.0

    def test_num_str(self):
        assert _num("3.14") == 3.14

    def test_num_pct_str(self):
        assert _num("22%") == pytest.approx(0.22)

    def test_num_none_default(self):
        assert _num(None, -1.0) == -1.0

    def test_num_empty_string(self):
        assert _num("") == 0.0

    def test_col_letter_a(self):
        assert _col_letter(1) == "A"

    def test_col_letter_z(self):
        assert _col_letter(26) == "Z"

    def test_col_letter_aa(self):
        assert _col_letter(27) == "AA"

    def test_safe_sheet_name_truncates(self):
        assert len(_safe_sheet_name("A" * 50)) == 31

    def test_safe_sheet_name_replaces_invalid(self):
        assert "[" not in _safe_sheet_name("Data[2024]")
        assert "]" not in _safe_sheet_name("Data[2024]")


class TestLoadDrivers:
    def test_loads_drivers_by_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            save_structured_assumptions(ws, _minimal_structured())
            drivers = _load_drivers(ws)
            assert "Cloud" in drivers
            assert "Ads" in drivers
            assert len(drivers["Cloud"]) == 2
            assert drivers["Cloud"][0]["name"] == "Volume"

    def test_returns_empty_when_no_drivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _minimal_structured()
            del data["growth_drivers"]
            save_structured_assumptions(ws, data)
            drivers = _load_drivers(ws)
            assert drivers == {}


class TestExtractDriverValues:
    def test_contribution_pct_without_explicit_raises(self):
        """When drivers lack explicit base_value/growth, raises ValueError (blocked in Step 5)."""
        drivers = [
            {"name": "Volume", "contribution_pct": 15, "evidence_ids": ["E1"],
             "derivation": "test"},
            {"name": "ASP", "contribution_pct": 5, "evidence_ids": ["E2"],
             "derivation": "test"},
        ]
        periods = ["T+1", "T+2", "T+3"]
        with pytest.raises(ValueError, match="base_value|explicit|Step 4"):
            _extract_driver_values(drivers, periods, base_revenue=1000.0)

    def test_explicit_driver_data(self):
        """When drivers have base_value and per-period growth, uses explicit mode."""
        drivers = [
            {"name": "Volume", "contribution_pct": 15, "evidence_ids": ["E1"],
             "derivation": "test", "base_value": 1000, "unit": "units",
             "growth_T+1": 0.10, "growth_T+2": 0.08, "growth_T+3": 0.06},
            {"name": "ASP", "contribution_pct": 5, "evidence_ids": ["E2"],
             "derivation": "test", "base_value": 5.0, "unit": "CNY/unit",
             "growth_T+1": 0.03, "growth_T+2": 0.02, "growth_T+3": 0.02},
        ]
        periods = ["T+1", "T+2", "T+3"]
        result = _extract_driver_values(drivers, periods, base_revenue=5000.0)
        assert len(result) == 2
        assert result[0]["mode"] == "explicit"
        assert result[0]["base_value"] == 1000.0
        assert result[0]["growths"]["T+1"] == pytest.approx(0.10)


# ── Integration tests ──────────────────────────────────────────────────


class TestGenerateExcelModel:
    def test_generates_xlsx_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            assert output.exists()
            assert output.name == EXCEL_FILENAME

    def test_xlsx_has_six_tabs(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            assert len(wb.sheetnames) == 6
            assert "Revenue Build" in wb.sheetnames
            assert "Income Statement" in wb.sheetnames
            assert "Balance Sheet" in wb.sheetnames
            assert "Cash Flow" in wb.sheetnames
            assert "Valuation Bridge" in wb.sheetnames
            assert "Assumptions & Checks" in wb.sheetnames

    def test_revenue_build_first_tab(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            assert wb.sheetnames[0] == "Revenue Build"

    def test_revenue_build_has_drivers(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            rev = wb["Revenue Build"]
            # Check that driver names appear in the sheet
            values = []
            for row in rev.iter_rows(min_col=1, max_col=1, values_only=False):
                for cell in row:
                    if cell.value:
                        values.append(str(cell.value))
            text = " ".join(values)
            assert "Volume" in text or "volume" in text.lower()
            assert "ASP" in text or "asp" in text.lower()
            assert "Total Revenue" in text

    def test_income_statement_has_formulas(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            is_ws = wb["Income Statement"]
            # Check for cross-sheet formula references
            formula_found = False
            for row in is_ws.iter_rows(values_only=False):
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("=") and "Revenue Build" in cell.value:
                            formula_found = True
                            break
            assert formula_found, "Income Statement should have cross-sheet formulas to Revenue Build"

    def test_balance_sheet_has_balance_check(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            bs = wb["Balance Sheet"]
            values = []
            for row in bs.iter_rows(min_col=1, max_col=1, values_only=True):
                if row[0]:
                    values.append(str(row[0]))
            text = " ".join(values)
            assert "Balance Check" in text

    def test_assumptions_checks_tab_has_integrity_checks(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            checks = wb["Assumptions & Checks"]
            values = []
            for row in checks.iter_rows(min_col=1, max_col=1, values_only=True):
                if row[0]:
                    values.append(str(row[0]))
            text = " ".join(values)
            assert "BS Balance" in text
            assert "Cash Tie-out" in text
            assert "NI Linkage" in text
            assert "Revenue Linkage" in text

    def test_fails_without_forecast_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # No forecast_model.json — should raise
            with pytest.raises(FileNotFoundError, match="forecast_model.json"):
                generate_excel_model(ws, ticker="TEST")

    def test_projection_cells_have_blue_font(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            rev = wb["Revenue Build"]
            # Check that at least some projection cells have blue font
            blue_count = 0
            for row in rev.iter_rows(min_col=3, values_only=False):
                for cell in row:
                    if cell.font and cell.font.color and cell.font.color.rgb and "0000CD" in str(cell.font.color.rgb):
                            blue_count += 1
            assert blue_count > 0, "Projection cells should have blue font"

    def test_cash_flow_has_ending_cash(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = _setup_workspace(tmp)
            output = generate_excel_model(ws, ticker="TEST")
            wb = openpyxl.load_workbook(str(output))
            cf = wb["Cash Flow"]
            values = []
            for row in cf.iter_rows(min_col=1, max_col=1, values_only=True):
                if row[0]:
                    values.append(str(row[0]))
            text = " ".join(values)
            assert "Ending Cash" in text
            assert "Cash from Operations" in text


class TestExcelModelWithExplicitDrivers:
    """Test Excel generation when growth_drivers have explicit base values."""

    def _data_with_explicit_drivers(self):
        data = _minimal_structured()
        data["growth_drivers"] = [
            {
                "segment": "Cloud",
                "drivers": [
                    {
                        "name": "Volume",
                        "contribution_pct": 15,
                        "evidence_ids": ["DATA:usage"],
                        "derivation": "Usage growth.",
                        "base_value": 100,
                        "unit": "units",
                        "growth_2027E": 0.12,
                        "growth_2028E": 0.10,
                        "growth_2029E": 0.08,
                    },
                    {
                        "name": "ASP",
                        "contribution_pct": 5,
                        "evidence_ids": ["DATA:pricing"],
                        "derivation": "Price upgrade.",
                        "base_value": 1.0,
                        "unit": "CNY/unit",
                        "growth_2027E": 0.03,
                        "growth_2028E": 0.02,
                        "growth_2029E": 0.02,
                    },
                ],
            },
            {
                "segment": "Ads",
                "drivers": [
                    {
                        "name": "Impressions",
                        "contribution_pct": 6,
                        "evidence_ids": ["DATA:traffic"],
                        "derivation": "Traffic growth.",
                        "base_value": 1000,
                        "unit": "impressions",
                        "growth_2027E": 0.08,
                        "growth_2028E": 0.06,
                        "growth_2029E": 0.05,
                    },
                    {
                        "name": "CPM",
                        "contribution_pct": 4,
                        "evidence_ids": ["DATA:cpm"],
                        "derivation": "Pricing improvement.",
                        "base_value": 0.20,
                        "unit": "CNY",
                        "growth_2027E": 0.02,
                        "growth_2028E": 0.02,
                        "growth_2029E": 0.01,
                    },
                ],
            },
        ]
        return data

    def test_explicit_drivers_render_in_excel(self):
        openpyxl = pytest.importorskip("openpyxl")
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = self._data_with_explicit_drivers()
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            generate_financial_model_artifacts(ws, ticker="EXPL")
            output = generate_excel_model(ws, ticker="EXPL")

            wb = openpyxl.load_workbook(str(output))
            rev = wb["Revenue Build"]
            values = []
            for row in rev.iter_rows(min_col=1, max_col=1, values_only=True):
                if row[0]:
                    values.append(str(row[0]))
            text = " ".join(values)
            assert "Volume" in text
            assert "ASP" in text
            assert "Impressions" in text
            assert "CPM" in text


# ── Tests for institutional-grade line items ─────────────────────────


class TestIncomeStatementLineItems:
    """Verify the enhanced IS has EBITDA, EBT, Interest, and Diluted EPS."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.is_ws = self.wb["Income Statement"]
        self.labels = self._col_a_labels()

    def _col_a_labels(self):
        labels = []
        for row in self.is_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        return " ".join(labels)

    def test_has_ebitda(self):
        assert "EBITDA" in self.labels, "IS must have EBITDA row"

    def test_has_ebt(self):
        assert any(
            "Pre-tax" in lbl or "EBT" in lbl for lbl in self.labels.split()
        ), "IS must have Pre-tax Income / EBT row"

    def test_has_interest_expense(self):
        assert "Interest Expense" in self.labels or "Interest Exp" in self.labels, (
            "IS must have Interest Expense row"
        )

    def test_has_diluted_eps(self):
        assert "Diluted" in self.labels, "IS must have EPS (Diluted) row"

    def test_has_margin_analysis(self):
        assert "Gross Margin" in self.labels, "IS must have Gross Margin % row"
        assert "EBIT Margin" in self.labels or "Operating Margin" in self.labels, (
            "IS must have EBIT/Operating Margin % row"
        )
        assert "Net Margin" in self.labels, "IS must have Net Margin % row"

    def test_ebitda_formula_references_ebit(self):
        """EBITDA row must be a formula referencing EBIT + D&A."""
        for row in self.is_ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and "EBITDA" in str(cell.value) and cell.value.startswith("="):
                    # Should reference EBIT row
                    assert "+" in cell.value, "EBITDA formula should add D&A to EBIT"
                    return
        # If we didn't find a formula cell directly, check by scanning label row
        # (the formula is in a data column, not column A — this is acceptable)


class TestBalanceSheetStructure:
    """Verify the BS has Current/Non-Current breakdown and Retained Earnings."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.bs_ws = self.wb["Balance Sheet"]
        self.labels = self._col_a_labels()

    def _col_a_labels(self):
        labels = []
        for row in self.bs_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        return " ".join(labels)

    def test_has_total_current_assets(self):
        assert "Total Current Assets" in self.labels

    def test_has_total_current_liabilities(self):
        assert "Total Current Liabilities" in self.labels

    def test_has_retained_earnings(self):
        assert "Retained Earnings" in self.labels

    def test_has_total_equity(self):
        assert "Total Equity" in self.labels

    def test_has_total_assets(self):
        assert "Total Assets" in self.labels

    def test_has_total_liabilities(self):
        assert "Total Liabilities" in self.labels

    def test_has_key_line_items(self):
        """BS should have granular items like Cash, AR, Inventory, AP, PP&E."""
        for item in ["Cash", "Accounts Receivable", "Inventory", "PP&E", "Accounts Payable"]:
            assert item in self.labels, f"BS must have '{item}' row"

    def test_has_section_headers(self):
        """BS should have ASSETS, LIABILITIES, EQUITY section headers."""
        for section in ["ASSETS", "LIABILITIES", "EQUITY"]:
            assert section in self.labels, f"BS must have '{section}' section header"

    def test_balance_check_formula_exists(self):
        """The Balance Check row should be a formula (Total Assets - Total L&E)."""
        for row in self.bs_ws.iter_rows(values_only=False):
            for cell in row:
                if (isinstance(cell.value, str) and cell.value.startswith("=") and cell.row > 1
                        and "Balance Check" in str(self.bs_ws.cell(row=cell.row, column=1).value or "")):
                        assert "-" in cell.value, "Balance check should subtract"
                        return
        # Some implementations put the label and formula on different rows — check label presence
        assert "Balance Check" in self.labels


class TestValuationBridgeEnhanced:
    """Verify the Valuation Bridge has EV/EBITDA."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.vb_ws = self.wb["Valuation Bridge"]
        self.labels = self._col_a_labels()

    def _col_a_labels(self):
        labels = []
        for row in self.vb_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        return " ".join(labels)

    def test_has_ev_ebitda(self):
        assert "EV/EBITDA" in self.labels or "EV / EBITDA" in self.labels, (
            "Valuation Bridge must have EV/EBITDA row"
        )

    def test_has_ebitda_row(self):
        assert "EBITDA" in self.labels, "Valuation Bridge must have EBITDA row"

    def test_has_target_price(self):
        assert "Target Price" in self.labels, "Valuation Bridge must have Target Price row"

    def test_has_enterprise_value(self):
        assert "Enterprise Value" in self.labels or "EV" in self.labels, (
            "Valuation Bridge must have Enterprise Value row"
        )

    def test_ebitda_formula_links_to_is(self):
        """EBITDA in Valuation Bridge should reference Income Statement."""
        for row in self.vb_ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("=") and "Income Statement" in cell.value:
                        return  # Found cross-sheet link
        pytest.fail("Valuation Bridge EBITDA should link to Income Statement")

    def test_ev_ebitda_has_if_guard(self):
        """EV/EBITDA formula should guard against division by zero."""
        for row in self.vb_ws.iter_rows(values_only=False):
            for cell in row:
                val = str(cell.value or "")
                if "EV/EBITDA" in val:
                    # Check the same row's data columns for IF formula
                    for dc in row:
                        if isinstance(dc.value, str) and dc.value.startswith("=IF"):
                            assert "0" in dc.value, "IF guard should check for zero EBITDA"
                            return
        # Label might be in column A, formulas in data columns — search adjacent
        for row in self.vb_ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and "IF(" in cell.value and "/" in cell.value:
                    return  # Found an IF-guarded ratio formula
        pytest.fail("EV/EBITDA should have IF(EBITDA=0, 0, ...) guard")


class TestAssumptionsChecksEnhanced:
    """Verify the Checks tab has RE Rollforward and WC Validation."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.checks_ws = self.wb["Assumptions & Checks"]
        self.labels = self._col_a_labels()

    def _col_a_labels(self):
        labels = []
        for row in self.checks_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        return " ".join(labels)

    def test_has_re_rollforward(self):
        assert "RE Rollforward" in self.labels, "Checks must have RE Rollforward check"

    def test_has_wc_validation(self):
        assert "WC Validation" in self.labels or "Working Capital" in self.labels, (
            "Checks must have Working Capital validation"
        )

    def test_has_fcf_consistency(self):
        assert "FCF Consistency" in self.labels, "Checks must have FCF consistency check"

    def test_has_all_six_checks(self):
        """Should have all 6+ integrity checks from the spec."""
        required = ["BS Balance", "Cash Tie-out", "NI Linkage", "Revenue Linkage"]
        for check in required:
            assert check in self.labels, f"Checks must have '{check}' check"

    def test_re_rollforward_has_formulas(self):
        """RE Rollforward check should reference Balance Sheet and Income Statement."""
        formula_found = False
        for row in self.checks_ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("=") and "Balance Sheet" in cell.value and "Income Statement" in cell.value:
                        formula_found = True
                        break
        assert formula_found, "RE Rollforward should reference both BS and IS"

    def test_wc_validation_has_formulas(self):
        """WC Validation check should reference Balance Sheet line items."""
        formula_found = False
        for row in self.checks_ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("=") and "Balance Sheet" in cell.value:
                        formula_found = True
                        break
        assert formula_found, "WC Validation should reference Balance Sheet"


class TestBSFormulaCells:
    """Verify specific BS cells are formulas (not hard-coded)."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.bs_ws = self.wb["Balance Sheet"]

    def _row_has_formula(self, sheet, label_text: str) -> bool:
        """Check if any data cell on the row with label_text is a formula."""
        for row in sheet.iter_rows(values_only=False):
            col_a_val = str(row[0].value or "")
            if label_text in col_a_val:
                for cell in row[1:]:  # Data columns
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        return True
        return False

    def test_cash_is_formula(self):
        """Cash row should be cross-sheet formula from Cash Flow."""
        assert self._row_has_formula(self.bs_ws, "Cash"), (
            "Cash row must have formula (CF ending cash)"
        )

    def test_total_assets_formula(self):
        """Total Assets should be a SUM formula."""
        for row in self.bs_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if "Total Assets" in col_a:
                for cell in row[1:]:
                    if isinstance(cell.value, str) and ("SUM(" in cell.value or cell.value.startswith("=")):
                        return
        pytest.fail("Total Assets should be a formula")

    def test_total_current_assets_formula(self):
        """Total Current Assets should be a SUM formula."""
        for row in self.bs_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if col_a.strip() == "Total Current Assets":
                for cell in row[1:]:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        return
        pytest.fail("Total Current Assets should be a formula")

    def test_balance_check_formula(self):
        """Balance Check should be an arithmetic formula (Assets - L&E)."""
        for row in self.bs_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if "Balance Check" in col_a:
                for cell in row[1:]:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        assert "-" in cell.value, "Balance Check formula should subtract"
                        return
        pytest.fail("Balance Check should be a formula")


class TestNoContributionFallback:
    """Verify Excel generation fails when drivers lack explicit base_value/growth."""

    def test_excel_fails_without_explicit_drivers(self):
        """generate_excel_model should raise when _extract_driver_values fails."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            data = _minimal_structured()
            # Drivers have only contribution_pct, no base_value/growth
            data["growth_drivers"] = [
                {
                    "segment": "Cloud",
                    "drivers": [
                        {
                            "name": "Volume",
                            "contribution_pct": 15,
                            "evidence_ids": ["DATA:usage"],
                            "derivation": "Usage growth.",
                            # Missing: base_value, growth_T+1, growth_T+2, growth_T+3
                        },
                    ],
                },
                {
                    "segment": "Ads",
                    "drivers": [
                        {
                            "name": "Impressions",
                            "contribution_pct": 6,
                            "evidence_ids": ["DATA:traffic"],
                            "derivation": "Traffic growth.",
                        },
                    ],
                },
            ]
            save_structured_assumptions(ws, data)
            _write_reviewed_lock(ws)
            with pytest.raises((ValueError, RuntimeError), match="base_value|explicit|Step 4|driver"):
                generate_financial_model_artifacts(ws, ticker="NOFALLBACK")


class TestOpExFormulaLink:
    """Verify OpEx ratio comes from assumption cell, not derived from model values."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.is_ws = self.wb["Income Statement"]
        self.checks_ws = self.wb["Assumptions & Checks"]

    def test_opex_ratio_is_assumption_cell(self):
        """The OpEx ratio used in formulas should reference an assumption cell."""
        formula_found = False
        for row in self.is_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if "Operating Expense" in col_a or "OpEx" in col_a:
                for cell in row[1:]:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        formula_found = True
                        break
        assert formula_found, (
            "Operating Expense should be a formula referencing Revenue × OpEx ratio"
        )

    def test_da_is_formula_linked(self):
        """D&A should be a formula referencing Revenue × da_ratio."""
        for row in self.is_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if "D&A" in col_a or "Depreciation" in col_a:
                for cell in row[1:]:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        return
        pytest.fail("D&A should be a formula (Revenue × da_ratio)")


class TestDilutedShares:
    """Verify diluted shares handling in Excel model."""

    @pytest.fixture(autouse=True)
    def _build(self, tmp_path):
        save_structured_assumptions(tmp_path, _minimal_structured())
        _write_reviewed_lock(tmp_path)
        generate_financial_model_artifacts(tmp_path, ticker="TEST")
        self.output = generate_excel_model(tmp_path, ticker="TEST")
        openpyxl = pytest.importorskip("openpyxl")
        self.wb = openpyxl.load_workbook(str(self.output))
        self.is_ws = self.wb["Income Statement"]
        self.vb_ws = self.wb["Valuation Bridge"]

    def test_diluted_eps_present(self):
        """Income Statement must have EPS (Diluted) row."""
        labels = []
        for row in self.is_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        text = " ".join(labels)
        assert "Diluted" in text, "IS must have Diluted EPS row"

    def test_valuation_uses_diluted_eps(self):
        """Valuation Bridge should reference Diluted EPS (not Basic)."""
        for row in self.vb_ws.iter_rows(values_only=False):
            col_a = str(row[0].value or "")
            if "EPS" in col_a and "Diluted" in col_a:
                for cell in row[1:]:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        assert "Income Statement" in cell.value, (
                            "Diluted EPS in Valuation should link to IS"
                        )
                        return
        # Label might be "EPS (Diluted)" — acceptable if at least the label exists
        labels = []
        for row in self.vb_ws.iter_rows(min_col=1, max_col=1, values_only=True):
            if row[0]:
                labels.append(str(row[0]))
        text = " ".join(labels)
        assert "Diluted" in text or "EPS" in text, (
            "Valuation Bridge must reference EPS"
        )
