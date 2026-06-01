"""A-share data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - stock_basic / stock_company: company info
  - daily: price history (OHLCV, unadjusted)
  - daily_basic: PE/PB/PS, market cap, total shares
  - income / balancesheet / cashflow: financial statements
  - fina_indicator: EPS, ROE, EBITDA, margins, etc.
"""

import pandas as pd
from datetime import datetime, timedelta
from src.data.base import BaseFetcher, FetchResult
from src.data.cache import fetch_and_cache
from config.ticker_rules import get_tushare_code


class AshareFetcher(BaseFetcher):
    market = "ASHARE"

    def _ts_code(self, ticker: str) -> str:
        return get_tushare_code(ticker, "ASHARE")

    def _today(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _start_date(self, period: str) -> str:
        years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)
        return (datetime.now() - timedelta(days=365 * years)).strftime("%Y%m%d")

    # ------------------------------------------------------------------
    # Company info
    # ------------------------------------------------------------------

    def fetch_company_info(self, ticker: str) -> FetchResult:
        """Fetch company info from Tushare stock_basic + stock_company."""
        from src.data.tushare_client import tushare_client

        warnings = []
        result = {
            "name": "", "sector": "", "industry": "",
            "description": "", "chairman": "", "employees": "",
            "province": "", "setup_date": "",
        }

        ts_code = self._ts_code(ticker)

        # Basic stock info (name, industry, list_date, etc.)
        try:
            basic_df = tushare_client.stock_basic(ts_code=ts_code)
            if basic_df is not None and not basic_df.empty:
                row = basic_df.iloc[0]
                result["name"] = row.get("name", "")
                result["industry"] = row.get("industry", "")
                result["area"] = row.get("area", "")
                result["market"] = row.get("market", "")
                result["list_date"] = row.get("list_date", "")
        except Exception as e:
            warnings.append(f"stock_basic failed: {e}")

        # Detailed company info (chairman, employees, description)
        try:
            company_df = tushare_client.stock_company(ts_code=ts_code)
            if company_df is not None and not company_df.empty:
                row = company_df.iloc[0]
                result["chairman"] = row.get("chairman", "")
                result["employees"] = row.get("employees", "")
                result["province"] = row.get("province", "")
                result["setup_date"] = row.get("setup_date", "")
                result["description"] = (
                    row.get("introduction", "")
                    or row.get("business_scope", "")
                    or row.get("mainbusiness", "")
                )
                result["website"] = row.get("website", "")
        except Exception as e:
            warnings.append(f"stock_company failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        """Fetch daily OHLCV from Tushare daily API.

        Tushare daily API returns unadjusted prices.
        Output is normalized with both Tushare native columns and
        akshare-compatible aliases (日期, 收盘, etc.).
        """
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import normalize_price_df

        ts_code = self._ts_code(ticker)
        start_date = self._start_date(period)
        end_date = self._today()

        try:
            raw_df = tushare_client.daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            df = normalize_price_df(raw_df)
            if df is not None and not df.empty:
                return FetchResult(data=df, source="tushare", success=True)
        except Exception as e:
            return FetchResult(success=False, warnings=[str(e)])

        return FetchResult(success=False, warnings=["No price data returned"])

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        """Fetch income/balance/cashflow/indicators from Tushare.

        Uses report_type=1 (合并报表, the default) and deduplicates
        by keeping the latest ann_date per end_date in the normalizer.
        """
        from src.data.tushare_client import tushare_client
        from src.data.tushare_normalizer import (
            normalize_income_df,
            normalize_balance_df,
            normalize_cashflow_df,
            normalize_fina_indicator_df,
        )

        ts_code = self._ts_code(ticker)
        result = {}
        warnings = []

        # Income statement
        try:
            raw = tushare_client.income(ts_code=ts_code)
            result["income"] = normalize_income_df(raw)
        except Exception as e:
            result["income"] = pd.DataFrame()
            warnings.append(f"income failed: {e}")

        # Balance sheet
        try:
            raw = tushare_client.balancesheet(ts_code=ts_code)
            result["balance_sheet"] = normalize_balance_df(raw)
        except Exception as e:
            result["balance_sheet"] = pd.DataFrame()
            warnings.append(f"balancesheet failed: {e}")

        # Cash flow
        try:
            raw = tushare_client.cashflow(ts_code=ts_code)
            result["cashflow"] = normalize_cashflow_df(raw)
        except Exception as e:
            result["cashflow"] = pd.DataFrame()
            warnings.append(f"cashflow failed: {e}")

        # Financial indicators (EPS, ROE, margins, etc.)
        try:
            raw = tushare_client.fina_indicator(ts_code=ts_code)
            result["financial_ratios"] = normalize_fina_indicator_df(raw)
        except Exception as e:
            warnings.append(f"fina_indicator failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)

    # ------------------------------------------------------------------
    # Valuation inputs
    # ------------------------------------------------------------------

    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs for A-share stocks.

        Data sources (all from Tushare):
          - daily_basic: current price, PE/PB/PS, market cap, total shares
          - fina_indicator: EPS, BPS, ROE, EBITDA
          - balancesheet (latest): total debt, cash

        Note on units per Tushare docs:
          - daily_basic.total_share: 万股
          - daily_basic.total_mv: 万元
          - daily_basic.circ_mv: 万元
        """
        from src.data.tushare_client import tushare_client

        ts_code = self._ts_code(ticker)
        result = {}
        warnings = []

        # ── daily_basic: price, PE, PB, shares, market cap ──
        try:
            db = tushare_client.daily_basic(ts_code=ts_code)
            if db is not None and not db.empty:
                # Sort by trade_date descending to get the latest row
                db = db.sort_values("trade_date", ascending=False)
                latest = db.iloc[0]
                result["current_price"] = latest.get("close")
                result["pe_ttm"] = latest.get("pe_ttm")
                result["pe"] = latest.get("pe")
                result["pb"] = latest.get("pb")
                result["ps_ttm"] = latest.get("ps_ttm")
                # total_share is in 万股 → convert to shares
                if latest.get("total_share"):
                    result["shares_outstanding"] = float(latest["total_share"]) * 10000
                # total_mv is in 万元 → convert to yuan
                if latest.get("total_mv"):
                    result["market_cap"] = float(latest["total_mv"]) * 10000
                if latest.get("circ_mv"):
                    result["circ_market_cap"] = float(latest["circ_mv"]) * 10000
        except Exception as e:
            warnings.append(f"daily_basic failed: {e}")

        # ── fina_indicator: EPS, BPS, ROE, EBITDA, margins ──
        try:
            fina = tushare_client.fina_indicator(ts_code=ts_code)
            if fina is not None and not fina.empty:
                latest = fina.iloc[0]
                result["eps_ttm"] = latest.get("eps")
                result["book_value_per_share"] = latest.get("bps")
                result["roe"] = latest.get("roe")
                result["ebitda"] = latest.get("ebitda")
                result["gross_margin"] = latest.get("grossprofit_margin")
                result["net_margin"] = latest.get("netprofit_margin")
                result["revenue_yoy"] = latest.get("or_yoy")
                result["profit_yoy"] = latest.get("netprofit_yoy")
        except Exception as e:
            warnings.append(f"fina_indicator failed: {e}")

        # ── Latest balance sheet for total_debt and cash ──
        try:
            bs = tushare_client.balancesheet(ts_code=ts_code)
            if bs is not None and not bs.empty:
                # Deduplicate: keep latest ann_date per end_date
                bs = bs.sort_values("ann_date", ascending=False).drop_duplicates(
                    subset=["end_date"], keep="first"
                )
                latest = bs.iloc[0]
                result["total_debt"] = latest.get("total_liab")
                result["total_cash"] = latest.get("money_cap")
                result["total_assets"] = latest.get("total_assets")
                result["total_equity"] = latest.get("total_hldr_eqy_exc_min_int")
                # Compute enterprise value = market_cap + total_debt - total_cash
                if result.get("market_cap") and result.get("total_debt"):
                    result["enterprise_value"] = (
                        result["market_cap"]
                        + float(result["total_debt"])
                        - float(result.get("total_cash", 0) or 0)
                    )
        except Exception as e:
            warnings.append(f"balancesheet for valuation failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
