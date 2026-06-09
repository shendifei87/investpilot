"""Tests for src.data.tushare_normalizer — Tushare→akshare format conversion.

Covers: all 5 normalize functions, Chinese alias generation, date parsing,
deduplication, gross profit computation, empty/None input handling.
"""

import numpy as np
import pandas as pd
import pytest

from src.data.tushare_normalizer import (
    normalize_price_df,
    normalize_income_df,
    normalize_balance_df,
    normalize_cashflow_df,
    normalize_fina_indicator_df,
    _parse_date_column,
    _add_alias,
)


# ---------------------------------------------------------------------------
# _parse_date_column
# ---------------------------------------------------------------------------

class TestParseDateColumn:
    def test_parses_yyyymmdd_string(self):
        df = pd.DataFrame({"trade_date": ["20260115", "20260320"]})
        result = _parse_date_column(df, "trade_date")
        assert pd.api.types.is_datetime64_any_dtype(result["trade_date"])

    def test_coerces_invalid_to_nat(self):
        df = pd.DataFrame({"trade_date": ["20260115", "bad_date"]})
        result = _parse_date_column(df, "trade_date")
        assert result["trade_date"].isna().sum() == 1

    def test_noop_when_column_missing(self):
        df = pd.DataFrame({"other": [1, 2]})
        result = _parse_date_column(df, "trade_date")
        assert "trade_date" not in result.columns


# ---------------------------------------------------------------------------
# _add_alias
# ---------------------------------------------------------------------------

class TestAddAlias:
    def test_adds_alias_from_source(self):
        df = pd.DataFrame({"total_revenue": [100, 200]})
        _add_alias(df, "total_revenue", "营业总收入")
        assert "营业总收入" in df.columns
        assert list(df["营业总收入"]) == [100, 200]

    def test_skips_when_source_missing(self):
        df = pd.DataFrame({"other": [1]})
        _add_alias(df, "nonexistent", "别名")
        assert "别名" not in df.columns

    def test_skips_when_alias_exists(self):
        df = pd.DataFrame({"total_revenue": [100], "营业总收入": [999]})
        _add_alias(df, "total_revenue", "营业总收入")
        assert df["营业总收入"].iloc[0] == 999  # not overwritten


# ---------------------------------------------------------------------------
# normalize_price_df
# ---------------------------------------------------------------------------

class TestNormalizePriceDF:
    def _sample_price_df(self):
        return pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "trade_date": ["20260115", "20260116", "20260117"],
            "open": [1800.0, 1810.0, 1805.0],
            "high": [1820.0, 1830.0, 1815.0],
            "low": [1790.0, 1800.0, 1795.0],
            "close": [1810.0, 1825.0, 1800.0],
            "vol": [50000, 60000, 55000],
            "amount": [90000000, 100000000, 95000000],
        })

    def test_adds_chinese_aliases(self):
        df = normalize_price_df(self._sample_price_df())
        assert "日期" in df.columns
        assert "收盘" in df.columns
        assert "开盘" in df.columns
        assert "最高" in df.columns
        assert "最低" in df.columns
        assert "成交量" in df.columns

    def test_parses_trade_date(self):
        df = normalize_price_df(self._sample_price_df())
        assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])

    def test_sorted_ascending(self):
        df = normalize_price_df(self._sample_price_df())
        dates = df["trade_date"].tolist()
        assert dates == sorted(dates)

    def test_preserves_native_columns(self):
        df = normalize_price_df(self._sample_price_df())
        assert "close" in df.columns
        assert "open" in df.columns
        assert "vol" in df.columns

    def test_empty_input_returns_empty(self):
        assert normalize_price_df(pd.DataFrame()).empty

    def test_none_input_returns_empty(self):
        assert normalize_price_df(None).empty

    def test_alias_values_match_source(self):
        df = normalize_price_df(self._sample_price_df())
        assert list(df["收盘"]) == list(df["close"])
        assert list(df["开盘"]) == list(df["open"])


# ---------------------------------------------------------------------------
# normalize_income_df
# ---------------------------------------------------------------------------

class TestNormalizeIncomeDF:
    def _sample_income_df(self):
        return pd.DataFrame({
            "ts_code": ["600519.SH"] * 3,
            "ann_date": ["20260428", "20260428", "20250429"],
            "f_ann_date": ["20260428", "20260428", "20250429"],
            "end_date": ["20260331", "20251231", "20250331"],
            "report_type": ["1"] * 3,
            "total_revenue": [500, 2000, 480],
            "revenue": [480, 1900, 460],
            "oper_cost": [200, 800, 190],
            "operate_profit": [150, 600, 140],
            "n_income": [120, 500, 110],
            "int_exp": [10, 40, 9],
            "income_tax": [30, 120, 28],
        })

    def test_adds_report_period(self):
        df = normalize_income_df(self._sample_income_df())
        assert "报告期" in df.columns

    def test_adds_chinese_aliases(self):
        df = normalize_income_df(self._sample_income_df())
        assert "营业总收入" in df.columns
        assert "营业利润" in df.columns
        assert "净利润" in df.columns
        assert "利息费用" in df.columns
        assert "所得税费用" in df.columns

    def test_computes_gross_profit(self):
        df = normalize_income_df(self._sample_income_df())
        assert "毛利润" in df.columns
        # First row: revenue=480, oper_cost=200 → gross profit=280
        row = df[df["end_date"] == pd.Timestamp("2026-03-31")].iloc[0]
        assert abs(row["毛利润"] - 280) < 0.01

    def test_deduplicates_by_end_date(self):
        """When multiple ann_dates for same end_date, keeps latest ann_date."""
        raw = pd.DataFrame({
            "ts_code": ["600519.SH", "600519.SH"],
            "ann_date": ["20260420", "20260428"],
            "end_date": ["20260331", "20260331"],
            "total_revenue": [490, 500],  # restated
            "revenue": [470, 480],
            "oper_cost": [195, 200],
        })
        df = normalize_income_df(raw)
        # Should keep the row with ann_date=20260428 (latest)
        assert len(df) == 1
        assert df.iloc[0]["total_revenue"] == 500

    def test_sorted_descending_by_period(self):
        df = normalize_income_df(self._sample_income_df())
        periods = df["报告期"].tolist()
        assert periods == sorted(periods, reverse=True)

    def test_empty_input(self):
        assert normalize_income_df(pd.DataFrame()).empty

    def test_none_input(self):
        assert normalize_income_df(None).empty

    def test_gross_profit_uses_revenue_fallback(self):
        """When 'revenue' column missing, uses 'total_revenue'."""
        raw = pd.DataFrame({
            "ts_code": ["600519.SH"],
            "ann_date": ["20260428"],
            "end_date": ["20260331"],
            "total_revenue": [500],
            "oper_cost": [200],
        })
        df = normalize_income_df(raw)
        assert df.iloc[0]["毛利润"] == 300


# ---------------------------------------------------------------------------
# normalize_balance_df
# ---------------------------------------------------------------------------

class TestNormalizeBalanceDF:
    def _sample_balance_df(self):
        return pd.DataFrame({
            "ts_code": ["600519.SH"],
            "ann_date": ["20260428"],
            "end_date": ["20260331"],
            "total_assets": [10000],
            "total_cur_assets": [3000],
            "total_liab": [4000],
            "total_cur_liab": [1500],
            "total_hldr_eqy_exc_min_int": [6000],
            "money_cap": [1250],
            "monetary_capital": [1200],
            "accounts_receiv": [500],
            "st_borr": [800],
            "lt_borr": [1200],
            "bond_payable": [300],
            "non_cur_liab_due_1y": [100],
        })

    def test_adds_report_period(self):
        df = normalize_balance_df(self._sample_balance_df())
        assert "报告期" in df.columns

    def test_adds_all_chinese_aliases(self):
        df = normalize_balance_df(self._sample_balance_df())
        aliases = [
            "所有者权益合计", "负债合计", "流动资产合计", "流动负债合计",
            "资产总计", "货币资金", "应收账款", "短期借款", "长期借款",
            "应付债券", "一年内到期的非流动负债",
        ]
        for alias in aliases:
            assert alias in df.columns, f"Missing alias: {alias}"

    def test_alias_values_match_source(self):
        df = normalize_balance_df(self._sample_balance_df())
        assert df.iloc[0]["资产总计"] == 10000
        assert df.iloc[0]["负债合计"] == 4000
        assert df.iloc[0]["所有者权益合计"] == 6000
        assert df.iloc[0]["货币资金"] == 1250

    def test_deduplicates(self):
        raw = pd.DataFrame({
            "ts_code": ["600519.SH", "600519.SH"],
            "ann_date": ["20260420", "20260428"],
            "end_date": ["20260331", "20260331"],
            "total_assets": [9500, 10000],
        })
        df = normalize_balance_df(raw)
        assert len(df) == 1
        assert df.iloc[0]["total_assets"] == 10000

    def test_empty_input(self):
        assert normalize_balance_df(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# normalize_cashflow_df
# ---------------------------------------------------------------------------

class TestNormalizeCashflowDF:
    def _sample_cashflow_df(self):
        return pd.DataFrame({
            "ts_code": ["600519.SH"],
            "ann_date": ["20260428"],
            "end_date": ["20260331"],
            "n_cashflow_act": [800],
            "c_pay_acq_const_fiolta": [200],
            "depr_fa_coga_dpba": [150],
        })

    def test_adds_report_period(self):
        df = normalize_cashflow_df(self._sample_cashflow_df())
        assert "报告期" in df.columns

    def test_adds_chinese_aliases(self):
        df = normalize_cashflow_df(self._sample_cashflow_df())
        assert "经营活动产生的现金流量净额" in df.columns
        assert "购建固定资产无形资产和其他长期资产支付的现金" in df.columns
        assert "折旧与摊销" in df.columns

    def test_alias_values_match(self):
        df = normalize_cashflow_df(self._sample_cashflow_df())
        assert df.iloc[0]["经营活动产生的现金流量净额"] == 800
        assert df.iloc[0]["折旧与摊销"] == 150

    def test_deduplicates(self):
        raw = pd.DataFrame({
            "ts_code": ["600519.SH", "600519.SH"],
            "ann_date": ["20260420", "20260428"],
            "end_date": ["20260331", "20260331"],
            "n_cashflow_act": [750, 800],
        })
        df = normalize_cashflow_df(raw)
        assert len(df) == 1
        assert df.iloc[0]["n_cashflow_act"] == 800

    def test_empty_input(self):
        assert normalize_cashflow_df(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# normalize_fina_indicator_df
# ---------------------------------------------------------------------------

class TestNormalizeFinaIndicatorDF:
    def _sample_fina_df(self):
        return pd.DataFrame({
            "ts_code": ["600519.SH"] * 2,
            "ann_date": ["20260428", "20260428"],
            "end_date": ["20260331", "20251231"],
            "eps": [12.0, 45.0],
            "roe": [0.15, 0.30],
        })

    def test_adds_report_period(self):
        df = normalize_fina_indicator_df(self._sample_fina_df())
        assert "报告期" in df.columns

    def test_sorted_descending(self):
        df = normalize_fina_indicator_df(self._sample_fina_df())
        assert df.iloc[0]["end_date"] > df.iloc[1]["end_date"]

    def test_preserves_numeric_columns(self):
        df = normalize_fina_indicator_df(self._sample_fina_df())
        assert df.iloc[0]["eps"] == 12.0

    def test_empty_input(self):
        assert normalize_fina_indicator_df(pd.DataFrame()).empty
