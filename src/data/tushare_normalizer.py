"""Normalize Tushare DataFrames into formats compatible with InvestPilot's analysis pipeline.

The analysis layer (src/analysis/financial.py) expects financial DataFrames in one of two
formats handled by `_get_series()`:

  1. yfinance format: items as row index, dates as columns
  2. akshare format: items as column names, dates in a "报告期" column

We normalize Tushare output into akshare-compatible format (option 2), so that existing
Chinese aliases in financial.py resolve directly.  Tushare English column names are also
added as extra aliases in financial.py for safety.

Price DataFrames are normalized to include both Tushare native columns AND akshare-style
columns ("日期", "收盘") so that valuation.py's load_price_series() works.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _parse_date_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Convert a YYYYMMDD string column to datetime, in-place."""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")
    return df


def normalize_price_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare price data (daily/hk_daily/us_daily).

    Adds akshare-compatible column aliases so that both downstream code paths work:
      - valuation.py looks for "日期" or "trade_date" as date column
      - valuation.py looks for "收盘" or "Close" or "close" as price column

    Input columns (Tushare): ts_code, trade_date, open, high, low, close, vol, amount, ...
    Output: same columns + "日期" alias for trade_date + "收盘" alias for close
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()

    # Parse trade_date
    df = _parse_date_column(df, "trade_date")

    # Sort by date ascending
    if "trade_date" in df.columns:
        df = df.sort_values("trade_date").reset_index(drop=True)

    # Add akshare-compatible aliases
    if "trade_date" in df.columns:
        df["日期"] = df["trade_date"]
    if "close" in df.columns:
        df["收盘"] = df["close"]
    if "open" in df.columns:
        df["开盘"] = df["open"]
    if "high" in df.columns:
        df["最高"] = df["high"]
    if "low" in df.columns:
        df["最低"] = df["low"]
    if "vol" in df.columns:
        df["成交量"] = df["vol"]

    return df


def _normalize_financial_df(
    raw_df: pd.DataFrame,
    date_cols: tuple = ("end_date", "ann_date"),
    dedup: bool = True,
) -> pd.DataFrame:
    """Shared preamble for financial statement normalizers.

    Handles: null check → copy → dedup → date parse → 报告期 alias → sort.
    Returns an empty DataFrame if input is None/empty.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()

    # Deduplicate: keep the latest announcement per end_date
    if dedup and "ann_date" in df.columns and "end_date" in df.columns:
        df = df.sort_values("ann_date", ascending=False).drop_duplicates(
            subset=["end_date"], keep="first"
        )

    for col in date_cols:
        _parse_date_column(df, col)

    if "end_date" in df.columns:
        df["报告期"] = df["end_date"]

    if "报告期" in df.columns:
        df = df.sort_values("报告期", ascending=False).reset_index(drop=True)

    return df


def normalize_income_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare income statement.

    Input columns: ts_code, ann_date, f_ann_date, end_date, report_type, comp_type,
                   total_revenue, operating_cost, operate_profit, total_profit,
                   n_income, n_income_attr_p, eps, int_exp, income_tax, ...
    Output: adds "报告期" column from "end_date", computes "毛利润" if missing.
    """
    df = _normalize_financial_df(raw_df, date_cols=("end_date", "ann_date", "f_ann_date"))
    if df.empty:
        return df

    # Compute 毛利润 (gross profit): revenue - oper_cost
    # Note: per Tushare docs, oper_cost = 营业成本 (COGS), total_cogs = 营业总成本 (includes period expenses)
    # Gross profit should use oper_cost, NOT total_cogs
    if "毛利润" not in df.columns:
        revenue_col = "revenue" if "revenue" in df.columns else "total_revenue"
        cost_col = "oper_cost" if "oper_cost" in df.columns else None
        if revenue_col in df.columns and cost_col:
            df["毛利润"] = pd.to_numeric(df[revenue_col], errors="coerce") - pd.to_numeric(
                df[cost_col], errors="coerce"
            )

    # Add Chinese aliases for key fields (for _get_series compatibility)
    _add_alias(df, "total_revenue", "营业总收入")
    _add_alias(df, "operate_profit", "营业利润")
    _add_alias(df, "n_income", "净利润")
    _add_alias(df, "int_exp", "利息费用")
    _add_alias(df, "income_tax", "所得税费用")

    return df


def normalize_balance_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare balance sheet.

    Input columns: ts_code, ann_date, end_date, total_assets, total_cur_assets,
                   total_liab, total_cur_liab, total_hldr_eqy_exc_min_int,
                   money_cap/monetary_capital, accounts_receiv, st_borr, lt_borr, ...
    """
    df = _normalize_financial_df(raw_df)
    if df.empty:
        return df

    # Add Chinese aliases
    _add_alias(df, "total_hldr_eqy_exc_min_int", "所有者权益合计")
    _add_alias(df, "total_liab", "负债合计")
    _add_alias(df, "total_cur_assets", "流动资产合计")
    _add_alias(df, "total_cur_liab", "流动负债合计")
    _add_alias(df, "total_assets", "资产总计")
    _add_alias(df, "money_cap", "货币资金")
    _add_alias(df, "monetary_capital", "货币资金")
    _add_alias(df, "accounts_receiv", "应收账款")
    _add_alias(df, "st_borr", "短期借款")
    _add_alias(df, "lt_borr", "长期借款")
    _add_alias(df, "bond_payable", "应付债券")
    _add_alias(df, "non_cur_liab_due_1y", "一年内到期的非流动负债")

    return df


def normalize_cashflow_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare cash flow statement.

    Input columns: ts_code, ann_date, end_date, n_cashflow_act,
                   c_pay_acq_const_fiolta, depr_fa_coga_dpba, ...
    """
    df = _normalize_financial_df(raw_df)
    if df.empty:
        return df

    # Add Chinese aliases
    _add_alias(df, "n_cashflow_act", "经营活动产生的现金流量净额")
    _add_alias(df, "c_pay_acq_const_fiolta", "购建固定资产无形资产和其他长期资产支付的现金")
    _add_alias(df, "depr_fa_coga_dpba", "折旧与摊销")

    return df


def normalize_fina_indicator_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Tushare financial indicators.

    Input columns: ts_code, ann_date, end_date, eps, dt_eps, total_revenue_ps,
                   revenue_ps, capital_rese_ps, surplus_rese_ps, undistr_profit_ps,
                   extra_item_ps, adjusted_net_profit, roe, roe_waa, ...
    """
    # fina_indicator has no ann_date dedup needed (no overlapping reports)
    return _normalize_financial_df(raw_df, dedup=False)


def _add_alias(df: pd.DataFrame, source_col: str, alias: str) -> None:
    """Add a column alias if the source column exists and alias doesn't."""
    if source_col in df.columns and alias not in df.columns:
        df[alias] = df[source_col]
