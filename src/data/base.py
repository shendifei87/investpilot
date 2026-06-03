"""Base classes for market data fetchers.

BaseFetcher defines the abstract interface.
BaseTushareFetcher provides shared Tushare-specific logic (price history,
financial statements, utility methods) so market subclasses only need to
override company_info and valuation_inputs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import pandas as pd

from config.ticker_rules import get_tushare_code


@dataclass
class FetchResult:
    data: Optional[object] = None
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    success: bool = True


class BaseFetcher(ABC):
    market: str

    @abstractmethod
    def fetch_company_info(self, ticker: str) -> FetchResult:
        ...

    @abstractmethod
    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        ...

    @abstractmethod
    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        ...

    @abstractmethod
    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs (price, shares, EPS, etc.) for local calculation.

        Returns raw data only — no pre-computed PE/PB/PS/EV·EBITDA ratios.
        All valuation ratios should be calculated via src.analysis.financial.calc_* functions.
        """
        ...

    def fetch_valuation_metrics(self, ticker: str) -> FetchResult:
        """Deprecated alias for fetch_valuation_inputs.

        Prefer calling fetch_valuation_inputs directly.
        """
        return self.fetch_valuation_inputs(ticker)

    def fetch_all(self, ticker: str, period: str = "5y") -> Dict[str, FetchResult]:
        results = {}
        for name, method in [
            ("company_info", self.fetch_company_info),
            ("price_history", lambda t: self.fetch_price_history(t, period=period)),
            ("financials", self.fetch_financial_statements),
            ("valuation", self.fetch_valuation_inputs),
        ]:
            try:
                results[name] = method(ticker)
            except Exception as e:
                results[name] = FetchResult(
                    success=False,
                    warnings=[f"Failed to fetch {name}: {e}"],
                )
        return results


class BaseTushareFetcher(BaseFetcher):
    """Shared Tushare-specific logic for all market fetchers.

    Subclasses must set:
        - api_methods: dict mapping logical names to Tushare API method names
          Required keys: "daily", "income", "balance_sheet", "cashflow"
          Optional key: "fina_indicator"
        - price_warning: str for when no price data is returned

    Subclasses must override:
        - fetch_company_info() — market-specific API calls
        - fetch_valuation_inputs() — market-specific data sources

    Subclasses may override:
        - fetch_financial_statements() — if extra statements are needed
    """

    api_methods: Dict[str, str] = {}
    price_warning: str = "No price data returned"

    # ── Utility methods ─────────────────────────────────────

    def _ts_code(self, ticker: str) -> str:
        return get_tushare_code(ticker, self.market)

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y%m%d")

    @staticmethod
    def _start_date(period: str) -> str:
        years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)
        return (datetime.now() - timedelta(days=365 * years)).strftime("%Y%m%d")

    @staticmethod
    def _compute_ev(market_cap, total_debt, total_cash) -> Optional[float]:
        """Compute Enterprise Value = market_cap + total_debt - total_cash."""
        if market_cap and total_debt:
            return float(market_cap) + float(total_debt) - float(total_cash or 0)
        return None

    # ── Price history (template method) ─────────────────────

    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        """Fetch daily OHLCV from Tushare.

        Uses the 'daily' key from api_methods to call the correct API.
        """
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import normalize_price_df

        ts_code = self._ts_code(ticker)
        start_date = self._start_date(period)
        end_date = self._today()

        try:
            raw_df = getattr(tushare_client, self.api_methods["daily"])(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            df = normalize_price_df(raw_df)
            if df is not None and not df.empty:
                return FetchResult(data=df, source="tushare", success=True)
        except Exception as e:
            return FetchResult(success=False, warnings=[str(e)])

        return FetchResult(success=False, warnings=[self.price_warning])

    # ── Financial statements (template method) ──────────────

    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        """Fetch income/balance/cashflow from Tushare.

        Uses api_methods to call the correct API methods per market.
        If 'fina_indicator' is in api_methods, also fetches financial ratios.
        """
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import (
            normalize_income_df,
            normalize_balance_df,
            normalize_cashflow_df,
        )

        ts_code = self._ts_code(ticker)
        start_date = self._start_date("5y")
        result = {}
        warnings = []

        # Income statement
        try:
            raw = getattr(tushare_client, self.api_methods["income"])(
                ts_code=ts_code, start_date=start_date,
            )
            result["income"] = normalize_income_df(raw)
        except Exception as e:
            result["income"] = pd.DataFrame()
            warnings.append(f"{self.api_methods['income']} failed: {e}")

        # Balance sheet
        try:
            raw = getattr(tushare_client, self.api_methods["balance_sheet"])(
                ts_code=ts_code, start_date=start_date,
            )
            result["balance_sheet"] = normalize_balance_df(raw)
        except Exception as e:
            result["balance_sheet"] = pd.DataFrame()
            warnings.append(f"{self.api_methods['balance_sheet']} failed: {e}")

        # Cash flow
        try:
            raw = getattr(tushare_client, self.api_methods["cashflow"])(
                ts_code=ts_code, start_date=start_date,
            )
            result["cashflow"] = normalize_cashflow_df(raw)
        except Exception as e:
            result["cashflow"] = pd.DataFrame()
            warnings.append(f"{self.api_methods['cashflow']} failed: {e}")

        # Financial indicators (optional — only if api_methods defines it)
        if "fina_indicator" in self.api_methods:
            try:
                from src.data.tushare_normalizer import normalize_fina_indicator_df
                raw = getattr(tushare_client, self.api_methods["fina_indicator"])(
                    ts_code=ts_code, start_date=start_date,
                )
                result["financial_ratios"] = normalize_fina_indicator_df(raw)
            except Exception as e:
                warnings.append(f"{self.api_methods['fina_indicator']} failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
