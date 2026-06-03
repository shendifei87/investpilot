"""HK stock data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - hk_basic: company info
  - hk_daily: price history
  - hk_income / hk_balancesheet / hk_cashflow: financial statements
"""

from datetime import datetime, timedelta

from src.data.base import BaseTushareFetcher, FetchResult


class HKFetcher(BaseTushareFetcher):
    market = "HK"
    api_methods = {
        "daily": "hk_daily",
        "income": "hk_income",
        "balance_sheet": "hk_balancesheet",
        "cashflow": "hk_cashflow",
    }
    price_warning = "No HK price data returned"

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
        statement_start = self._start_date("3y")

        # ── hk_daily: latest price ──
        try:
            end_date = self._today()
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            price_df = tushare_client.hk_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date,
            )
            if price_df is not None and not price_df.empty:
                if "trade_date" in price_df.columns:
                    price_df = price_df.sort_values("trade_date", ascending=False)
                latest = price_df.iloc[0]
                result["current_price"] = latest.get("close")
        except Exception as e:
            warnings.append(f"hk_daily for price failed: {e}")

        # ── hk_fina_indicator: comprehensive financial metrics ──
        try:
            fina = tushare_client.hk_fina_indicator(ts_code=ts_code, start_date=statement_start)
            if fina is not None and not fina.empty:
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

                # Compute enterprise value
                ev = self._compute_ev(
                    result.get("market_cap"),
                    result.get("total_debt"),
                    result.get("total_cash"),
                )
                if ev is not None:
                    result["enterprise_value"] = ev
        except Exception as e:
            warnings.append(f"hk_fina_indicator failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
