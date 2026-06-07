"""Tests for data fetcher layer — BaseTushareFetcher and AshareFetcher.

These tests mock the Tushare client to verify correct API method dispatch,
error handling, and normalization without requiring network access.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.ashare_fetcher import AshareFetcher
from src.data.base import BaseTushareFetcher, FetchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tushare():
    """Return a MagicMock that can be patched in as tushare_client."""
    return MagicMock()


@pytest.fixture
def ashare_fetcher():
    return AshareFetcher()


# ---------------------------------------------------------------------------
# BaseTushareFetcher template method tests
# ---------------------------------------------------------------------------


class TestBaseTushareFetcher:
    """Verify that the template method pattern dispatches correctly."""

    def test_fetch_all_calls_all_methods(self, ashare_fetcher, mock_tushare):
        """fetch_all should call company_info, price_history, financials, valuation."""
        with (
            patch.object(ashare_fetcher, "fetch_company_info", return_value=FetchResult(data={"name": "Test"}, source="mock")),
            patch.object(ashare_fetcher, "fetch_price_history", return_value=FetchResult(data=pd.DataFrame(), source="mock")),
            patch.object(ashare_fetcher, "fetch_financial_statements", return_value=FetchResult(data={}, source="mock")),
            patch.object(ashare_fetcher, "fetch_valuation_inputs", return_value=FetchResult(data={}, source="mock")),
        ):
            results = ashare_fetcher.fetch_all("600519.SH", period="3y")
        assert "company_info" in results
        assert "price_history" in results
        assert "financials" in results
        assert "valuation" in results
        assert all(r.success for r in results.values())

    def test_fetch_all_catches_errors(self, ashare_fetcher):
        """When a method raises, fetch_all should return a failed FetchResult, not propagate."""
        with patch.object(ashare_fetcher, "fetch_company_info", side_effect=RuntimeError("API down")):
            results = ashare_fetcher.fetch_all("600519.SH")
        assert results["company_info"].success is False
        assert "API down" in str(results["company_info"].warnings)

    def test_api_methods_defined(self, ashare_fetcher):
        """AshareFetcher must define all required api_methods keys."""
        required = {"daily", "income", "balance_sheet", "cashflow", "fina_indicator"}
        assert required.issubset(set(ashare_fetcher.api_methods.keys()))

    def test_price_warning_set(self, ashare_fetcher):
        assert ashare_fetcher.price_warning != ""

    def test_today_is_yyyymmdd(self, ashare_fetcher):
        today = ashare_fetcher._today()
        assert len(today) == 8
        assert today.isdigit()

    def test_start_date_returns_yyyymmdd(self, ashare_fetcher):
        for period in ("1y", "2y", "3y", "5y", "10y"):
            sd = ashare_fetcher._start_date(period)
            assert len(sd) == 8
            assert sd.isdigit()

    def test_start_date_default_is_5y(self, ashare_fetcher):
        sd = ashare_fetcher._start_date("unknown")
        assert len(sd) == 8

    def test_compute_ev_positive(self, ashare_fetcher):
        ev = ashare_fetcher._compute_ev(100, 50, 20)
        assert ev == 130.0

    def test_compute_ev_none_market_cap(self, ashare_fetcher):
        assert ashare_fetcher._compute_ev(None, 50, 20) is None

    def test_compute_ev_none_debt(self, ashare_fetcher):
        assert ashare_fetcher._compute_ev(100, None, 20) is None

    def test_compute_ev_zero_cash(self, ashare_fetcher):
        ev = ashare_fetcher._compute_ev(100, 50, 0)
        assert ev == 150.0


# ---------------------------------------------------------------------------
# AshareFetcher specific tests
# ---------------------------------------------------------------------------


class TestAshareFetcherIntegration:
    """Integration-style tests with mocked Tushare client."""

    def test_fetch_company_info_produces_structure(self, ashare_fetcher, mock_tushare):
        """Even with empty DataFrames, company_info should return the expected keys."""
        mock_tushare.stock_basic.return_value = pd.DataFrame()
        mock_tushare.stock_company.return_value = pd.DataFrame()

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = ashare_fetcher.fetch_company_info("600519.SH")

        assert result.success is True
        assert isinstance(result.data, dict)
        expected_keys = {"name", "sector", "industry", "description", "chairman", "employees"}
        assert expected_keys.issubset(set(result.data.keys()))

    def test_fetch_company_info_handles_exceptions(self, ashare_fetcher, mock_tushare):
        """When Tushare raises, the method should still return a successful result with warnings."""
        mock_tushare.stock_basic.side_effect = RuntimeError("Connection refused")
        mock_tushare.stock_company.side_effect = RuntimeError("Timeout")

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = ashare_fetcher.fetch_company_info("600519.SH")

        assert result.success is True
        assert len(result.warnings) >= 1

    def test_fetch_valuation_inputs_structure(self, ashare_fetcher, mock_tushare):
        """Valuation inputs should return dict with expected keys when data present."""
        mock_tushare.daily_basic.return_value = pd.DataFrame([{
            "trade_date": "20260101",
            "close": 25.0,
            "pe_ttm": 18.0,
            "pe": 17.5,
            "pb": 3.2,
            "ps_ttm": 2.5,
            "total_share": 1000.0,  # 万股
            "total_mv": 250000.0,   # 万元
            "circ_mv": 200000.0,
        }])
        mock_tushare.fina_indicator.return_value = pd.DataFrame([{
            "end_date": "20251231",
            "eps": 1.5,
            "bps": 8.0,
            "roe": 18.0,
            "ebitda": 5000.0,
        }])
        mock_tushare.balancesheet.return_value = pd.DataFrame([{
            "ann_date": "20260401",
            "end_date": "20251231",
            "total_liab": 10000.0,
            "money_cap": 5000.0,
            "total_assets": 30000.0,
            "total_hldr_eqy_exc_min_int": 15000.0,
        }])

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = ashare_fetcher.fetch_valuation_inputs("600519.SH")

        assert result.success is True
        assert isinstance(result.data, dict)
        # Shares should be converted from 万股 to actual shares (× 10000)
        assert result.data.get("shares_outstanding") == 10_000_000.0
        # Market cap should be converted from 万元 (× 10000)
        assert result.data.get("market_cap") == 2_500_000_000.0

    def test_fetch_price_history_with_mock(self, ashare_fetcher, mock_tushare):
        """Price history should return a DataFrame."""
        mock_tushare.daily.return_value = pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_date": ["20260101", "20260102", "20260103"],
            "open": [24.0, 24.5, 25.0],
            "high": [25.0, 25.5, 26.0],
            "low": [23.5, 24.0, 24.5],
            "close": [25.0, 25.0, 25.5],
            "vol": [10000, 12000, 11000],
            "amount": [250000, 300000, 280000],
        })

        with (
            patch("src.data.tushare_client.tushare_client", mock_tushare),
            patch("src.data.tushare_normalizer.normalize_price_df", lambda df: df),
        ):
            result = ashare_fetcher.fetch_price_history("600519.SH", period="1y")

        assert result.success is True
        assert isinstance(result.data, pd.DataFrame)
        assert len(result.data) == 3

    def test_fetch_price_history_handles_empty(self, ashare_fetcher, mock_tushare):
        """When Tushare returns empty, should return failed result."""
        mock_tushare.daily.return_value = pd.DataFrame()

        with (
            patch("src.data.tushare_client.tushare_client", mock_tushare),
            patch("src.data.tushare_normalizer.normalize_price_df", lambda df: None),
        ):
            result = ashare_fetcher.fetch_price_history("600519.SH")

        assert result.success is False
        assert result.warnings


class TestFetchResult:
    def test_defaults(self):
        fr = FetchResult()
        assert fr.data is None
        assert fr.source == ""
        assert fr.warnings == []
        assert fr.success is True

    def test_error_result(self):
        fr = FetchResult(success=False, warnings=["API error"])
        assert fr.success is False
        assert "API error" in fr.warnings

    def test_data_result(self):
        fr = FetchResult(data={"key": "val"}, source="tushare")
        assert fr.data == {"key": "val"}
        assert fr.source == "tushare"
