"""US stock data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - us_basic: company info
  - us_daily: price history
  - us_income / us_balancesheet / us_cashflow: financial statements
"""

import pandas as pd
from datetime import datetime, timedelta
from src.data.base import BaseFetcher, FetchResult
from config.ticker_rules import get_tushare_code


class USFetcher(BaseFetcher):
    market = "US"

    def _ts_code(self, ticker: str) -> str:
        return get_tushare_code(ticker, "US")

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
            "market_cap": None, "description": "",
            "shares_outstanding": None,
        }

        ts_code = self._ts_code(ticker)

        try:
            basic_df = tushare_client.us_basic(ts_code=ts_code)
            if basic_df is not None and not basic_df.empty:
                row = basic_df.iloc[0]
                result["name"] = row.get("name", "")
                result["industry"] = row.get("industry", "")
        except Exception as e:
            warnings.append(f"us_basic failed: {e}")

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
            raw_df = tushare_client.us_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            df = normalize_price_df(raw_df)
            if df is not None and not df.empty:
                return FetchResult(data=df, source="tushare", success=True)
        except Exception as e:
            return FetchResult(success=False, warnings=[str(e)])

        return FetchResult(success=False, warnings=["No US price data returned"])

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
            raw = tushare_client.us_income(ts_code=ts_code)
            result["income"] = normalize_income_df(raw)
        except Exception as e:
            result["income"] = pd.DataFrame()
            warnings.append(f"us_income failed: {e}")

        try:
            raw = tushare_client.us_balancesheet(ts_code=ts_code)
            result["balance_sheet"] = normalize_balance_df(raw)
        except Exception as e:
            result["balance_sheet"] = pd.DataFrame()
            warnings.append(f"us_balancesheet failed: {e}")

        try:
            raw = tushare_client.us_cashflow(ts_code=ts_code)
            result["cashflow"] = normalize_cashflow_df(raw)
        except Exception as e:
            result["cashflow"] = pd.DataFrame()
            warnings.append(f"us_cashflow failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)

    # ------------------------------------------------------------------
    # Valuation inputs
    # ------------------------------------------------------------------

    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs for US stocks from Tushare.

        Data sources:
          - us_daily_adj: current price, total shares, market cap
          - us_daily (with optional fields): PE, PB
          - us_fina_indicator: EPS, margins, ROE, debt ratio

        Note: US fina_indicator does not include total_assets or
        total_liabilities as structured columns, so we use
        debt_asset_ratio as a reference and attempt to derive
        total_debt from us_balancesheet (key-value format).
        """
        from src.data.tushare_client import tushare_client

        ts_code = self._ts_code(ticker)
        result = {}
        warnings = []

        # ── us_daily_adj: price, shares, market cap ──
        try:
            end_date = self._today()
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            adj_df = tushare_client.us_daily_adj(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            if adj_df is not None and not adj_df.empty:
                latest = adj_df.iloc[-1]
                result["current_price"] = latest.get("close")
                if latest.get("total_share"):
                    result["shares_outstanding"] = float(latest["total_share"])
                if latest.get("total_mv"):
                    result["market_cap"] = float(latest["total_mv"])
        except Exception as e:
            warnings.append(f"us_daily_adj failed: {e}")

        # ── us_daily: PE, PB (optional fields) ──
        try:
            end_date = self._today()
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            daily_df = tushare_client.us_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            if daily_df is not None and not daily_df.empty:
                latest = daily_df.iloc[-1]
                # Optional fields may or may not be present
                if latest.get("pe"):
                    result["pe_ttm_api"] = latest.get("pe")
                if latest.get("pb"):
                    result["pb_ttm_api"] = latest.get("pb")
                # Fallback for current_price if us_daily_adj failed
                if not result.get("current_price"):
                    result["current_price"] = latest.get("close")
        except Exception as e:
            warnings.append(f"us_daily for PE/PB failed: {e}")

        # ── us_fina_indicator: EPS, margins, profitability ──
        try:
            fina = tushare_client.us_fina_indicator(ts_code=ts_code)
            if fina is not None and not fina.empty:
                # Sort by end_date descending for latest report
                fina = fina.sort_values("end_date", ascending=False)
                latest = fina.iloc[0]

                result["basic_eps"] = latest.get("basic_eps")
                result["diluted_eps"] = latest.get("diluted_eps")
                result["gross_margin"] = latest.get("gross_profit_ratio")
                result["net_margin"] = latest.get("net_profit_ratio")
                result["roe"] = latest.get("roe_avg")
                result["roa"] = latest.get("roa")
                result["debt_asset_ratio"] = latest.get("debt_asset_ratio")
                result["revenue_yoy"] = latest.get("operate_income_yoy")
                result["profit_yoy"] = latest.get("parent_holder_netprofit_yoy")
        except Exception as e:
            warnings.append(f"us_fina_indicator failed: {e}")

        # ── Estimate total_debt from balance sheet (key-value format) ──
        # us_balancesheet returns (ind_name, ind_value) rows per period.
        # We look for "total_liabilities" in the latest period.
        try:
            bs_df = tushare_client.us_balancesheet(ts_code=ts_code)
            if bs_df is not None and not bs_df.empty and "ind_name" in bs_df.columns:
                # Filter for total_liabilities
                liab_row = bs_df[bs_df["ind_name"].str.contains(
                    "总负债|total.liabil", case=False, na=False
                )]
                if not liab_row.empty:
                    # Take the latest end_date
                    liab_row = liab_row.sort_values("end_date", ascending=False)
                    val = liab_row.iloc[0].get("ind_value")
                    if val:
                        result["total_debt"] = float(val)

                # Also look for cash
                cash_row = bs_df[bs_df["ind_name"].str.contains(
                    "现金|cash", case=False, na=False
                )]
                if not cash_row.empty:
                    cash_row = cash_row.sort_values("end_date", ascending=False)
                    val = cash_row.iloc[0].get("ind_value")
                    if val:
                        result["total_cash"] = float(val)
        except Exception as e:
            warnings.append(f"us_balancesheet for debt/cash failed: {e}")

        # ── Compute enterprise value ──
        mc = result.get("market_cap")
        td = result.get("total_debt")
        tc = result.get("total_cash")
        if mc and td:
            result["enterprise_value"] = (
                float(mc) + float(td) - float(tc or 0)
            )

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
