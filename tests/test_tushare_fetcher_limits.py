"""Tests that Tushare fetchers use bounded API windows."""

import pandas as pd

from src.data.ashare_fetcher import AshareFetcher


class _FakeTushareClient:
    def __init__(self):
        self.calls = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return pd.DataFrame()

    def income(self, **kwargs):
        return self._record("income", **kwargs)

    def balancesheet(self, **kwargs):
        return self._record("balancesheet", **kwargs)

    def cashflow(self, **kwargs):
        return self._record("cashflow", **kwargs)

    def fina_indicator(self, **kwargs):
        return self._record("fina_indicator", **kwargs)

    def daily_basic(self, **kwargs):
        return self._record("daily_basic", **kwargs)


def test_financial_statements_pass_start_date(monkeypatch):
    fake = _FakeTushareClient()
    import src.data.tushare_client as client_module

    monkeypatch.setattr(client_module, "tushare_client", fake)

    fetcher = AshareFetcher()
    fetcher.fetch_financial_statements("600519.SH")

    calls = {name: kwargs for name, kwargs in fake.calls}
    for name in ("income", "balancesheet", "cashflow", "fina_indicator"):
        assert name in calls
        assert calls[name]["ts_code"] == "600519.SH"
        assert calls[name].get("start_date")


def test_ashare_valuation_inputs_pass_bounded_daily_basic_window(monkeypatch):
    fake = _FakeTushareClient()
    import src.data.tushare_client as client_module

    monkeypatch.setattr(client_module, "tushare_client", fake)

    fetcher = AshareFetcher()
    fetcher.fetch_valuation_inputs("600519.SH")

    calls = {name: kwargs for name, kwargs in fake.calls}
    assert calls["daily_basic"]["ts_code"] == "600519.SH"
    assert calls["daily_basic"].get("start_date")
    assert calls["daily_basic"].get("end_date")
    assert calls["fina_indicator"].get("start_date")
    assert calls["balancesheet"].get("start_date")
