"""Tests for src.analysis.valuation — DCF, Reverse DCF, PE Band."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.valuation import (
    dcf_model,
    reverse_dcf,
    forward_pe_band,
    load_price_series,
)


class TestDCFModel:
    def test_basic_dcf(self):
        """Cross-check with hand calculation.

        FCF=100, g=5%, WACC=10%, TG=3%, 5y, 100 shares.

        Year 1: FCF=105, PV=95.45
        Year 2: FCF=110.25, PV=91.12
        Year 3: FCF=115.76, PV=86.97
        Year 4: FCF=121.55, PV=83.01
        Year 5: FCF=127.63, PV=79.23
        PV_FCF = 435.78

        TV = 127.63 * 1.03 / (0.10 - 0.03) = 1877.28
        PV_TV = 1877.28 / 1.10^5 = 1164.82

        Total = 1600.60 / 100 = $16.01/share
        """
        result = dcf_model(
            fcf=100, growth_rate=0.05, wacc=0.10,
            terminal_growth=0.03, years=5, shares_outstanding=100,
        )
        assert "error" not in result
        assert abs(result["pv_fcf"] - 435.78) < 1.0
        assert abs(result["intrinsic_value_per_share"] - 16.0) < 0.5

    def test_zero_growth(self):
        result = dcf_model(
            fcf=100, growth_rate=0, wacc=0.10,
            terminal_growth=0.03, years=5, shares_outstanding=100,
        )
        assert "error" not in result
        # With zero growth, all projected FCFs should be 100
        assert all(fcf == 100 for fcf in result["projected_fcf"])

    def test_terminal_value_dominates(self):
        """For typical params, terminal value > sum of PV FCFs."""
        result = dcf_model(
            fcf=50, growth_rate=0.10, wacc=0.08,
            terminal_growth=0.03, years=10, shares_outstanding=1000,
        )
        assert result["pv_terminal"] > result["pv_fcf"]

    def test_wacc_equals_terminal_growth_raises(self):
        """WACC == terminal_growth causes division by zero in TV formula."""
        result = dcf_model(
            fcf=100, growth_rate=0.05, wacc=0.03,
            terminal_growth=0.03, years=5, shares_outstanding=100,
        )
        # Should get an error (ZeroDivisionError caught by try/except)
        assert "error" in result or np.isinf(result.get("terminal_value", 0))


class TestReverseDCF:
    def test_known_growth_rate(self):
        """Create a DCF with known g=15%, then reverse-DCF should recover ~15%."""
        result = dcf_model(
            fcf=100, growth_rate=0.15, wacc=0.10,
            terminal_growth=0.03, years=5, shares_outstanding=100,
        )
        price = result["intrinsic_value_per_share"]

        rev = reverse_dcf(
            current_price=price,
            shares_outstanding=100,
            base_fcf=100,
            wacc=0.10,
            terminal_growth=0.03,
            years=5,
        )
        assert "error" not in rev
        assert abs(rev["implied_growth_rate"] - 0.15) < 0.01

    def test_zero_price(self):
        rev = reverse_dcf(
            current_price=0, shares_outstanding=100,
            base_fcf=100, wacc=0.10,
        )
        assert "error" in rev

    def test_convergence(self):
        """Reverse DCF should converge within tolerance."""
        # High growth stock
        rev = reverse_dcf(
            current_price=50, shares_outstanding=1000,
            base_fcf=10, wacc=0.12,
            terminal_growth=0.03, years=5,
        )
        assert "error" not in rev
        assert -0.10 <= rev["implied_growth_rate"] <= 0.50

    def test_low_vs_high_price(self):
        """Lower price should imply lower growth than higher price."""
        rev_low = reverse_dcf(
            current_price=10, shares_outstanding=1000,
            base_fcf=50, wacc=0.10,
            terminal_growth=0.03, years=5,
            g_max=0.80,  # wider range to avoid both hitting ceiling
        )
        rev_high = reverse_dcf(
            current_price=200, shares_outstanding=1000,
            base_fcf=50, wacc=0.10,
            terminal_growth=0.03, years=5,
            g_max=0.80,
        )
        assert "error" not in rev_low
        assert "error" not in rev_high
        assert rev_low["implied_growth_rate"] < rev_high["implied_growth_rate"]


class TestForwardPEBand:
    def test_basic_band(self):
        dates = pd.date_range("2020-01-01", periods=300, freq="D")
        prices = pd.Series(
            np.random.default_rng(42).normal(100, 10, 300),
            index=dates,
        )
        result = forward_pe_band(prices, forward_eps=5.0)
        assert "error" not in result
        assert "bands" in result
        assert result["current_pe"] > 0
        assert result["forward_eps"] == 5.0
        for key in ["p10", "p25", "p50", "p75", "p90"]:
            assert key in result["bands"]

    def test_negative_eps_rejected(self):
        prices = pd.Series([100, 101, 102], dtype=float)
        result = forward_pe_band(prices, forward_eps=-5)
        assert "error" in result

    def test_empty_prices_rejected(self):
        result = forward_pe_band(pd.Series(dtype=float), forward_eps=5.0)
        assert "error" in result

    def test_percentile_ordering(self):
        dates = pd.date_range("2020-01-01", periods=500, freq="D")
        prices = pd.Series(
            np.random.default_rng(42).normal(100, 15, 500),
            index=dates,
        )
        result = forward_pe_band(prices, forward_eps=5.0)
        bands = result["bands"]
        assert bands["p10"] < bands["p25"] < bands["p50"] < bands["p75"] < bands["p90"]


class TestLoadPriceSeries:
    def test_empty_when_no_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            result = load_price_series(Path(tmp))
            assert result.empty

    def test_loads_yfinance_format(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "price_history.csv"
            df = pd.DataFrame({
                "Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "Close": [100, 101, 102],
            })
            df.to_csv(csv_path, index=False)
            result = load_price_series(Path(tmp))
            assert len(result) == 3
            assert result.iloc[-1] == 102
