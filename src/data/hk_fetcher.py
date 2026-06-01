"""HK stock data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - hk_basic: company info
  - hk_daily: price history
  - hk_income / hk_balancesheet / hk_cashflow: financial statements
"""

import pandas as pd
from datetime import datetime, timedelta
from src.data.base import BaseFetcher, FetchResult
from config.ticker_rules import get_tushare_code


class HKFetcher(BaseFetcher):
    market = "HK"

    def _ts_code(self, ticker: str) -> str:
        return get_tushare_code(ticker, "HK")

    def _today(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _start_date(self, period: str) -> str:
        years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)
        return (datetime.now() - timedelta(days=365 * years)).strftime("%Y%m%d")

    # ------------------------------------------------------------------
    # Company info
    # ------------------------------------------------------------------

    def fetch_company_info(self, ticker: str) -> FetchResult:
        from src.data.tushare_client import tushare_client

        warnings = []
        result = {
            "name": "", "sector": "", "industry": "",
            "market_cap": None, "description": "", "shares_outstanding": None,
        }

        ts_code = self._ts_code(ticker)

        try:
            basic_df = tushare_client.hk_basic(ts_code=ts_code)
            if basic_df is not None and not basic_df.empty:
                row = basic_df.iloc[0]
                result["name"] = row.get("name", "")
                result["industry"] = row.get("industry", "")
        except Exception as e:
            warnings.append(f"hk_basic failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import normalize_price_df

        ts_code = self._ts_code(ticker)
        start_date = self._start_date(period)
        end_date = self._today()

        try:
            raw_df = tushare_client.hk_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            df = normalize_price_df(raw_df)
            if df is not None and not df.empty:
                return FetchResult(data=df, source="tushare", success=True)
        except Exception as e:
            return FetchResult(success=False, warnings=[str(e)])

        return FetchResult(success=False, warnings=["No HK price data returned"])

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import (
            normalize_income_df,
            normalize_balance_df,
            normalize_cashflow_df,
        )

        ts_code = self._ts_code(ticker)
        result = {}
        warnings = []

        try:
            raw = tushare_client.hk_income(ts_code=ts_code)
            result["income"] = normalize_income_df(raw)
        except Exception as e:
            result["income"] = pd.DataFrame()
            warnings.append(f"hk_income failed: {e}")

        try:
            raw = tushare_client.hk_balancesheet(ts_code=ts_code)
            result["balance_sheet"] = normalize_balance_df(raw)
        except Exception as e:
            result["balance_sheet"] = pd.DataFrame()
            warnings.append(f"hk_balancesheet failed: {e}")

        try:
            raw = tushare_client.hk_cashflow(ts_code=ts_code)
            result["cashflow"] = normalize_cashflow_df(raw)
        except Exception as e:
            result["cashflow"] = pd.DataFrame()
            warnings.append(f"hk_cashflow failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)

    # ------------------------------------------------------------------
    # Valuation inputs
    # ------------------------------------------------------------------

    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs for HK stocks from Tushare.

        Data sources:
          - hk_daily: current price (latest close)
          - hk_fina_indicator: EPS, BPS, ROE, margins, market cap, shares,
            total assets/liabilities/equity, PE/PB, end cash, etc.

        Note: HK fina_indicator returns structured columns (not key-value),
        making it a rich single-source for valuation metrics.
        """
        from src.data.tushare_client import tushare_client

        ts_code = self._ts_code(ticker)
        result = {}
        warnings = []

        # ── hk_daily: latest price ──
        try:
            end_date = self._today()
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            price_df = tushare_client.hk_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            if price_df is not None and not price_df.empty:
                latest = price_df.iloc[-1]
                result["current_price"] = latest.get("close")
        except Exception as e:
            warnings.append(f"hk_daily for price failed: {e}")

        # ── hk_fina_indicator: comprehensive financial metrics ──
        try:
            fina = tushare_client.hk_fina_indicator(ts_code=ts_code)
            if fina is not None and not fina.empty:
                # Sort by end_date descending to get the latest report
                fina = fina.sort_values("end_date", ascending=False)
                latest = fina.iloc[0]

                # Per-share metrics
                result["eps_ttm"] = latest.get("eps_ttm")
                result["basic_eps"] = latest.get("basic_eps")
                result["diluted_eps"] = latest.get("diluted_eps")
                result["book_value_per_share"] = latest.get("bps")

                # Profitability
                result["gross_margin"] = latest.get("gross_profit_ratio")
                result["net_margin"] = latest.get("net_profit_ratio")
                result["roe"] = latest.get("roe_avg")
                result["roa"] = latest.get("roa")

                # Shares & market cap
                if latest.get("hk_common_shares"):
                    result["shares_outstanding"] = float(latest["hk_common_shares"])
                if latest.get("total_market_cap"):
                    result["market_cap"] = float(latest["total_market_cap"])

                # Balance sheet items
                result["total_assets"] = latest.get("total_assets")
                result["total_debt"] = latest.get("total_liabilities")
                result["total_equity"] = latest.get("total_parent_equity")
                result["total_cash"] = latest.get("end_cash")
                result["debt_asset_ratio"] = latest.get("debt_asset_ratio")

                # Valuation multiples from API (cross-check reference)
                result["pe_ttm_api"] = latest.get("pe_ttm")
                result["pb_ttm_api"] = latest.get("pb_ttm")

                # Growth
                result["revenue_yoy"] = latest.get("operate_income_yoy")
                result["profit_yoy"] = latest.get("holder_profit_yoy")

                # Compute enterprise value = market_cap + total_debt - total_cash
                mc = result.get("market_cap")
                td = result.get("total_debt")
                tc = result.get("total_cash")
                if mc and td:
                    result["enterprise_value"] = (
                        float(mc) + float(td) - float(tc or 0)
                    )
        except Exception as e:
            warnings.append(f"hk_fina_indicator failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
