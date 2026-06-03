"""US stock data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - us_basic: company info
  - us_daily: price history
  - us_income / us_balancesheet / us_cashflow: financial statements
"""

from datetime import datetime, timedelta

from src.data.base import BaseTushareFetcher, FetchResult


class USFetcher(BaseTushareFetcher):
    market = "US"
    api_methods = {
        "daily": "us_daily",
        "income": "us_income",
        "balance_sheet": "us_balancesheet",
        "cashflow": "us_cashflow",
    }
    price_warning = "No US price data returned"

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
        statement_start = self._start_date("3y")

        # ── us_daily_adj: price, shares, market cap ──
        try:
            end_date = self._today()
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            adj_df = tushare_client.us_daily_adj(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            if adj_df is not None and not adj_df.empty:
                if "trade_date" in adj_df.columns:
                    adj_df = adj_df.sort_values("trade_date", ascending=False)
                latest = adj_df.iloc[0]
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
                if "trade_date" in daily_df.columns:
                    daily_df = daily_df.sort_values("trade_date", ascending=False)
                latest = daily_df.iloc[0]
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
            fina = tushare_client.us_fina_indicator(ts_code=ts_code, start_date=statement_start)
            if fina is not None and not fina.empty:
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
        try:
            bs_df = tushare_client.us_balancesheet(ts_code=ts_code, start_date=statement_start)
            if bs_df is not None and not bs_df.empty and "ind_name" in bs_df.columns:
                liab_row = bs_df[bs_df["ind_name"].str.contains(
                    "总负债|total.liabil", case=False, na=False
                )]
                if not liab_row.empty:
                    liab_row = liab_row.sort_values("end_date", ascending=False)
                    val = liab_row.iloc[0].get("ind_value")
                    if val:
                        result["total_debt"] = float(val)

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
        ev = self._compute_ev(
            result.get("market_cap"),
            result.get("total_debt"),
            result.get("total_cash"),
        )
        if ev is not None:
            result["enterprise_value"] = ev

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
