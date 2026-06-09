"""HK stock data fetcher — AKShare primary, Tushare supplement.

Data sources:
  - AKShare stock_hk_daily: price history (primary, free, no registration)
  - AKShare stock_hk_financial_indicator_em: financial ratios + market cap + shares
  - AKShare stock_hk_company_profile_em: company profile
  - AKShare stock_hk_valuation_comparison_em: peer valuation comparison
  - Tushare hk_basic / hk_daily / hk_fina_indicator: supplement (requires purchase)
  - Tushare moneyflow_hsgt / hk_hold: southbound capital flow (always available)

Fallback chain: AKShare → Tushare → empty result with warning
"""

from datetime import datetime, timedelta
from typing import Optional
import time
import logging

import pandas as pd

from src.data.base import BaseFetcher, FetchResult

logger = logging.getLogger(__name__)

# ── AKShare retry config ──
_AK_RETRY_COUNT = 3
_AK_RETRY_DELAY = 1.0


def _ak_retry(fn, *args, **kwargs):
    """Call an AKShare function with retry and timeout."""
    last_err = None
    for attempt in range(_AK_RETRY_COUNT):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            logger.warning("AKShare %s attempt %d failed: %s", fn.__name__, attempt + 1, e)
            time.sleep(_AK_RETRY_DELAY * (attempt + 1))
    raise last_err


def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class HKFetcher(BaseFetcher):
    """HK stock data fetcher with AKShare primary + Tushare supplement."""

    market = "HK"

    # ── Company info ──────────────────────────────────────────

    def fetch_company_info(self, ticker: str) -> FetchResult:
        warnings = []
        result = {
            "name": "", "sector": "", "industry": "",
            "market_cap": None, "description": "", "shares_outstanding": None,
        }

        # AKShare primary
        try:
            import akshare as ak
            profile = _ak_retry(ak.stock_hk_company_profile_em, symbol=ticker)
            if profile is not None and not profile.empty:
                row = profile.iloc[0]
                result["name"] = str(row.get("公司名称", ""))
                result["description"] = str(row.get("公司介绍", ""))
                result["industry"] = ""
        except Exception as e:
            warnings.append(f"AKShare company_profile failed: {e}")

        # Tushare supplement
        try:
            from src.data.tushare_client import tushare_client
            ts_code = f"{ticker}.HK" if not ticker.endswith(".HK") else ticker
            basic_df = tushare_client.hk_basic(ts_code=ts_code)
            if basic_df is not None and not basic_df.empty:
                row = basic_df.iloc[0]
                if not result["name"]:
                    result["name"] = row.get("name", "")
                if not result["industry"]:
                    result["industry"] = row.get("industry", "")
        except Exception as e:
            warnings.append(f"Tushare hk_basic failed: {e}")

        return FetchResult(data=result, source="akshare+tushare", success=True, warnings=warnings)

    # ── Price history ─────────────────────────────────────────

    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        import akshare as ak
        warnings = []

        try:
            df = _ak_retry(ak.stock_hk_daily, symbol=ticker, adjust="qfq")
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "date": "trade_date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "vol",
                    "amount": "amount",
                })
                if "trade_date" in df.columns:
                    df["trade_date"] = pd.to_datetime(df["trade_date"])
                    df = df.sort_values("trade_date")

                # Filter to requested period
                years = {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)
                cutoff = datetime.now() - timedelta(days=365 * years)
                if "trade_date" in df.columns:
                    df = df[df["trade_date"] >= pd.Timestamp(cutoff)]

                return FetchResult(data=df, source="akshare", success=True, warnings=warnings)
        except Exception as e:
            warnings.append(f"AKShare stock_hk_daily failed: {e}")

        # Tushare fallback
        try:
            from src.data.tushare_client import tushare_client
            from src.data.tushare_normalizer import normalize_price_df
            ts_code = f"{ticker}.HK" if not ticker.endswith(".HK") else ticker
            start_date = (datetime.now() - timedelta(days=365 * {"1y":1,"2y":2,"3y":3,"5y":5,"10y":10}[period])).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            raw = tushare_client.hk_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            df = normalize_price_df(raw)
            if df is not None and not df.empty:
                return FetchResult(data=df, source="tushare", success=True, warnings=warnings)
        except Exception as e:
            warnings.append(f"Tushare hk_daily fallback also failed: {e}")

        return FetchResult(success=False, warnings=warnings + ["No HK price data from any source"])

    # ── Financial statements ──────────────────────────────────

    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        """Fetch financial data from AKShare financial indicators + Tushare fallback."""
        result = {}
        warnings = []

        # AKShare financial indicators (rich single-source)
        try:
            import akshare as ak
            fina = _ak_retry(ak.stock_hk_financial_indicator_em, symbol=ticker)
            if fina is not None and not fina.empty:
                row = fina.iloc[0]
                revenue = _safe_float(row.get("营业总收入"))
                net_income = _safe_float(row.get("净利润"))
                eps = _safe_float(row.get("基本每股收益(元)"))
                bps = _safe_float(row.get("每股净资产(元)"))
                shares = _safe_float(row.get("已发行股本(股)"))
                ocf_per_share = _safe_float(row.get("每股经营现金流(元)"))
                equity = bps * shares if bps is not None and shares else None
                ocf = ocf_per_share * shares if ocf_per_share is not None and shares else None
                # Build income-like structure
                result["income"] = pd.DataFrame([{
                    "Total Revenue": revenue,
                    "Net Income": net_income,
                    "Diluted EPS": eps,
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": eps,
                    "bps": bps,
                    "ocf_per_share": ocf_per_share,
                    "gross_margin": _safe_float(row.get("销售毛利率(%)")),
                    "roe": _safe_float(row.get("股东权益回报率(%)")),
                    "roa": _safe_float(row.get("总资产回报率(%)")),
                }])
                # Balance sheet from the same source
                result["balance_sheet"] = pd.DataFrame([{
                    "Total Stockholder Equity": equity,
                    "total_shares": shares,
                    "market_cap_hkd": _safe_float(row.get("总市值(港元)")),
                    "hk_market_cap_hkd": _safe_float(row.get("港股市值(港元)")),
                }])
                result["cashflow"] = pd.DataFrame([{
                    "Operating Cash Flow": ocf,
                    "ocf_per_share": ocf_per_share,
                }])
        except Exception as e:
            warnings.append(f"AKShare financial_indicator failed: {e}")

        # Tushare fallback
        if not result.get("income", pd.DataFrame()).empty:
            # Already got data from AKShare
            pass
        else:
            try:
                from src.data.tushare_client import tushare_client
                from src.data.tushare_normalizer import (
                    normalize_income_df, normalize_balance_df, normalize_cashflow_df,
                )
                ts_code = f"{ticker}.HK" if not ticker.endswith(".HK") else ticker
                start = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y%m%d")

                try:
                    raw = tushare_client.hk_income(ts_code=ts_code, start_date=start)
                    result["income"] = normalize_income_df(raw)
                except Exception as e:
                    warnings.append(f"Tushare hk_income failed: {e}")

                try:
                    raw = tushare_client.hk_balancesheet(ts_code=ts_code, start_date=start)
                    result["balance_sheet"] = normalize_balance_df(raw)
                except Exception as e:
                    warnings.append(f"Tushare hk_balancesheet failed: {e}")

                try:
                    raw = tushare_client.hk_cashflow(ts_code=ts_code, start_date=start)
                    result["cashflow"] = normalize_cashflow_df(raw)
                except Exception as e:
                    warnings.append(f"Tushare hk_cashflow failed: {e}")
            except Exception as e:
                warnings.append(f"Tushare financials fallback failed: {e}")

        return FetchResult(data=result, source="akshare+tushare", success=True, warnings=warnings)

    # ── Valuation inputs ──────────────────────────────────────

    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs: price, EPS, BPS, shares, market cap, etc."""
        import akshare as ak
        result = {}
        warnings = []

        # ── Price: AKShare daily ──
        try:
            df = _ak_retry(ak.stock_hk_daily, symbol=ticker, adjust="qfq")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                result["current_price"] = _safe_float(latest.get("close"))
                result["price_date"] = str(latest.get("date", ""))
        except Exception as e:
            warnings.append(f"AKShare daily for price failed: {e}")

        # Tushare price fallback
        if not result.get("current_price"):
            try:
                from src.data.tushare_client import tushare_client
                ts_code = f"{ticker}.HK" if not ticker.endswith(".HK") else ticker
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                price_df = tushare_client.hk_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if price_df is not None and not price_df.empty:
                    if "trade_date" in price_df.columns:
                        price_df = price_df.sort_values("trade_date", ascending=False)
                    result["current_price"] = _safe_float(price_df.iloc[0].get("close"))
            except Exception as e:
                warnings.append(f"Tushare price fallback failed: {e}")

        # ── Financial indicators: AKShare ──
        try:
            fina = _ak_retry(ak.stock_hk_financial_indicator_em, symbol=ticker)
            if fina is not None and not fina.empty:
                row = fina.iloc[0]
                result["eps_ttm"] = _safe_float(row.get("基本每股收益(元)"))
                result["eps_ttm_basis"] = "akshare_latest_reported_eps"
                result["book_value_per_share"] = _safe_float(row.get("每股净资产(元)"))
                result["financial_currency"] = "HKD/RMB as reported by AKShare; verify before formal HK valuation"
                result["price_currency"] = "HKD"
                result["roe"] = _safe_float(row.get("股东权益回报率(%)"))
                result["roa"] = _safe_float(row.get("总资产回报率(%)"))
                result["net_margin"] = _safe_float(row.get("销售净利率(%)"))

                shares = _safe_float(row.get("已发行股本(股)"))
                if shares:
                    result["shares_outstanding"] = shares
                mcap = _safe_float(row.get("总市值(港元)"))
                if mcap:
                    result["market_cap"] = mcap
                rev = _safe_float(row.get("营业总收入"))
                if rev:
                    result["revenue_ttm"] = rev
                ni = _safe_float(row.get("净利润"))
                if ni:
                    result["net_income_ttm"] = ni
                result["ocf_per_share"] = _safe_float(row.get("每股经营现金流(元)"))
                result["dps_ttm_hkd"] = _safe_float(row.get("每股股息TTM(港元)"))
                result["payout_ratio"] = _safe_float(row.get("派息比率(%)"))
        except Exception as e:
            warnings.append(f"AKShare financial_indicator failed: {e}")

        # Tushare fina_indicator fallback
        if not result.get("eps_ttm"):
            try:
                from src.data.tushare_client import tushare_client
                ts_code = f"{ticker}.HK" if not ticker.endswith(".HK") else ticker
                stmt_start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
                fina_ts = tushare_client.hk_fina_indicator(ts_code=ts_code, start_date=stmt_start)
                if fina_ts is not None and not fina_ts.empty:
                    fina_ts = fina_ts.sort_values("end_date", ascending=False)
                    latest = fina_ts.iloc[0]
                    result["eps_ttm"] = _safe_float(latest.get("eps_ttm"))
                    result["book_value_per_share"] = _safe_float(latest.get("bps"))
                    result["roe"] = _safe_float(latest.get("roe_avg"))
                    result["roa"] = _safe_float(latest.get("roa"))
                    result["gross_margin"] = _safe_float(latest.get("gross_profit_ratio"))
                    if not result.get("shares_outstanding"):
                        result["shares_outstanding"] = _safe_float(latest.get("hk_common_shares"))
                    if not result.get("market_cap"):
                        result["market_cap"] = _safe_float(latest.get("total_market_cap"))
                    result["total_assets"] = _safe_float(latest.get("total_assets"))
                    # NOTE: hk_fina_indicator has no debt breakdown — this is total_liab, NOT interest-bearing debt
                    result["total_liab"] = _safe_float(latest.get("total_liabilities"))
                    result["total_equity"] = _safe_float(latest.get("total_parent_equity"))
                    result["total_cash"] = _safe_float(latest.get("end_cash"))
            except Exception as e:
                warnings.append(f"Tushare fina_indicator fallback failed: {e}")

        return FetchResult(data=result, source="akshare+tushare", success=True, warnings=warnings)
