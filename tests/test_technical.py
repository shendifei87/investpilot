"""Tests for technical analysis indicators (src/analysis/technical.py)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.technical import calc_ma, calc_macd, calc_rsi


def _make_close_series(n: int = 100, seed: int = 42) -> pd.Series:
    """Generate a realistic-looking price series."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.001, 0.02, n)
    prices = 100 * np.cumprod(1 + returns)
    return pd.Series(prices, name="Close")


class TestCalcMA:
    """Tests for moving average calculation."""

    def test_default_windows(self):
        close = _make_close_series(150)
        ma = calc_ma(close)
        assert list(ma.columns) == ["MA5", "MA20", "MA60", "MA120"]

    def test_custom_windows(self):
        close = _make_close_series(50)
        ma = calc_ma(close, windows=[3, 10])
        assert list(ma.columns) == ["MA3", "MA10"]

    def test_ma_values_correct(self):
        """Verify MA5 matches manual calculation."""
        close = pd.Series([10, 11, 12, 13, 14, 15, 16])
        ma = calc_ma(close, windows=[5])
        # MA5 at index 4: (10+11+12+13+14)/5 = 12.0
        assert ma["MA5"].iloc[4] == pytest.approx(12.0)
        # MA5 at index 5: (11+12+13+14+15)/5 = 13.0
        assert ma["MA5"].iloc[5] == pytest.approx(13.0)

    def test_first_n_minus_1_are_nan(self):
        close = pd.Series([float(i) for i in range(20)])
        ma = calc_ma(close, windows=[5])
        assert ma["MA5"].iloc[:4].isna().all()
        assert not ma["MA5"].iloc[4:].isna().any()

    def test_short_series(self):
        """MA with window > len(close) should be all NaN."""
        close = pd.Series([10, 11, 12])
        ma = calc_ma(close, windows=[10])
        assert ma["MA10"].isna().all()


class TestCalcRSI:
    """Tests for RSI calculation."""

    def test_rsi_range(self):
        close = _make_close_series(100)
        rsi = calc_rsi(close, period=14)
        # RSI should be between 0 and 100 (after warmup)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_uptrend_high_rsi(self):
        """Consistent uptrend should produce RSI > 70."""
        close = pd.Series([float(i) for i in range(50, 80)])  # Strictly increasing
        rsi = calc_rsi(close, period=14)
        # Last few values should be high
        assert rsi.iloc[-1] > 70

    def test_downtrend_low_rsi(self):
        """Consistent downtrend should produce RSI < 30."""
        close = pd.Series([float(i) for i in range(80, 50, -1)])  # Strictly decreasing
        rsi = calc_rsi(close, period=14)
        assert rsi.iloc[-1] < 30

    def test_constant_price(self):
        """Constant price should not crash (all gains/losses = 0)."""
        close = pd.Series([100.0] * 30)
        rsi = calc_rsi(close, period=14)
        # When avg_loss=0, RSI should be 100 (no losses)
        valid = rsi.dropna()
        assert (valid == 100.0).all()

    def test_first_value_is_nan(self):
        close = pd.Series([10, 11, 12, 13])
        rsi = calc_rsi(close, period=14)
        assert rsi.iloc[0] != rsi.iloc[0]  # NaN check


class TestCalcMACD:
    """Tests for MACD calculation."""

    def test_output_columns(self):
        close = _make_close_series(100)
        macd = calc_macd(close)
        assert list(macd.columns) == ["MACD", "Signal", "Histogram"]

    def test_histogram_is_difference(self):
        close = _make_close_series(100)
        macd = calc_macd(close)
        # Histogram = MACD - Signal
        diff = macd["MACD"] - macd["Signal"]
        pd.testing.assert_series_equal(
            macd["Histogram"], diff, check_names=False
        )

    def test_custom_parameters(self):
        close = _make_close_series(100)
        macd = calc_macd(close, fast=8, slow=21, signal=5)
        assert len(macd) == len(close)

    def test_short_series_no_crash(self):
        """Even with very short series, should not crash."""
        close = pd.Series([10, 11, 12])
        macd = calc_macd(close)
        assert len(macd) == 3
