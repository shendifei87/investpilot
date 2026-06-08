"""US stock data fetcher.

Data strategy:
  - AKShare: daily price history
  - SEC EDGAR companyfacts: financial statements and valuation raw inputs

InvestPilot does not rely on Tushare US modules because they may not be
available in the configured Tushare plan. All valuation ratios must still be
self-calculated downstream from these raw inputs.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd
import requests

from src.data.base import BaseFetcher, FetchResult


_AK_RETRY_COUNT = 3
_AK_RETRY_DELAY = 1.0
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _ak_retry(fn, *args, **kwargs):
    last_err = None
    for attempt in range(_AK_RETRY_COUNT):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_err = exc
            time.sleep(_AK_RETRY_DELAY * (attempt + 1))
    raise last_err


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sec_headers() -> dict[str, str]:
    user_agent = os.environ.get(
        "SEC_USER_AGENT",
        "InvestPilot research tool contact@example.com",
    )
    return {"User-Agent": user_agent}


def _request_json(url: str) -> dict[str, Any]:
    response = requests.get(url, headers=_sec_headers(), timeout=20)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _period_years(period: str) -> int:
    return {"1y": 1, "2y": 2, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)


class USFetcher(BaseFetcher):
    """US stock data fetcher with AKShare + SEC EDGAR primary sources."""

    market = "US"

    def _company_ticker_row(self, ticker: str) -> dict[str, Any] | None:
        ticker_upper = ticker.strip().upper()
        data = _request_json(_SEC_TICKERS_URL)
        for row in data.values():
            if isinstance(row, dict) and str(row.get("ticker", "")).upper() == ticker_upper:
                return row
        return None

    def _company_facts(self, ticker: str) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self._company_ticker_row(ticker)
        if not row:
            raise ValueError(f"SEC ticker mapping not found for {ticker}")
        cik = str(row.get("cik_str", "")).zfill(10)
        facts = _request_json(_SEC_FACTS_URL.format(cik=cik))
        return row, facts

    @staticmethod
    def _unit_records(
        facts: dict[str, Any],
        namespace: str,
        concept: str,
        units: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        concept_data = (
            facts.get("facts", {})
            .get(namespace, {})
            .get(concept, {})
            .get("units", {})
        )
        records: list[dict[str, Any]] = []
        for unit in units:
            raw_records = concept_data.get(unit, [])
            if isinstance(raw_records, list):
                records.extend(r for r in raw_records if isinstance(r, dict))
        return records

    def _latest_fact_value(
        self,
        facts: dict[str, Any],
        concepts: list[tuple[str, str]],
        units: tuple[str, ...],
        annual_only: bool = False,
    ) -> Optional[float]:
        candidates: list[dict[str, Any]] = []
        for namespace, concept in concepts:
            candidates.extend(self._unit_records(facts, namespace, concept, units))
        if annual_only:
            candidates = [
                r for r in candidates
                if str(r.get("form", "")).upper() == "10-K" or str(r.get("fp", "")).upper() == "FY"
            ]
        candidates = [r for r in candidates if _safe_float(r.get("val")) is not None and r.get("end")]
        if not candidates:
            return None
        candidates.sort(key=lambda r: (str(r.get("end", "")), str(r.get("filed", ""))), reverse=True)
        return _safe_float(candidates[0].get("val"))

    def _facts_to_frames(self, facts: dict[str, Any]) -> dict[str, pd.DataFrame]:
        revenue = self._latest_fact_value(
            facts,
            [
                ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                ("us-gaap", "Revenues"),
                ("us-gaap", "SalesRevenueNet"),
            ],
            ("USD",),
            annual_only=True,
        )
        net_income = self._latest_fact_value(
            facts,
            [("us-gaap", "NetIncomeLoss")],
            ("USD",),
            annual_only=True,
        )
        eps_diluted = self._latest_fact_value(
            facts,
            [("us-gaap", "EarningsPerShareDiluted")],
            ("USD/shares", "USD/share"),
            annual_only=True,
        )
        assets = self._latest_fact_value(
            facts,
            [("us-gaap", "Assets")],
            ("USD",),
        )
        liabilities = self._latest_fact_value(
            facts,
            [("us-gaap", "Liabilities")],
            ("USD",),
        )
        equity = self._latest_fact_value(
            facts,
            [
                ("us-gaap", "StockholdersEquity"),
                ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
            ],
            ("USD",),
        )
        cash = self._latest_fact_value(
            facts,
            [
                ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
                ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
            ],
            ("USD",),
        )
        ocf = self._latest_fact_value(
            facts,
            [("us-gaap", "NetCashProvidedByUsedInOperatingActivities")],
            ("USD",),
            annual_only=True,
        )
        capex = self._latest_fact_value(
            facts,
            [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment")],
            ("USD",),
            annual_only=True,
        )

        return {
            "income": pd.DataFrame([{
                "Total Revenue": revenue,
                "Net Income": net_income,
                "Diluted EPS": eps_diluted,
            }]),
            "balance_sheet": pd.DataFrame([{
                "Total Assets": assets,
                "Total Debt": liabilities,
                "Total Stockholder Equity": equity,
                "Cash And Cash Equivalents": cash,
            }]),
            "cashflow": pd.DataFrame([{
                "Operating Cash Flow": ocf,
                "Capital Expenditure": capex,
            }]),
        }

    def fetch_company_info(self, ticker: str) -> FetchResult:
        warnings = []
        result = {
            "name": "", "sector": "", "industry": "",
            "market_cap": None, "description": "",
            "shares_outstanding": None,
        }
        try:
            row = self._company_ticker_row(ticker)
            if row:
                result["name"] = row.get("title", "")
                result["ticker"] = row.get("ticker", ticker)
                result["cik"] = str(row.get("cik_str", "")).zfill(10)
        except Exception as exc:
            warnings.append(f"SEC company_tickers failed: {exc}")
        return FetchResult(data=result, source="sec_edgar", success=True, warnings=warnings)

    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        warnings = []
        try:
            import akshare as ak

            try:
                df = _ak_retry(ak.stock_us_daily, symbol=ticker, adjust="qfq")
            except TypeError:
                df = _ak_retry(ak.stock_us_daily, symbol=ticker)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "date": "trade_date",
                    "日期": "trade_date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "vol",
                    "成交量": "vol",
                    "amount": "amount",
                })
                if "trade_date" in df.columns:
                    df["trade_date"] = pd.to_datetime(df["trade_date"])
                    df = df.sort_values("trade_date")
                    cutoff = datetime.now() - timedelta(days=365 * _period_years(period))
                    df = df[df["trade_date"] >= pd.Timestamp(cutoff)]
                return FetchResult(data=df, source="akshare", success=True, warnings=warnings)
        except Exception as exc:
            warnings.append(f"AKShare stock_us_daily failed: {exc}")
        return FetchResult(success=False, source="akshare", warnings=warnings + ["No US price data returned"])

    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        try:
            _, facts = self._company_facts(ticker)
            return FetchResult(data=self._facts_to_frames(facts), source="sec_edgar", success=True)
        except Exception as exc:
            return FetchResult(
                data={"income": pd.DataFrame(), "balance_sheet": pd.DataFrame(), "cashflow": pd.DataFrame()},
                source="sec_edgar",
                success=False,
                warnings=[f"SEC companyfacts failed: {exc}"],
            )

    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        result: dict[str, Any] = {}
        warnings = []

        price_result = self.fetch_price_history(ticker, period="1y")
        if price_result.success and isinstance(price_result.data, pd.DataFrame) and not price_result.data.empty:
            df = price_result.data
            close_col = "close" if "close" in df.columns else "Close" if "Close" in df.columns else None
            if close_col:
                latest = df.iloc[-1]
                result["current_price"] = _safe_float(latest.get(close_col))
                result["price_date"] = str(latest.get("trade_date", ""))
        else:
            warnings.extend(price_result.warnings)

        try:
            _, facts = self._company_facts(ticker)
            shares = self._latest_fact_value(
                facts,
                [
                    ("dei", "EntityCommonStockSharesOutstanding"),
                    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
                ],
                ("shares",),
            )
            eps = self._latest_fact_value(
                facts,
                [("us-gaap", "EarningsPerShareDiluted")],
                ("USD/shares", "USD/share"),
                annual_only=True,
            )
            revenue = self._latest_fact_value(
                facts,
                [
                    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                    ("us-gaap", "Revenues"),
                    ("us-gaap", "SalesRevenueNet"),
                ],
                ("USD",),
                annual_only=True,
            )
            net_income = self._latest_fact_value(
                facts,
                [("us-gaap", "NetIncomeLoss")],
                ("USD",),
                annual_only=True,
            )
            equity = self._latest_fact_value(
                facts,
                [
                    ("us-gaap", "StockholdersEquity"),
                    ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
                ],
                ("USD",),
            )
            liabilities = self._latest_fact_value(
                facts,
                [("us-gaap", "Liabilities")],
                ("USD",),
            )
            cash = self._latest_fact_value(
                facts,
                [
                    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
                    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
                ],
                ("USD",),
            )

            if shares:
                result["shares_outstanding"] = shares
            if eps:
                result["eps_ttm"] = eps
            if revenue:
                result["revenue_ttm"] = revenue
            if net_income:
                result["net_income_ttm"] = net_income
            if equity and shares:
                result["book_value_per_share"] = equity / shares
            if liabilities:
                result["total_debt"] = liabilities
            if cash:
                result["total_cash"] = cash
            if result.get("current_price") and shares:
                result["market_cap"] = float(result["current_price"]) * shares
            if result.get("market_cap") and liabilities:
                result["enterprise_value"] = float(result["market_cap"]) + liabilities - float(cash or 0)
        except Exception as exc:
            warnings.append(f"SEC valuation inputs failed: {exc}")

        return FetchResult(data=result, source="akshare+sec_edgar", success=bool(result), warnings=warnings)
