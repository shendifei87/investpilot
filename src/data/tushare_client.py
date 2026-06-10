"""Unified Tushare Pro API client with retry and rate-limiting.

Usage:
    from src.data.tushare_client import tushare_client

    df = tushare_client.daily("600519.SH", start_date="20200101", end_date="20241231")
"""

import logging
import time

import pandas as pd

from config.settings import get_tushare_token

logger = logging.getLogger(__name__)

# Rate-limit: minimum seconds between consecutive API calls
_MIN_CALL_INTERVAL = 0.3


class TushareClient:
    """Thin wrapper around tushare.pro_api with lazy init, retry, and rate-limit."""

    def __init__(self):
        self._api = None
        self._last_call_ts = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_api(self):
        """Lazy-initialize the pro_api handle."""
        if self._api is not None:
            return self._api

        token = get_tushare_token()
        if not token:
            raise RuntimeError(
                "TUSHARE_TOKEN is not set. "
                "Export it as an environment variable or add it to your .env file. "
                "Get a token from https://tushare.pro"
            )

        import tushare as ts

        ts.set_token(token)
        self._api = ts.pro_api()
        logger.info("Tushare pro_api initialized successfully")
        return self._api

    def _throttle(self):
        """Simple rate-limiter between API calls."""
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)
        self._last_call_ts = time.monotonic()

    # Exceptions that are not worth retrying (logic / auth / input errors)
    _NON_RETRYABLE = (AttributeError, ValueError, TypeError, KeyError, PermissionError)

    def _call(self, method_name: str, **kwargs) -> pd.DataFrame:
        """Call a Tushare API method with retry (3 attempts) on transient errors."""
        api = self._get_api()
        fn = getattr(api, method_name, None)
        if fn is None:
            raise AttributeError(f"Tushare API has no method '{method_name}'")

        last_err = None
        for attempt in range(3):
            try:
                self._throttle()
                df = fn(**kwargs)
                return df if df is not None else pd.DataFrame()
            except self._NON_RETRYABLE:
                raise  # Don't retry logic / auth / input errors
            except Exception as e:
                last_err = e
                logger.warning(
                    "Tushare %s(%s) attempt %d failed: %s",
                    method_name, kwargs, attempt + 1, e,
                )
                time.sleep(1.0 * (attempt + 1))

        raise RuntimeError(
            f"Tushare {method_name}({kwargs}) failed after 3 attempts: {last_err}"
        )

    # ------------------------------------------------------------------
    # A-share data
    # ------------------------------------------------------------------

    def stock_basic(self, ts_code: str = "", **kwargs) -> pd.DataFrame:
        """Stock list / basic info.  ts_code optional — leave empty for all."""
        params = {**kwargs}
        if ts_code:
            params["ts_code"] = ts_code
        return self._call("stock_basic", **params)

    def stock_company(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """Listed company detailed info (chairman, employees, etc.)."""
        return self._call("stock_company", ts_code=ts_code, **kwargs)

    def daily(self, ts_code: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """A-share daily OHLCV."""
        return self._call("daily", ts_code=ts_code, start_date=start_date,
                          end_date=end_date, **kwargs)

    def income(self, ts_code: str, start_date: str = "", **kwargs) -> pd.DataFrame:
        """Income statement."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        return self._call("income", **params)

    def balancesheet(self, ts_code: str, start_date: str = "", **kwargs) -> pd.DataFrame:
        """Balance sheet."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        return self._call("balancesheet", **params)

    def cashflow(self, ts_code: str, start_date: str = "", **kwargs) -> pd.DataFrame:
        """Cash flow statement."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        return self._call("cashflow", **params)

    def fina_indicator(self, ts_code: str, start_date: str = "", **kwargs) -> pd.DataFrame:
        """Financial indicators (EPS, ROE, margins, etc.)."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        return self._call("fina_indicator", **params)

    def daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        """Daily basic indicators (PE, PB, PS, total_mv, circ_mv, etc.)."""
        params = {**kwargs}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._call("daily_basic", **params)

    # ------------------------------------------------------------------
    # HK stock data
    # ------------------------------------------------------------------

    def hk_basic(self, ts_code: str = "", **kwargs) -> pd.DataFrame:
        """HK stock list."""
        params = {**kwargs}
        if ts_code:
            params["ts_code"] = ts_code
        return self._call("hk_basic", **params)

    def hk_daily(self, ts_code: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """HK stock daily OHLCV."""
        return self._call("hk_daily", ts_code=ts_code, start_date=start_date,
                          end_date=end_date, **kwargs)

    def hk_income(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """HK income statement."""
        return self._call("hk_income", ts_code=ts_code, **kwargs)

    def hk_balancesheet(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """HK balance sheet."""
        return self._call("hk_balancesheet", ts_code=ts_code, **kwargs)

    def hk_cashflow(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """HK cash flow statement."""
        return self._call("hk_cashflow", ts_code=ts_code, **kwargs)

    def hk_fina_indicator(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """HK financial indicators (EPS, BPS, ROE, market cap, shares, etc.)."""
        return self._call("hk_fina_indicator", ts_code=ts_code, **kwargs)

    # ------------------------------------------------------------------
    # US stock data
    # ------------------------------------------------------------------

    def us_basic(self, ts_code: str = "", **kwargs) -> pd.DataFrame:
        """US stock list."""
        params = {**kwargs}
        if ts_code:
            params["ts_code"] = ts_code
        return self._call("us_basic", **params)

    def us_daily(self, ts_code: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """US stock daily OHLCV."""
        return self._call("us_daily", ts_code=ts_code, start_date=start_date,
                          end_date=end_date, **kwargs)

    def us_income(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """US income statement."""
        return self._call("us_income", ts_code=ts_code, **kwargs)

    def us_balancesheet(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """US balance sheet."""
        return self._call("us_balancesheet", ts_code=ts_code, **kwargs)

    def us_cashflow(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """US cash flow statement."""
        return self._call("us_cashflow", ts_code=ts_code, **kwargs)

    def us_fina_indicator(self, ts_code: str, **kwargs) -> pd.DataFrame:
        """US financial indicators (EPS, margins, ROE, etc.)."""
        return self._call("us_fina_indicator", ts_code=ts_code, **kwargs)

    def us_daily_adj(self, ts_code: str, start_date: str = "",
                     end_date: str = "", **kwargs) -> pd.DataFrame:
        """US daily adjusted (shares, market cap, adj factor)."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._call("us_daily_adj", **params)

    def hk_daily_adj(self, ts_code: str, start_date: str = "",
                     end_date: str = "", **kwargs) -> pd.DataFrame:
        """HK daily adjusted (shares, market cap, adj factor)."""
        params = {"ts_code": ts_code, **kwargs}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._call("hk_daily_adj", **params)


# Module-level singleton
tushare_client = TushareClient()
