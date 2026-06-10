"""A-share data fetcher — Tushare only.

All data sourced exclusively from Tushare Pro API:
  - stock_basic / stock_company: company info
  - daily: price history (OHLCV, unadjusted)
  - daily_basic: PE/PB/PS, market cap, total shares
  - income / balancesheet / cashflow: financial statements
  - fina_indicator: EPS, ROE, EBITDA, margins, etc.
"""

import math
from datetime import datetime, timedelta

from src.data.base import BaseTushareFetcher, FetchResult


def _ttm_from_cumulative_ytd(df, value_col: str):
    """Compute latest TTM from Tushare cumulative YTD rows.

    For non-year-end rows: TTM = latest YTD + prior FY - prior-year same-period YTD.
    Falls back to the latest annual row when a true TTM bridge is unavailable.
    """
    if df is None or df.empty or value_col not in df.columns or "end_date" not in df.columns:
        return None, "missing"

    tmp = df.copy()
    tmp["_end_str"] = tmp["end_date"].astype(str)
    tmp = tmp[tmp[value_col].notna() & tmp["_end_str"].str.len().ge(8)]
    if tmp.empty:
        return None, "missing"

    tmp = tmp.sort_values("_end_str")
    latest = tmp.iloc[-1]
    latest_end = str(latest["_end_str"])
    latest_value = float(latest[value_col])
    if latest_end.endswith("1231"):
        return latest_value, "latest_annual"

    year = int(latest_end[:4])
    prior_fy_end = f"{year - 1}1231"
    prior_same_end = f"{year - 1}{latest_end[4:]}"
    prior_fy = tmp[tmp["_end_str"] == prior_fy_end]
    prior_same = tmp[tmp["_end_str"] == prior_same_end]
    if not prior_fy.empty and not prior_same.empty:
        ttm = latest_value + float(prior_fy.iloc[-1][value_col]) - float(prior_same.iloc[-1][value_col])
        return ttm, "ytd_plus_prior_fy_minus_prior_ytd"

    annual = tmp[tmp["_end_str"].str.endswith("1231")]
    if not annual.empty:
        return float(annual.iloc[-1][value_col]), "latest_available_annual"

    return latest_value, "latest_period_fallback"


class AshareFetcher(BaseTushareFetcher):
    market = "ASHARE"
    api_methods = {
        "daily": "daily",
        "income": "income",
        "balance_sheet": "balancesheet",
        "cashflow": "cashflow",
        "fina_indicator": "fina_indicator",
    }
    price_warning = "No price data returned"

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
        end_date = self._today()
        recent_start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        statement_start = self._start_date("3y")

        # ── daily_basic: price, PE, PB, shares, market cap ──
        try:
            db = tushare_client.daily_basic(
                ts_code=ts_code,
                start_date=recent_start,
                end_date=end_date,
            )
            if db is not None and not db.empty:
                db = db.sort_values("trade_date", ascending=False)
                latest = db.iloc[0]
                result["current_price"] = latest.get("close")
                result["pe_ttm"] = latest.get("pe_ttm")
                result["pe"] = latest.get("pe")
                result["pb"] = latest.get("pb")
                result["ps_ttm"] = latest.get("ps_ttm")
                if latest.get("total_share"):
                    result["shares_outstanding"] = float(latest["total_share"]) * 10000
                if latest.get("total_mv"):
                    result["market_cap"] = float(latest["total_mv"]) * 10000
                if latest.get("circ_mv"):
                    result["circ_market_cap"] = float(latest["circ_mv"]) * 10000
        except Exception as e:
            warnings.append(f"daily_basic failed: {e}")

        # ── fina_indicator: EPS, BPS, ROE, EBITDA, margins ──
        try:
            fina = tushare_client.fina_indicator(ts_code=ts_code, start_date=statement_start)
            if fina is not None and not fina.empty:
                eps_ttm, eps_basis = _ttm_from_cumulative_ytd(fina, "eps")
                if "end_date" in fina.columns:
                    fina = fina.sort_values("end_date", ascending=False)
                    latest = fina.iloc[0]
                elif "ann_date" in fina.columns:
                    fina = fina.sort_values("ann_date", ascending=False)
                    latest = fina.iloc[0]
                else:
                    latest = fina.iloc[0]
                result["eps_ttm"] = eps_ttm if eps_ttm is not None else latest.get("eps")
                result["eps_ttm_basis"] = eps_basis
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
            bs = tushare_client.balancesheet(ts_code=ts_code, start_date=statement_start)
            if bs is not None and not bs.empty:
                bs = bs.sort_values("ann_date", ascending=False).drop_duplicates(
                    subset=["end_date"], keep="first"
                )
                latest = bs.iloc[0]
                # Interest-bearing debt ≠ total liabilities
                debt_components = [
                    latest.get("st_borr"),              # 短期借款
                    latest.get("lt_borr"),              # 长期借款
                    latest.get("bond_payable"),         # 应付债券
                    latest.get("non_cur_liab_due_1y"),  # 一年内到期的非流动负债
                ]
                valid_debt_components = []
                for value in debt_components:
                    try:
                        num = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(num):
                        valid_debt_components.append(num)
                total_debt = sum(valid_debt_components)
                result["total_debt"] = total_debt if total_debt > 0 else None
                result["total_cash"] = latest.get("money_cap")
                result["total_assets"] = latest.get("total_assets")
                result["total_equity"] = latest.get("total_hldr_eqy_exc_min_int")
                ev = self._compute_ev(
                    result.get("market_cap"),
                    result.get("total_debt"),
                    result.get("total_cash"),
                )
                if ev is not None:
                    result["enterprise_value"] = ev
        except Exception as e:
            warnings.append(f"balancesheet for valuation failed: {e}")

        return FetchResult(data=result, source="tushare", success=True, warnings=warnings)
