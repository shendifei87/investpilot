"""Tests for src.analysis.financial — financial ratios, EQC, DuPont, valuation."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.financial import (
    _BALANCE_ALIASES,
    _CASHFLOW_ALIASES,
    _INCOME_ALIASES,
    _get_series,
    calc_all_valuation_ratios,
    calc_earnings_quality,
    calc_ev_ebitda,
    calc_financial_ratios,
    calc_pb,
    calc_pb_from_statements,
    calc_pe,
    calc_pe_forward,
    calc_pe_trailing,
    calc_peer_pe_table,
    calc_ps,
    calc_ps_from_statements,
    calc_revenue_growth,
    dupont_analysis,
    quarterly_arithmetic_check,
    validate_valuation_apple_to_apple,
)

# ── yfinance-format mock data factories ──────────────────────────


def _make_yfinance_income(years=3):
    """Create a mock yfinance income statement (items as index, dates as columns)."""
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    data = {
        "Total Revenue": [1000 * (1.1 ** i) for i in range(years)],
        "Gross Profit": [400 * (1.1 ** i) for i in range(years)],
        "Operating Income": [250 * (1.1 ** i) for i in range(years)],
        "Net Income": [150 * (1.1 ** i) for i in range(years)],
        "Interest Expense": [10 * (1.02 ** i) for i in range(years)],
        "Tax Provision": [20 * (1.03 ** i) for i in range(years)],
    }
    return pd.DataFrame(data, index=dates).T


def _make_yfinance_balance(years=3):
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    data = {
        "Total Stockholder Equity": [800 * (1.05 ** i) for i in range(years)],
        "Total Debt": [300 * (1.02 ** i) for i in range(years)],
        "Total Current Assets": [400 * (1.03 ** i) for i in range(years)],
        "Total Current Liabilities": [200 * (1.04 ** i) for i in range(years)],
        "Total Assets": [1200 * (1.05 ** i) for i in range(years)],
        "Cash And Cash Equivalents": [150 * (1.03 ** i) for i in range(years)],
        "Accounts Receivable": [100 * (1.06 ** i) for i in range(years)],
    }
    return pd.DataFrame(data, index=dates).T


def _make_yfinance_cashflow(years=3):
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    data = {
        "Operating Cash Flow": [200 * (1.1 ** i) for i in range(years)],
        "Capital Expenditure": [50 * (1.05 ** i) for i in range(years)],
        "Depreciation And Amortization": [30 * (1.05 ** i) for i in range(years)],
    }
    return pd.DataFrame(data, index=dates).T


# ── akshare-format mock data factories ────────────────────────────


def _make_akshare_income(years=3):
    """Create a mock akshare income statement (items as columns, dates in 报告期)."""
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    return pd.DataFrame({
        "报告期": dates,
        "营业总收入": [1000 * (1.1 ** i) for i in range(years)],
        "毛利润": [400 * (1.1 ** i) for i in range(years)],
        "营业利润": [250 * (1.1 ** i) for i in range(years)],
        "净利润": [150 * (1.1 ** i) for i in range(years)],
        "利息费用": [10 * (1.02 ** i) for i in range(years)],
        "所得税费用": [20 * (1.03 ** i) for i in range(years)],
    })


def _make_akshare_balance(years=3):
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    return pd.DataFrame({
        "报告期": dates,
        "所有者权益合计": [800 * (1.05 ** i) for i in range(years)],
        "负债合计": [300 * (1.02 ** i) for i in range(years)],
        "流动资产合计": [400 * (1.03 ** i) for i in range(years)],
        "流动负债合计": [200 * (1.04 ** i) for i in range(years)],
        "资产总计": [1200 * (1.05 ** i) for i in range(years)],
        "货币资金": [150 * (1.03 ** i) for i in range(years)],
        "应收账款": [100 * (1.06 ** i) for i in range(years)],
    })


def _make_akshare_cashflow(years=3):
    dates = pd.date_range("2023-01-01", periods=years, freq="YE")
    return pd.DataFrame({
        "报告期": dates,
        "经营活动产生的现金流量净额": [200 * (1.1 ** i) for i in range(years)],
        "购建固定资产无形资产和其他长期资产支付的现金": [50 * (1.05 ** i) for i in range(years)],
        "固定资产折旧、油气资产折耗、生产性生物资产折旧": [30 * (1.05 ** i) for i in range(years)],
    })


# ══════════════════════════════════════════════════════════════════
# Existing tests (unchanged)
# ══════════════════════════════════════════════════════════════════


class TestFinancialRatios:
    def test_margins(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        ratios = calc_financial_ratios(income, balance)
        assert "gross_margin" in ratios
        assert "operating_margin" in ratios
        assert "net_margin" in ratios

    def test_balance_ratios(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        ratios = calc_financial_ratios(income, balance)
        assert "debt_to_equity" in ratios
        assert "current_ratio" in ratios

    def test_empty_input(self):
        ratios = calc_financial_ratios(pd.DataFrame(), pd.DataFrame())
        assert ratios == {}


class TestRevenueGrowth:
    def test_yoy_growth(self):
        income = _make_yfinance_income(3)
        result = calc_revenue_growth(income)
        assert "revenue_yoy" in result
        growths = list(result["revenue_yoy"].values())
        valid = [g for g in growths if np.isfinite(g)]
        assert len(valid) >= 1
        assert all(0.05 < g < 0.20 for g in valid)

    def test_empty_input(self):
        result = calc_revenue_growth(pd.DataFrame())
        assert result == {}


class TestDuPontAnalysis:
    def test_three_factor_decomposition(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = dupont_analysis(income, balance)
        assert "roe" in result
        assert "net_margin" in result
        assert "asset_turnover" in result
        assert "financial_leverage" in result

    def test_roe_equals_product(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = dupont_analysis(income, balance)
        for date_key in result["roe"]:
            if np.isfinite(result["roe"][date_key]):
                product = (
                    result["net_margin"][date_key]
                    * result["asset_turnover"][date_key]
                    * result["financial_leverage"][date_key]
                )
                assert abs(result["roe"][date_key] - product) < 0.001


class TestEarningsQuality:
    def test_score_range(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        cashflow = _make_yfinance_cashflow()
        result = calc_earnings_quality(income, balance, cashflow)
        assert 0 <= result["total_score"] <= 100
        assert result["grade"] in ["A", "B", "C", "D"]

    def test_high_quality_company(self):
        dates = pd.date_range("2023-01-01", periods=3, freq="YE")
        income = pd.DataFrame({
            "Total Revenue": [1000, 1100, 1200],
            "Net Income": [200, 220, 250],
        }, index=dates).T
        balance = pd.DataFrame({
            "Total Assets": [2000, 2100, 2200],
            "Total Current Assets": [600, 650, 700],
            "Total Current Liabilities": [300, 310, 320],
            "Accounts Receivable": [100, 95, 90],  # AR declining → turnover improving
        }, index=dates).T
        cashflow = pd.DataFrame({
            "Operating Cash Flow": [300, 350, 400],
        }, index=dates).T

        result = calc_earnings_quality(income, balance, cashflow)
        assert result["total_score"] >= 50
        assert "components" in result

    def test_missing_cashflow(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = calc_earnings_quality(income, balance, cashflow=None)
        assert 0 <= result["total_score"] <= 100

    def test_receivables_trend_key(self):
        """EQC should use 'receivables_trend' key (not old 'liquidity_trend')."""
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = calc_earnings_quality(income, balance)
        assert "receivables_trend" in result["components"]
        assert "liquidity_trend" not in result["components"]

    def test_ar_turnover_with_receivables(self):
        """When AR data is available, should use AR turnover instead of current ratio."""
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()  # has Accounts Receivable
        result = calc_earnings_quality(income, balance)
        # With growing AR, turnover should be computed
        assert result["components"]["receivables_trend"]["score"] > 0


class TestQuarterlyArithmeticCheck:
    def test_reasonable_growth(self):
        result = quarterly_arithmetic_check(
            q1_actual=26, q1_last_year=25,
            full_year_estimate=112, full_year_last_year=100,
        )
        assert "error" not in result
        assert "REASONABLE" in result["feasibility"] or "CONSERVATIVE" in result["feasibility"]

    def test_unreasonable_growth(self):
        result = quarterly_arithmetic_check(
            q1_actual=30, q1_last_year=25,
            full_year_estimate=200, full_year_last_year=100,
        )
        assert "UNREASONABLE" in result["feasibility"] or "STRETCH" in result["feasibility"]

    def test_conservative_estimate(self):
        result = quarterly_arithmetic_check(
            q1_actual=30, q1_last_year=25,
            full_year_estimate=105, full_year_last_year=100,
        )
        assert "CONSERVATIVE" in result["feasibility"] or "OVERLY CONSERVATIVE" in result["feasibility"]

    def test_zero_last_year(self):
        result = quarterly_arithmetic_check(
            q1_actual=30, q1_last_year=0,
            full_year_estimate=100, full_year_last_year=0,
        )
        assert "error" in result

    def test_acceleration_warning(self):
        result = quarterly_arithmetic_check(
            q1_actual=26, q1_last_year=25,
            full_year_estimate=150, full_year_last_year=100,
        )
        if result.get("acceleration_note"):
            assert "WARNING" in result["acceleration_note"] or "accelerat" in result["acceleration_note"].lower()


# ══════════════════════════════════════════════════════════════════
# NEW: Valuation ratio tests
# ══════════════════════════════════════════════════════════════════


class TestCalcPE:
    def test_basic_pe(self):
        result = calc_pe(price=100, eps=5.0, label="TTM")
        assert result["pe"] == 20.0
        assert result["valid"] is True
        assert result["source"] == "calculated"

    def test_zero_eps(self):
        result = calc_pe(price=100, eps=0)
        assert result["valid"] is False
        assert result["pe"] is None

    def test_negative_eps(self):
        result = calc_pe(price=100, eps=-5.0)
        assert result["valid"] is False

    def test_none_inputs(self):
        result = calc_pe(price=None, eps=5.0)
        assert result["valid"] is False


class TestCalcPETrailing:
    def test_from_income(self):
        income = _make_yfinance_income()
        result = calc_pe_trailing(price=100, income=income, shares=10)
        assert result["valid"] is True
        assert result["eps_ttm"] > 0
        assert result["pe"] > 0

    def test_tushare_descending_period_uses_newest(self):
        income = pd.DataFrame({
            "报告期": pd.to_datetime(["2026-12-31", "2025-12-31"]),
            "净利润": [300.0, 100.0],
        })
        result = calc_pe_trailing(price=90, income=income, shares=10)
        assert result["valid"] is True
        assert result["eps_ttm"] == 30.0
        assert result["pe"] == 3.0

    def test_cumulative_ytd_ttm_bridge(self):
        """Quarterly Tushare-style YTD values should be converted to TTM."""
        income = pd.DataFrame({
            "报告期": pd.to_datetime(["2025-03-31", "2025-12-31", "2026-03-31"]),
            "净利润": [10.0, 100.0, 20.0],
        })
        result = calc_pe_trailing(price=100, income=income, shares=10)
        assert result["valid"] is True
        assert result["net_income"] == pytest.approx(110.0)
        assert result["eps_ttm"] == pytest.approx(11.0)
        assert result["pe"] == pytest.approx(9.09, rel=0.01)
        assert result["ttm_method"] == "ytd_plus_prior_fy_minus_prior_ytd"

    def test_no_income(self):
        result = calc_pe_trailing(price=100, income=pd.DataFrame(), shares=10)
        assert result["valid"] is False


class TestCalcPEForward:
    def test_forward_pe(self):
        result = calc_pe_forward(price=100, eps_estimate=6.0, year_label="2026E")
        assert result["pe"] == pytest.approx(100 / 6, rel=0.01)
        assert "Forward" in result["label"]
        assert result["valid"] is True


class TestCalcPB:
    def test_basic_pb(self):
        result = calc_pb(price=50, book_value_per_share=25)
        assert result["pb"] == 2.0
        assert result["source"] == "calculated"

    def test_zero_bvps(self):
        result = calc_pb(price=50, book_value_per_share=0)
        assert result["valid"] is False

    def test_from_statements(self):
        balance = _make_yfinance_balance()
        result = calc_pb_from_statements(price=100, balance=balance, shares=10)
        assert result["valid"] is True
        assert result["pb"] > 0

    def test_tushare_descending_period_uses_newest(self):
        balance = pd.DataFrame({
            "报告期": pd.to_datetime(["2026-12-31", "2025-12-31"]),
            "所有者权益合计": [500.0, 100.0],
        })
        result = calc_pb_from_statements(price=100, balance=balance, shares=10)
        assert result["valid"] is True
        assert result["book_value_per_share"] == 50.0
        assert result["pb"] == 2.0


class TestCalcPS:
    def test_basic_ps(self):
        result = calc_ps(price=100, revenue_per_share=50)
        assert result["ps"] == 2.0
        assert result["source"] == "calculated"

    def test_from_statements(self):
        income = _make_yfinance_income()
        result = calc_ps_from_statements(price=100, income=income, shares=10)
        assert result["valid"] is True
        assert result["ps"] > 0

    def test_tushare_descending_period_uses_newest(self):
        income = pd.DataFrame({
            "报告期": pd.to_datetime(["2026-12-31", "2025-12-31"]),
            "营业总收入": [1000.0, 200.0],
        })
        result = calc_ps_from_statements(price=100, income=income, shares=10)
        assert result["valid"] is True
        assert result["revenue_per_share"] == 100.0
        assert result["ps"] == 1.0

    def test_cumulative_ytd_revenue_ttm_bridge(self):
        income = pd.DataFrame({
            "报告期": pd.to_datetime(["2025-03-31", "2025-12-31", "2026-03-31"]),
            "营业总收入": [100.0, 1000.0, 250.0],
        })
        result = calc_ps_from_statements(price=100, income=income, shares=10)
        assert result["valid"] is True
        assert result["total_revenue"] == pytest.approx(1150.0)
        assert result["revenue_per_share"] == pytest.approx(115.0)
        assert result["ttm_method"] == "ytd_plus_prior_fy_minus_prior_ytd"


class TestCalcEvEbitda:
    def test_basic(self):
        result = calc_ev_ebitda(market_cap=1000, total_debt=200, cash=50, ebitda=150)
        assert result["ev_ebitda"] == pytest.approx(1150 / 150, rel=0.01)
        assert result["ev"] == 1150
        assert result["source"] == "calculated"

    def test_zero_ebitda(self):
        result = calc_ev_ebitda(market_cap=1000, total_debt=200, cash=50, ebitda=0)
        assert result["valid"] is False


class TestCalcAllValuationRatios:
    def test_all_ratios_with_cashflow(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        cashflow = _make_yfinance_cashflow()
        result = calc_all_valuation_ratios(
            price=100, shares=10, income=income,
            balance=balance, cashflow=cashflow,
            eps_estimate=5.0,
        )
        assert result["source"] == "calculated"
        assert result["pe_trailing"]["valid"] is True
        assert result["pe_forward"]["valid"] is True
        assert result["pb"]["valid"] is True
        assert result["ps"]["valid"] is True
        assert result["ev_ebitda"]["valid"] is True

    def test_ebitda_uses_real_da(self):
        """Verify EBITDA uses actual D&A from cashflow, not the 1.2x approximation."""
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        cashflow = _make_yfinance_cashflow()  # includes D&A
        result = calc_all_valuation_ratios(
            price=100, shares=10, income=income,
            balance=balance, cashflow=cashflow,
        )
        if result["ev_ebitda"]["valid"]:
            # Should NOT have the approximation warning
            assert not any("1.2" in w for w in result.get("warnings", []))

    def test_ebitda_fallback_without_cashflow(self):
        """Without cashflow, should fallback to OP*1.2 with a warning."""
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = calc_all_valuation_ratios(
            price=100, shares=10, income=income,
            balance=balance, cashflow=None,
        )
        if result["ev_ebitda"]["valid"]:
            assert any("1.2" in w for w in result.get("warnings", []))

    def test_cash_uses_real_cash(self):
        """Verify Cash uses actual Cash & Cash Equivalents, not CA-CL proxy."""
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()  # has Cash And Cash Equivalents
        cashflow = _make_yfinance_cashflow()
        result = calc_all_valuation_ratios(
            price=100, shares=10, income=income,
            balance=balance, cashflow=cashflow,
        )
        if result["ev_ebitda"]["valid"]:
            # Should NOT have the CA-CL proxy warning
            assert not any("Cash & Cash Equivalents not found" in w for w in result.get("warnings", []))

    def test_ev_does_not_use_total_liabilities_as_debt(self):
        """EV must use interest-bearing debt components, not total_liab."""
        date = pd.Timestamp("2026-12-31")
        income = pd.DataFrame({
            date: {
                "Total Revenue": 500.0,
                "Operating Income": 100.0,
                "Net Income": 50.0,
            }
        })
        balance = pd.DataFrame({
            date: {
                "Total Stockholder Equity": 1000.0,
                "total_liab": 9000.0,
                "Short Term Debt": 50.0,
                "Long Term Debt": 150.0,
                "money_cap": 100.0,
            }
        })
        cashflow = pd.DataFrame({
            date: {"Depreciation And Amortization": 20.0}
        })
        result = calc_all_valuation_ratios(
            price=10, shares=100, income=income, balance=balance, cashflow=cashflow,
        )
        assert result["ev_ebitda"]["valid"] is True
        assert result["ev_ebitda"]["total_debt"] == pytest.approx(200.0)
        assert result["ev_ebitda"]["cash"] == pytest.approx(100.0)
        assert result["ev_ebitda"]["ev"] == pytest.approx(1100.0)

    def test_lowercase_financial_fields_work(self):
        """HK/SEC-style lowercase columns should feed formal calculated ratios."""
        date = pd.Timestamp("2026-12-31")
        income = pd.DataFrame({
            "revenue": [1000.0],
            "operating_income": [250.0],
            "net_income": [200.0],
        }, index=[date])
        balance = pd.DataFrame({
            "total_hldr_eqy_exc_min_int": [500.0],
            "money_cap": [100.0],
            "st_borr": [50.0],
            "lt_borr": [100.0],
        }, index=[date])
        cashflow = pd.DataFrame({
            "depr_fa_coga_dpba": [30.0],
        }, index=[date])
        result = calc_all_valuation_ratios(
            price=20, shares=10, income=income, balance=balance, cashflow=cashflow,
        )
        assert result["pe_trailing"]["valid"] is True
        assert result["pe_trailing"]["eps_ttm"] == pytest.approx(20.0)
        assert result["pb"]["valid"] is True
        assert result["ps"]["valid"] is True
        assert result["ev_ebitda"]["valid"] is True

    def test_without_forward_eps(self):
        income = _make_yfinance_income()
        balance = _make_yfinance_balance()
        result = calc_all_valuation_ratios(
            price=100, shares=10, income=income,
            balance=balance,
        )
        assert "pe_forward" not in result
        assert result["pe_trailing"]["valid"] is True


class TestCalcPeerPETable:
    def test_basic_comparison(self):
        target = {"name": "Target", "price": 100, "eps_estimate": 5.0}
        peers = [
            {"name": "Peer A", "price": 80, "eps_estimate": 4.0},
            {"name": "Peer B", "price": 120, "eps_estimate": 6.0},
        ]
        result = calc_peer_pe_table(target, peers, pe_basis="forward")
        assert result["apple_to_apple"] is True
        assert result["source"] == "calculated"
        assert result["peer_median_pe"] > 0

    def test_trailing_basis(self):
        target = {"name": "Target", "price": 100, "eps": 5.0}
        peers = [
            {"name": "Peer A", "price": 80, "eps": 4.0},
        ]
        result = calc_peer_pe_table(target, peers, pe_basis="trailing")
        assert result["basis"] == "trailing"

    def test_insufficient_peers(self):
        target = {"name": "Target", "price": 100, "eps_estimate": 5.0}
        peers = []
        result = calc_peer_pe_table(target, peers, pe_basis="forward")
        assert "error" in result


class TestValidateAppleToApple:
    def test_mixed_trailing_forward_fails(self):
        comparisons = [
            {"metric": "pe", "basis": "TTM", "value": 20, "source": "calculated", "label": "TTM PE"},
            {"metric": "pe", "basis": "T+1", "value": 18, "source": "calculated", "label": "Forward PE"},
        ]
        result = validate_valuation_apple_to_apple(comparisons)
        assert result["passed"] is False
        assert any(v["type"] == "trailing_vs_forward_mixed" for v in result["violations"])

    def test_all_same_basis_passes(self):
        comparisons = [
            {"metric": "pe", "basis": "T+1", "value": 27, "source": "calculated", "label": "A T+1"},
            {"metric": "pe", "basis": "T+1", "value": 25, "source": "calculated", "label": "B T+1"},
        ]
        result = validate_valuation_apple_to_apple(comparisons)
        assert result["passed"] is True

    def test_non_calculated_source_fails(self):
        comparisons = [
            {"metric": "pe", "basis": "T+1", "value": 27, "source": "calculated", "label": "A"},
            {"metric": "pe", "basis": "T+1", "value": 25, "source": "news", "label": "B"},
        ]
        result = validate_valuation_apple_to_apple(comparisons)
        assert result["passed"] is False

    def test_single_entry_passes(self):
        result = validate_valuation_apple_to_apple([
            {"metric": "pe", "basis": "T+1", "value": 27, "source": "calculated", "label": "A"},
        ])
        assert result["passed"] is True


# ══════════════════════════════════════════════════════════════════
# NEW: Akshare alias resolution tests
# ══════════════════════════════════════════════════════════════════


class TestAkshareAliasResolution:
    def test_income_aliases(self):
        income = _make_akshare_income()
        ni = _get_series(income, "Net Income", _INCOME_ALIASES["Net Income"])
        assert ni is not None
        assert len(ni) == 3
        assert ni.iloc[-1] > 0

    def test_interest_expense_alias(self):
        income = _make_akshare_income()
        ie = _get_series(income, "Interest Expense", _INCOME_ALIASES["Interest Expense"])
        assert ie is not None
        assert len(ie) == 3

    def test_tax_provision_alias(self):
        income = _make_akshare_income()
        tax = _get_series(income, "Tax Provision", _INCOME_ALIASES["Tax Provision"])
        assert tax is not None
        assert len(tax) == 3

    def test_balance_cash_alias(self):
        balance = _make_akshare_balance()
        cash = _get_series(
            balance, "Cash And Cash Equivalents",
            _BALANCE_ALIASES["Cash And Cash Equivalents"],
        )
        assert cash is not None
        assert len(cash) == 3

    def test_balance_ar_alias(self):
        balance = _make_akshare_balance()
        ar = _get_series(
            balance, "Accounts Receivable",
            _BALANCE_ALIASES["Accounts Receivable"],
        )
        assert ar is not None
        assert len(ar) == 3

    def test_cashflow_da_alias(self):
        cashflow = _make_akshare_cashflow()
        da = _get_series(
            cashflow, "Depreciation And Amortization",
            _CASHFLOW_ALIASES["Depreciation And Amortization"],
        )
        assert da is not None
        assert len(da) == 3

    def test_calc_all_with_akshare_data(self):
        income = _make_akshare_income()
        balance = _make_akshare_balance()
        cashflow = _make_akshare_cashflow()
        result = calc_all_valuation_ratios(
            price=50, shares=10, income=income,
            balance=balance, cashflow=cashflow,
            eps_estimate=3.0,
        )
        assert result["source"] == "calculated"
        assert result["pe_trailing"]["valid"] is True
        # EBITDA should use real D&A, not approximation
        if result["ev_ebitda"]["valid"]:
            assert not any("1.2" in w for w in result.get("warnings", []))

    def test_eqc_with_akshare_data(self):
        income = _make_akshare_income()
        balance = _make_akshare_balance()
        cashflow = _make_akshare_cashflow()
        result = calc_earnings_quality(income, balance, cashflow)
        assert 0 <= result["total_score"] <= 100
        assert "receivables_trend" in result["components"]


# ══════════════════════════════════════════════════════════════════
# NEW: New field alias resolution (yfinance format)
# ══════════════════════════════════════════════════════════════════


class TestNewFieldAliasesYfinance:
    def test_cash_from_balance(self):
        balance = _make_yfinance_balance()
        cash = _get_series(
            balance, "Cash And Cash Equivalents",
            _BALANCE_ALIASES["Cash And Cash Equivalents"],
        )
        assert cash is not None
        assert len(cash) == 3
        assert cash.iloc[-1] > 0

    def test_ar_from_balance(self):
        balance = _make_yfinance_balance()
        ar = _get_series(
            balance, "Accounts Receivable",
            _BALANCE_ALIASES["Accounts Receivable"],
        )
        assert ar is not None

    def test_da_from_cashflow(self):
        cashflow = _make_yfinance_cashflow()
        da = _get_series(
            cashflow, "Depreciation And Amortization",
            _CASHFLOW_ALIASES["Depreciation And Amortization"],
        )
        assert da is not None
        assert da.iloc[-1] > 0

    def test_interest_expense_from_income(self):
        income = _make_yfinance_income()
        ie = _get_series(
            income, "Interest Expense",
            _INCOME_ALIASES["Interest Expense"],
        )
        assert ie is not None

    def test_tax_provision_from_income(self):
        income = _make_yfinance_income()
        tax = _get_series(
            income, "Tax Provision",
            _INCOME_ALIASES["Tax Provision"],
        )
        assert tax is not None
