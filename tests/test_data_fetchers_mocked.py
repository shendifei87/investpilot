"""Tests using recorded API fixture data.

These tests use pre-recorded API responses from tests/fixtures/ to verify
data fetcher behavior without network access. This complements
test_data_fetchers.py which uses inline mock data.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.ashare_fetcher import AshareFetcher
from src.data.us_fetcher import USFetcher

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    """Load a JSON fixture file from tests/fixtures/."""
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mock_tushare():
    return MagicMock()


# ---------------------------------------------------------------------------
# AshareFetcher tests using fixture data
# ---------------------------------------------------------------------------


class TestAshareFetcherWithFixtures:
    """Verify AshareFetcher against recorded API response shapes."""

    def test_price_history_from_fixture(self, mock_tushare):
        """Price history should parse fixture daily data correctly."""
        fetcher = AshareFetcher()
        mock_tushare.daily.return_value = pd.DataFrame(load_fixture("tushare_daily.json"))

        with (
            patch("src.data.tushare_client.tushare_client", mock_tushare),
            patch("src.data.tushare_normalizer.normalize_price_df", lambda df: df),
        ):
            result = fetcher.fetch_price_history("600519.SH", period="1y")

        assert result.success is True
        assert isinstance(result.data, pd.DataFrame)
        assert len(result.data) == 3
        assert list(result.data["close"]) == [25.0, 25.0, 25.5]

    def test_valuation_inputs_from_fixture(self, mock_tushare):
        """Valuation inputs should compute shares/market_cap from fixture data."""
        fetcher = AshareFetcher()
        mock_tushare.daily_basic.return_value = pd.DataFrame(load_fixture("tushare_daily_basic.json"))
        mock_tushare.fina_indicator.return_value = pd.DataFrame(load_fixture("tushare_fina_indicator.json"))
        mock_tushare.balancesheet.return_value = pd.DataFrame(load_fixture("tushare_balance_sheet.json"))

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = fetcher.fetch_valuation_inputs("600519.SH")

        assert result.success is True
        assert isinstance(result.data, dict)
        # Shares converted from 万股 to actual shares (× 10000)
        assert result.data["shares_outstanding"] == 10_000_000.0
        # Market cap converted from 万元 (× 10000)
        assert result.data["market_cap"] == 2_500_000_000.0
        # Interest-bearing debt only: st_borr + lt_borr + bond_payable + non_cur_liab_due_1y
        assert result.data["total_debt"] == 24000.0

    def test_company_info_from_fixture(self, mock_tushare):
        """Company info should extract name and industry from fixture."""
        fetcher = AshareFetcher()
        mock_tushare.stock_basic.return_value = pd.DataFrame([load_fixture("tushare_stock_basic.json")])
        mock_tushare.stock_company.return_value = pd.DataFrame()

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = fetcher.fetch_company_info("600519.SH")

        assert result.success is True
        assert result.data["name"] == "贵州茅台"
        assert result.data["industry"] == "白酒"

    def test_financials_from_fixture(self, mock_tushare):
        """Financial statements should return structured data from income/balance fixtures."""
        fetcher = AshareFetcher()
        mock_tushare.income.return_value = pd.DataFrame(load_fixture("tushare_income.json"))
        mock_tushare.balancesheet.return_value = pd.DataFrame(load_fixture("tushare_balance_sheet.json"))
        mock_tushare.cashflow.return_value = pd.DataFrame()
        mock_tushare.fina_indicator.return_value = pd.DataFrame(load_fixture("tushare_fina_indicator.json"))

        with patch("src.data.tushare_client.tushare_client", mock_tushare):
            result = fetcher.fetch_financial_statements("600519.SH")

        assert result.success is True
        assert isinstance(result.data, dict)


# ---------------------------------------------------------------------------
# USFetcher tests using fixture data
# ---------------------------------------------------------------------------


class TestUSFetcherWithFixtures:
    """Verify USFetcher against recorded SEC EDGAR response shapes."""

    def test_sec_tickers_parsing(self):
        """SEC company_tickers.json fixture should parse correctly."""
        tickers = load_fixture("sec_company_tickers.json")
        assert tickers["0"]["ticker"] == "AAPL"
        assert tickers["1"]["ticker"] == "MSFT"
        assert tickers["2"]["ticker"] == "TSLA"

    def test_sec_facts_parsing(self):
        """SEC company_facts fixture should have correct revenue structure."""
        facts = load_fixture("sec_facts_aapl.json")
        revenues = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        assert len(revenues) == 2
        assert revenues[0]["val"] == 391_035_000_000

    def test_valuation_inputs_with_mocked_akshare(self, monkeypatch):
        """USFetcher should work with mocked AKShare + SEC fixture data."""
        fetcher = USFetcher()

        # Mock akshare
        fake_ak = types.SimpleNamespace()
        fake_ak.stock_us_daily = lambda symbol, adjust="": pd.DataFrame({
            "日期": ["2026-01-02"],
            "收盘": [195.0],
            "最高": [196.0],
            "最低": [193.0],
            "开盘": [194.0],
            "成交量": [50000000],
        })
        monkeypatch.setitem(sys.modules, "akshare", fake_ak)

        # Mock requests for SEC
        class FakeResp:
            def __init__(self, data):
                self._data = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        tickers = load_fixture("sec_company_tickers.json")
        facts = load_fixture("sec_facts_aapl.json")

        def fake_get(url, **kwargs):
            if "company_tickers" in url:
                return FakeResp(tickers)
            return FakeResp(facts)

        monkeypatch.setattr("src.data.us_fetcher.requests.get", fake_get)

        result = fetcher.fetch_valuation_inputs("AAPL")
        assert result.success is True
        # Mocked SEC data resolves revenue and net_income at minimum;
        # shares requires a more complete EntityCommonStockSharesOutstanding structure
        assert "revenue_ttm" in result.data
        assert "net_income_ttm" in result.data
