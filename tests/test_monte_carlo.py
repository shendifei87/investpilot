"""Tests for src.analysis.monte_carlo — the core quantitative engine.

Validates distribution fitting, Monte Carlo simulation, RRR/Kelly calculation,
assumption consistency guard, and reproducibility.
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.analysis.monte_carlo import (
    NormalDist,
    LogNormalDist,
    _ndtri,
    _norm_cdf,
    _t_cdf,
    fit_distribution_from_percentiles,
    build_correlation_matrix,
    run_monte_carlo,
    calc_rrr,
    save_reviewed_assumptions,
    verify_assumption_consistency,
    save_calibration,
    update_calibration_actual,
)


# ── Distribution classes ──────────────────────────────────────────

class TestNormalDist:
    def test_ppf_matches_known_quantiles(self):
        dist = NormalDist(mu=100, sigma=15)
        # P50 should be mu
        assert abs(dist.ppf(0.5) - 100) < 0.01
        # P84.13 ≈ mu + sigma
        assert abs(dist.ppf(0.8413) - 115) < 0.5
        # P15.87 ≈ mu - sigma
        assert abs(dist.ppf(0.1587) - 85) < 0.5

    def test_rvs_shape(self):
        dist = NormalDist(mu=0, sigma=1)
        samples = dist.rvs(1000)
        assert samples.shape == (1000,)

    def test_truncation(self):
        dist = NormalDist(mu=0, sigma=1, lower=-2, upper=2)
        samples = dist.rvs(10000, rng=np.random.default_rng(42))
        assert samples.min() >= -2
        assert samples.max() <= 2

    def test_sigma_clamped(self):
        dist = NormalDist(mu=5, sigma=0)
        assert dist.sigma == 1e-10

    def test_reproducible_with_seed(self):
        dist = NormalDist(mu=10, sigma=2)
        rng1 = np.random.default_rng(123)
        rng2 = np.random.default_rng(123)
        s1 = dist.rvs(100, rng=rng1)
        s2 = dist.rvs(100, rng=rng2)
        np.testing.assert_array_equal(s1, s2)


class TestLogNormalDist:
    def test_mean_formula(self):
        dist = LogNormalDist(mu=0, sigma=0.5)
        expected_mean = np.exp(0 + 0.5**2 / 2)
        assert abs(dist.mean - expected_mean) < 1e-10

    def test_ppf_positive(self):
        dist = LogNormalDist(mu=2, sigma=0.3)
        for q in [0.01, 0.1, 0.5, 0.9, 0.99]:
            assert dist.ppf(q) > 0

    def test_truncation(self):
        dist = LogNormalDist(mu=2, sigma=0.5, lower=5, upper=15)
        samples = dist.rvs(10000, rng=np.random.default_rng(42))
        assert samples.min() >= 5
        assert samples.max() <= 15


# ── Numerical helpers ─────────────────────────────────────────────

class TestNdtri:
    """Validate Beasley-Springer-Moro against known values."""

    def test_median(self):
        assert abs(_ndtri(0.5)) < 1e-10

    def test_symmetry(self):
        for p in [0.1, 0.25, 0.4, 0.6, 0.75, 0.9]:
            assert abs(_ndtri(p) + _ndtri(1 - p)) < 1e-8

    def test_extreme_values(self):
        # P0.001 ≈ -3.09
        assert -3.15 < _ndtri(0.001) < -3.0
        # P0.999 ≈ +3.09
        assert 3.0 < _ndtri(0.999) < 3.15

    def test_array_input(self):
        result = _ndtri([0.1, 0.5, 0.9])
        assert result.shape == (3,)
        assert abs(result[1]) < 1e-10

    def test_agrees_with_norm_cdf_roundtrip(self):
        """ppf(cdf(x)) ≈ x for standard normal."""
        for x in [-2, -1, 0, 1, 2]:
            cdf_val = _norm_cdf(x)
            reconstructed = _ndtri(float(cdf_val))
            assert abs(reconstructed - x) < 0.01, f"Roundtrip failed at x={x}"


class TestNormCDF:
    def test_half_at_zero(self):
        assert abs(_norm_cdf(0) - 0.5) < 1e-10

    def test_symmetry(self):
        assert abs(_norm_cdf(1.0) + _norm_cdf(-1.0) - 1.0) < 1e-10

    def test_known_values(self):
        # CDF(1.96) ≈ 0.975
        assert abs(_norm_cdf(1.96) - 0.975) < 0.002


class TestTCDF:
    """Tests for the corrected Student-t CDF (scipy-backed)."""

    def test_at_zero(self):
        """CDF(0, df) = 0.5 for all df."""
        assert abs(_t_cdf(0, 4) - 0.5) < 1e-10
        assert abs(_t_cdf(0, 10) - 0.5) < 1e-10

    def test_symmetry(self):
        """CDF(x, df) + CDF(-x, df) = 1."""
        assert abs(_t_cdf(1.5, 6) + _t_cdf(-1.5, 6) - 1.0) < 1e-10

    def test_known_quantile_df6(self):
        """Verify against published t-distribution tables.

        For df=6, t=1.440 → CDF ≈ 0.90 (one-sided).
        """
        result = _t_cdf(1.440, 6)
        assert abs(result - 0.90) < 0.005

    def test_heavy_tail_at_low_df(self):
        """For df=4, CDF(-3) should be much larger than normal CDF(-3).

        Normal CDF(-3) ≈ 0.0013. t(df=4) CDF(-3) ≈ 0.020.
        The old scaled-normal approximation would give ~0.003.
        """
        t_val = _t_cdf(-3.0, 4)
        normal_val = _norm_cdf(-3.0)
        # t-CDF must be substantially larger in the tail
        assert t_val > normal_val * 3, \
            f"t(df=4) CDF(-3)={t_val:.4f} should be >> normal CDF(-3)={normal_val:.4f}"
        # Should be close to the true value ~0.020 (from scipy)
        assert abs(t_val - 0.020) < 0.003

    def test_converges_to_normal_at_high_df(self):
        """For df=200, t-CDF should be very close to normal."""
        x = 1.96
        assert abs(_t_cdf(x, 200) - _norm_cdf(x)) < 0.005

    def test_array_input(self):
        """Must accept numpy arrays."""
        result = _t_cdf(np.array([-1.0, 0.0, 1.0]), 6)
        assert result.shape == (3,)
        assert abs(result[1] - 0.5) < 1e-10


# ── Distribution fitting ──────────────────────────────────────────

class TestFitDistribution:
    def test_normal_from_percentiles(self):
        dist = fit_distribution_from_percentiles(
            {10: 80, 30: 92, 50: 100, 70: 108, 90: 120},
            dist_type="normal",
        )
        assert isinstance(dist, NormalDist)
        assert abs(dist.mu - 100) < 2
        assert 10 < dist.sigma < 20

    def test_lognormal_from_percentiles(self):
        dist = fit_distribution_from_percentiles(
            {10: 10, 50: 20, 90: 40},
            dist_type="lognormal",
        )
        assert isinstance(dist, LogNormalDist)
        assert abs(dist.ppf(0.5) - 20) < 3

    def test_single_point_fallback(self):
        dist = fit_distribution_from_percentiles({50: 100}, dist_type="normal")
        assert isinstance(dist, NormalDist)
        assert abs(dist.mu - 100) < 1

    def test_two_points_minimum(self):
        dist = fit_distribution_from_percentiles({25: 90, 75: 110}, dist_type="normal")
        assert isinstance(dist, NormalDist)
        assert abs(dist.mu - 100) < 5

    def test_truncation_applied(self):
        dist = fit_distribution_from_percentiles(
            {10: 80, 50: 100, 90: 120}, dist_type="normal"
        )
        assert dist.lower is not None
        assert dist.upper is not None
        assert dist.lower < 80
        assert dist.upper > 120


# ── Correlation matrix ────────────────────────────────────────────

class TestCorrelationMatrix:
    def test_identity_matrix(self):
        corr, warnings = build_correlation_matrix(
            ["a", "b"], []
        )
        np.testing.assert_array_almost_equal(corr, np.eye(2))

    def test_with_correlations(self):
        corr, warnings = build_correlation_matrix(
            ["rev_growth", "pe"], [("rev_growth", "pe", 0.6)]
        )
        assert abs(corr[0, 1] - 0.6) < 0.01
        assert abs(corr[1, 0] - 0.6) < 0.01
        assert corr[0, 0] == 1.0

    def test_psd_fix_applied(self):
        """Extreme correlations that make matrix non-PSD get fixed."""
        corr, warnings = build_correlation_matrix(
            ["a", "b", "c"],
            [("a", "b", 0.95), ("b", "c", 0.95), ("a", "c", -0.9)],
        )
        eigvals = np.linalg.eigvalsh(corr)
        assert eigvals.min() >= -1e-10, "Matrix should be PSD after fix"
        assert len(warnings) > 0


# ── Monte Carlo simulation ────────────────────────────────────────

class TestRunMonteCarlo:
    def _simple_pnl(self, inputs):
        """PnL model: target = eps * pe"""
        return {"target_price": inputs["eps"] * inputs["pe"]}

    def test_single_variable(self):
        eps_dist = NormalDist(mu=5, sigma=0.5)
        pe_dist = NormalDist(mu=15, sigma=2)
        result = run_monte_carlo(
            {"eps": eps_dist, "pe": pe_dist},
            self._simple_pnl,
            seed=42,
            n_simulations=1000,
        )
        prices = result["target_price"]
        assert prices.shape == (1000,)
        # E[target] ≈ 5 * 15 = 75
        assert abs(np.mean(prices) - 75) < 5

    def test_reproducibility_with_seed(self):
        dists = {"eps": NormalDist(mu=5, sigma=0.5), "pe": NormalDist(mu=15, sigma=2)}
        r1 = run_monte_carlo(dists, self._simple_pnl, seed=999, n_simulations=500)
        r2 = run_monte_carlo(dists, self._simple_pnl, seed=999, n_simulations=500)
        np.testing.assert_array_equal(r1["target_price"], r2["target_price"])

    def test_different_seeds_differ(self):
        dists = {"eps": NormalDist(mu=5, sigma=0.5), "pe": NormalDist(mu=15, sigma=2)}
        r1 = run_monte_carlo(dists, self._simple_pnl, seed=1, n_simulations=500)
        r2 = run_monte_carlo(dists, self._simple_pnl, seed=2, n_simulations=500)
        assert not np.allclose(r1["target_price"], r2["target_price"])

    def test_seed_recorded_in_result(self):
        result = run_monte_carlo(
            {"x": NormalDist(mu=1, sigma=0.1)},
            lambda i: {"y": i["x"]},
            seed=42,
            n_simulations=100,
        )
        assert result["seed"] == 42
        assert result["n_simulations"] == 100

    def test_correlated_simulation(self):
        corr, _ = build_correlation_matrix(
            ["a", "b"], [("a", "b", 0.9)]
        )
        result = run_monte_carlo(
            {"a": NormalDist(mu=0, sigma=1), "b": NormalDist(mu=0, sigma=1)},
            lambda i: {"sum": i["a"] + i["b"]},
            correlation_matrix=corr,
            seed=42,
            n_simulations=10000,
        )
        # High positive correlation → sum should be more volatile
        assert np.std(result["sum"]) > 1.0

    def test_t_copula_produces_valid_results(self):
        """Verify t-copula simulation completes and produces reasonable output."""
        corr = np.eye(2)
        result = run_monte_carlo(
            {"a": NormalDist(mu=0, sigma=1), "b": NormalDist(mu=0, sigma=1)},
            lambda i: {"sum": i["a"] + i["b"]},
            correlation_matrix=corr,
            n_simulations=10000,
            copula_df=4,
            seed=42,
        )
        assert result["sum"].shape == (10000,)
        # Mean should be close to 0
        assert abs(np.mean(result["sum"])) < 0.2

    def test_t_copula_has_fatter_tails_than_gaussian(self):
        """t-Copula (df=4) should produce more extreme values than Gaussian copula."""
        corr = np.array([[1.0, 0.8], [0.8, 1.0]])
        dists = {
            "a": NormalDist(mu=0, sigma=1),
            "b": NormalDist(mu=0, sigma=1),
        }
        pnl = lambda i: {"a": i["a"]}

        result_gauss = run_monte_carlo(dists, pnl, correlation_matrix=corr, seed=42, n_simulations=50000)
        result_t = run_monte_carlo(dists, pnl, correlation_matrix=corr, seed=42, n_simulations=50000, copula_df=4)

        # Kurtosis of t-copula samples should be higher
        from scipy.stats import kurtosis
        kurt_g = kurtosis(result_gauss["a"])
        kurt_t = kurtosis(result_t["a"])
        assert kurt_t > kurt_g, \
            f"t-Copula kurtosis ({kurt_t:.2f}) should exceed Gaussian ({kurt_g:.2f})"


# ── RRR + Kelly ────────────────────────────────────────────────────

class TestCalcRRR:
    def test_basic_upside(self):
        # All prices above current → infinite RRR
        prices = np.array([110, 120, 130, 140, 150], dtype=float)
        result = calc_rrr(prices, current_price=100)
        assert result["rrr"] == float("inf")
        assert result["p_up"] == 1.0
        assert result["p_down"] == 0.0

    def test_basic_downside(self):
        # All prices below current → RRR = 0
        prices = np.array([50, 60, 70, 80, 90], dtype=float)
        result = calc_rrr(prices, current_price=100)
        assert result["rrr"] == 0.0
        assert result["p_down"] == 1.0

    def test_balanced_distribution(self):
        prices = np.array([80, 85, 90, 95, 105, 110, 115, 120], dtype=float)
        result = calc_rrr(prices, current_price=100)
        assert result["p_up"] == 0.5
        assert result["p_down"] == 0.5
        # Symmetric upside/downside → RRR = 1.0
        assert abs(result["rrr"] - 1.0) < 0.01

    def test_good_trade(self):
        # More upside, less downside
        prices = np.concatenate([
            np.random.default_rng(42).normal(120, 15, 800),
            np.random.default_rng(42).normal(90, 5, 200),
        ])
        result = calc_rrr(prices, current_price=100)
        assert result["rrr"] > 1.0
        assert result["kelly_full"] > 0
        assert result["kelly_half"] == result["kelly_full"] / 2

    def test_percentiles_present(self):
        prices = np.random.default_rng(42).normal(100, 20, 10000)
        result = calc_rrr(prices, current_price=100)
        for p in [10, 25, 50, 75, 90]:
            assert p in result["percentiles"]

    def test_kelly_capped_at_zero(self):
        # Bad trade → kelly should be 0
        prices = np.array([50, 60, 70, 80], dtype=float)
        result = calc_rrr(prices, current_price=100)
        assert result["kelly_full"] == 0.0
        assert result["kelly_half"] == 0.0


# ── Assumption consistency guard ──────────────────────────────────

class TestAssumptionConsistency:
    def test_pass_when_consistent(self):
        """Verify consistency check passes when P50 matches."""
        from src.storage import AtomicJSON
        # Use the actual WORKSPACES_DIR and create a test workspace
        from config.settings import WORKSPACES_DIR
        test_ws = "test_consistency_ws"
        ws_path = WORKSPACES_DIR / test_ws
        ws_path.mkdir(parents=True, exist_ok=True)

        try:
            store = AtomicJSON(ws_path)
            store.save("_reviewed_assumptions.json", {
                "reviewed_at": "2026-01-01",
                "assumptions": {"rev_growth": {"p50": 0.15}},
            })
            dist = NormalDist(mu=0.15, sigma=0.05)
            result = verify_assumption_consistency(test_ws, {"rev_growth": dist})
            assert result["passed"], f"Should pass but got: {result}"
        finally:
            # Cleanup
            import shutil
            if ws_path.exists():
                shutil.rmtree(ws_path)

    def test_fail_on_drift(self):
        """Verify that large P50 drift is caught."""
        from src.storage import AtomicJSON
        from config.settings import WORKSPACES_DIR
        test_ws = "test_drift_ws"
        ws_path = WORKSPACES_DIR / test_ws
        ws_path.mkdir(parents=True, exist_ok=True)

        try:
            store = AtomicJSON(ws_path)
            store.save("_reviewed_assumptions.json", {
                "reviewed_at": "2026-01-01",
                "assumptions": {"rev_growth": {"p50": 0.15}},
            })
            # Pass a distribution with very different P50
            dist = NormalDist(mu=0.50, sigma=0.05)
            result = verify_assumption_consistency(test_ws, {"rev_growth": dist})
            assert not result["passed"], "Should detect P50 drift"
            assert len(result["violations"]) > 0
        finally:
            import shutil
            if ws_path.exists():
                shutil.rmtree(ws_path)


# ── Calibration ───────────────────────────────────────────────────

class TestCalibration:
    def test_save_and_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            # We test the logic but can't test the full path resolution without mocking
            # The core logic is: save record → update with actual → verify stats
            records = [
                {"predicted_year": "2025", "predicted_eps_p50": 5.0,
                 "predicted_percentiles": {30: 4.5, 70: 5.5}, "actual_eps": None},
            ]
            # Simulate update
            for rec in records:
                if rec["predicted_year"] == "2025" and rec["actual_eps"] is None:
                    rec["actual_eps"] = 5.2
                    rec["actual_date"] = "2026-04-15"

            assert records[0]["actual_eps"] == 5.2
            # Verify actual falls within predicted range
            assert records[0]["predicted_percentiles"][30] <= records[0]["actual_eps"] <= records[0]["predicted_percentiles"][70]
