from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.stats import t as t_dist

from config.settings import MONTE_CARLO_SIMULATIONS, WORKSPACES_DIR
from src.analysis._base import resolve_workspace_path
from src.storage import AtomicJSON

# ──────────────────────────────────────────────
#  Distribution classes
# ──────────────────────────────────────────────


class NormalDist:
    """Pure numpy normal distribution with optional truncation."""

    def __init__(self, mu: float, sigma: float, lower: float = None, upper: float = None):
        self.mu = mu
        self.sigma = max(sigma, 1e-10)
        self.lower = lower
        self.upper = upper

    def rvs(self, size: int, rng: np.random.Generator | None = None) -> np.ndarray:
        _rng = rng or np.random.default_rng()
        samples = _rng.normal(self.mu, self.sigma, size=size)
        if self.lower is not None:
            samples = np.maximum(samples, self.lower)
        if self.upper is not None:
            samples = np.minimum(samples, self.upper)
        return samples

    def ppf(self, q):
        q = np.asarray(q, dtype=float)
        out = self.mu + self.sigma * _ndtri(q)
        if self.lower is not None:
            out = np.maximum(out, self.lower)
        if self.upper is not None:
            out = np.minimum(out, self.upper)
        return out

    @property
    def mean(self):
        return self.mu

    @property
    def std(self):
        return self.sigma


class LogNormalDist:
    """Lognormal distribution — strictly positive, right-skewed (PE, PB, market cap).

    Supports optional truncation to prevent runaway right tails.
    """

    def __init__(self, mu: float, sigma: float, lower: float = None, upper: float = None):
        self.mu = mu
        self.sigma = max(sigma, 1e-10)
        self.lower = lower
        self.upper = upper

    def rvs(self, size: int, rng: np.random.Generator | None = None) -> np.ndarray:
        _rng = rng or np.random.default_rng()
        samples = _rng.lognormal(self.mu, self.sigma, size=size)
        if self.lower is not None:
            samples = np.maximum(samples, self.lower)
        if self.upper is not None:
            samples = np.minimum(samples, self.upper)
        return samples

    def ppf(self, q):
        q = np.asarray(q, dtype=float)
        out = np.exp(self.mu + self.sigma * _ndtri(q))
        if self.lower is not None:
            out = np.maximum(out, self.lower)
        if self.upper is not None:
            out = np.minimum(out, self.upper)
        return out

    @property
    def mean(self):
        return np.exp(self.mu + self.sigma**2 / 2)

    @property
    def std(self):
        return self.mean * np.sqrt(np.exp(self.sigma**2) - 1)


# ──────────────────────────────────────────────
#  Numerical helpers
# ──────────────────────────────────────────────


def _ndtri(p):
    """Normal inverse CDF (Beasley-Springer-Moro, pure numpy, array-safe)."""
    p = np.asarray(p, dtype=float)
    p = np.clip(p, 1e-10, 1 - 1e-10)

    a = np.array(
        [
            -3.969683028665376e01,
            2.209460984245205e02,
            -2.759285104469687e02,
            1.383577518672690e02,
            -3.066479806614716e01,
            2.506628277459239e00,
        ]
    )
    b = np.array(
        [
            -5.447609879822406e01,
            1.615858368580409e02,
            -1.556989798598866e02,
            6.680131188771972e01,
            -1.328068155288572e01,
        ]
    )
    c = np.array(
        [
            -7.784894002430293e-03,
            -3.223964580411365e-01,
            -2.400758277161838e00,
            -2.549732539343734e00,
            4.374664141464968e00,
            2.938163982698783e00,
        ]
    )
    d = np.array(
        [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    )

    p_low = 0.02425
    p_high = 1 - p_low
    x = np.zeros_like(p)

    mask = p < p_low
    if np.any(mask):
        q = np.sqrt(-2 * np.log(p[mask]))
        x[mask] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )

    mask = (p >= p_low) & (p <= p_high)
    if np.any(mask):
        q = p[mask] - 0.5
        r = q * q
        x[mask] = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )

    mask = p > p_high
    if np.any(mask):
        q = np.sqrt(-2 * np.log(1 - p[mask]))
        x[mask] = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )

    return x


def _norm_cdf(x):
    """Standard normal CDF via scipy.stats.norm (accurate across full domain)."""
    return norm.cdf(x)


def _t_cdf(x, df):
    """Student-t CDF via scipy.stats.t.

    Accurate for all df values including low df (3-6) where tail
    dependency matters most for t-Copula modeling.

    The previous implementation used a scaled-normal approximation that
    severely underestimated tail probabilities at low df (e.g. 3.5x error
    at df=6, x=-3). This is the mathematically correct implementation.
    """
    return t_dist.cdf(x, df)


def _nearest_psd_cholesky(
    matrix: np.ndarray, epsilon: float = 1e-10
) -> np.ndarray:
    """Cholesky decomposition with nearest-PSD fallback.

    If the input matrix is not positive-definite, applies an eigendecomposition
    fix (clip eigenvalues to *epsilon*, reconstruct, normalize diagonal) and
    retries.  If that also fails, falls back to the identity matrix (independent
    draws) and emits a warning.

    Returns the lower-triangular Cholesky factor *L*.
    """
    # Fast path — matrix is already PD
    try:
        return np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError:
        pass

    # Eigendecomposition fix
    n = matrix.shape[0]
    try:
        eigvals, eigvecs = np.linalg.eigh(matrix)
        eigvals = np.maximum(eigvals, epsilon)
        fixed = eigvecs @ np.diag(eigvals) @ eigvecs.T
        d = np.sqrt(np.diag(fixed))
        d[d == 0] = 1.0  # guard against zero diagonal
        fixed = fixed / np.outer(d, d)
        return np.linalg.cholesky(fixed)
    except np.linalg.LinAlgError:
        logger.warning(
            "Correlation matrix not PD after nearest-PSD fix; "
            "falling back to independent draws (identity matrix)"
        )
        return np.eye(n)


# ──────────────────────────────────────────────
#  Distribution fitting
# ──────────────────────────────────────────────


def _wls_fit(z_scores: np.ndarray, values: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Weighted least-squares: values = intercept + slope * z_scores."""
    W = np.diag(weights)
    X = np.column_stack([np.ones(len(z_scores)), z_scores])
    beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ values)
    return float(beta[0]), float(beta[1])


def fit_distribution_from_percentiles(
    percentiles: dict,
    dist_type: str = "normal",
    direction: str = "higher_is_better",
) -> NormalDist | LogNormalDist:
    """Fit a distribution from percentile points using weighted least-squares.

    percentiles: {p: val, ...} where p is percentile level (e.g. 10, 25, 50, 75, 90).
                 Accepts any number of points >= 2. More points = better fit.
    dist_type: "normal" or "lognormal"
    direction: "higher_is_better" (default) or "lower_is_better".
               For "lower_is_better" variables (e.g. credit_cost, NPL), the raw
               percentiles are typically decreasing (P10=worst, P90=best). Setting
               direction="lower_is_better" automatically reverses them so P10→best,
               P90→worst, producing a strictly-increasing sequence for fitting.

    Uses inverse-variance weighted least squares over all provided percentiles.
    Central percentiles receive higher weight (they are estimated more precisely).

    Truncation: bounds are set to P1/P99 of the fitted distribution so that
    simulations stay within the analyst's intended range. Override by passing
    lower=/upper= to the returned distribution after construction.
    """
    # ── Input validation ──
    if not percentiles:
        if dist_type == "lognormal":
            return LogNormalDist(np.log(1e-4), 0.01)
        return NormalDist(0.0, 0.01)

    levels = sorted(percentiles.keys())
    values = np.array([percentiles[p] for p in levels])

    # ── Auto-reverse for lower_is_better variables ──
    if direction == "lower_is_better":
        # Raw: P10=worst(high), P90=best(low) → reverse so values are increasing
        values = values[::-1]

    if dist_type == "lognormal" and np.any(values <= 0):
        neg_keys = [p for p in levels if percentiles[p] <= 0]
        raise ValueError(
            f"Lognormal distribution requires all percentile values > 0. "
            f"Non-positive at percentiles: {neg_keys}"
        )

    for i in range(1, len(levels)):
        if not values[i] > values[i - 1]:
            raise ValueError(
                f"Percentile values must be strictly increasing: "
                f"P{levels[i - 1]}={float(values[i - 1]):.6f} >= "
                f"P{levels[i]}={float(values[i]):.6f}"
                f" (direction={direction})"
            )
    probs = np.array(levels, dtype=float) / 100.0

    # Fallback for a single point
    if len(levels) < 2:
        mu = float(values[0]) if len(values) == 1 else 0.0
        if dist_type == "lognormal":
            mu = max(mu, 1e-10)
            return LogNormalDist(np.log(mu), abs(np.log(mu)) * 0.1 + 0.01)
        return NormalDist(mu, abs(mu) * 0.1 + 0.01)

    # Theoretical z-scores for each percentile level
    z_scores = _ndtri(np.clip(probs, 1e-10, 1 - 1e-10))

    # Inverse-variance weights: central quantiles are estimated more precisely
    weights = np.exp(-0.5 * z_scores**2)
    weights = weights / weights.sum()

    if dist_type == "lognormal":
        values = np.maximum(values, 1e-10)
        log_values = np.log(values)
        mu, sigma = _wls_fit(z_scores, log_values, weights)
        sigma = max(sigma, 1e-10)
        # Truncate at P1/P99 of the fitted distribution
        lower = float(np.exp(mu + sigma * _ndtri(0.01)))
        upper = float(np.exp(mu + sigma * _ndtri(0.99)))
        return LogNormalDist(mu, sigma, lower=lower, upper=upper)
    else:
        mu, sigma = _wls_fit(z_scores, values, weights)
        sigma = max(abs(sigma), 1e-10)
        lower = float(mu + sigma * _ndtri(0.01))
        upper = float(mu + sigma * _ndtri(0.99))
        return NormalDist(mu, sigma, lower=lower, upper=upper)


# ──────────────────────────────────────────────
#  Correlation matrix with t-Copula support
# ──────────────────────────────────────────────


def build_correlation_matrix(assumptions: list, correlations: list) -> tuple:
    """Build correlation matrix from user-defined correlations.

    Returns: (correlation_matrix, warnings)
    """
    n = len(assumptions)
    corr = np.eye(n)
    idx_map = {name: i for i, name in enumerate(assumptions)}
    warnings = []

    for var_a, var_b, strength in correlations:
        if var_a in idx_map and var_b in idx_map:
            i, j = idx_map[var_a], idx_map[var_b]
            corr[i, j] = strength
            corr[j, i] = strength

    eigvals, eigvecs = np.linalg.eigh(corr)
    min_eigval = float(np.min(eigvals))
    if min_eigval < -1e-10:
        warnings.append(
            f"Correlation matrix was not positive semi-definite "
            f"(min eigenvalue={min_eigval:.4f}). Applied eigendecomposition fix."
        )
        eigvals = np.maximum(eigvals, 1e-10)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)

        for var_a, var_b, target in correlations:
            if var_a in idx_map and var_b in idx_map:
                i, j = idx_map[var_a], idx_map[var_b]
                actual = corr[i, j]
                if abs(actual - target) > 0.05:
                    warnings.append(
                        f"corr({var_a}, {var_b}): requested={target:.2f}, "
                        f"adjusted={actual:.2f} (delta={actual - target:+.2f})"
                    )

    return corr, warnings


# ──────────────────────────────────────────────
#  Monte Carlo simulation with t-Copula
# ──────────────────────────────────────────────


def run_monte_carlo(
    assumption_distributions: dict,
    pnl_model_fn,
    correlation_matrix: np.ndarray = None,
    n_simulations: int = None,
    copula_df: float = None,
    seed: int | None = None,
    store_raw_draws: bool = False,
) -> dict:
    """Run Monte Carlo simulation.

    copula_df: Student-t degrees of freedom for tail dependency.
               None = Gaussian copula (no extra tail dependency).
               5-8 = moderate tail dependency (recommended for fundamentals).
               3-4 = heavy tails (crisis scenarios).
               Lower df → fatter tails → more extreme co-moves → lower RRR.
    seed: Optional seed for reproducibility. If None, uses OS entropy.
          The seed is recorded in the result for audit/replay.
    """
    if n_simulations is None:
        n_simulations = MONTE_CARLO_SIMULATIONS

    # Record seed BEFORE creating rng so it can reproduce the full run.
    # When seed=None, generate a fresh seed from OS entropy so the rng
    # created below starts from a known, recorded state.
    actual_seed = seed if seed is not None else int(np.random.default_rng().integers(0, 2**63))

    rng = np.random.default_rng(actual_seed)

    names = list(assumption_distributions.keys())
    n_vars = len(names)

    if correlation_matrix is not None and correlation_matrix.shape == (n_vars, n_vars):
        L = _nearest_psd_cholesky(correlation_matrix)
        z = rng.standard_normal((n_simulations, n_vars))
        correlated_z = z @ L.T

        if copula_df is not None and copula_df > 2:
            # t-Copula: multiply by sqrt(df/chi2) to get t-distributed marginals
            chi2 = rng.chisquare(df=copula_df, size=n_simulations)
            scaling = np.sqrt(copula_df / chi2)
            correlated_z = correlated_z * scaling[:, np.newaxis]
            # Convert to uniform via t-CDF, then to target marginals via inverse CDF
            samples = np.zeros((n_simulations, n_vars))
            for i, name in enumerate(names):
                dist = assumption_distributions[name]
                u = _t_cdf(correlated_z[:, i], copula_df)
                samples[:, i] = dist.ppf(u)
        else:
            # Gaussian copula
            samples = np.zeros((n_simulations, n_vars))
            for i, name in enumerate(names):
                dist = assumption_distributions[name]
                samples[:, i] = dist.ppf(_norm_cdf(correlated_z[:, i]))
    else:
        samples = np.zeros((n_simulations, n_vars))
        for i, name in enumerate(names):
            samples[:, i] = assumption_distributions[name].rvs(n_simulations, rng=rng)

    # ── Vectorized path: pass entire sample arrays to model function ──
    vectorized_inputs = {name: samples[:, i] for i, name in enumerate(names)}
    try:
        vectorized_result = pnl_model_fn(vectorized_inputs)
        if isinstance(vectorized_result, dict) and all(
            isinstance(v, np.ndarray) and v.shape == (n_simulations,)
            for v in vectorized_result.values()
        ):
            output = dict(vectorized_result)
            output["seed"] = actual_seed
            output["n_simulations"] = n_simulations
            if store_raw_draws:
                output["raw_draws"] = samples
            return output
    except Exception:
        pass  # model function doesn't support array inputs, fall through

    # ── Sequential fallback (for non-vectorizable model functions) ──
    first_inputs = {name: samples[0, i] for i, name in enumerate(names)}
    first_result = pnl_model_fn(first_inputs)
    result_keys = list(first_result.keys())

    results = {key: [first_result[key]] for key in result_keys}

    for row_idx in range(1, n_simulations):
        inputs = {name: samples[row_idx, i] for i, name in enumerate(names)}
        pnl = pnl_model_fn(inputs)
        for key in result_keys:
            results[key].append(pnl.get(key, np.nan))

    output = {key: np.array(val) for key, val in results.items()}
    output["seed"] = actual_seed
    output["n_simulations"] = n_simulations
    if store_raw_draws:
        output["raw_draws"] = samples
    return output


# ──────────────────────────────────────────────
#  Multi-year cumulative simulation
# ──────────────────────────────────────────────


def _generate_samples(
    distributions: dict[str, NormalDist | LogNormalDist],
    names: list[str],
    correlation_matrix: np.ndarray | None,
    n_simulations: int,
    copula_df: float | None,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate correlated samples for one simulation year via t-Copula or Gaussian."""
    n_vars = len(names)
    samples = np.zeros((n_simulations, n_vars))

    if correlation_matrix is not None and correlation_matrix.shape == (n_vars, n_vars):
        L = _nearest_psd_cholesky(correlation_matrix)
        z = rng.standard_normal((n_simulations, n_vars))
        correlated_z = z @ L.T

        if copula_df is not None and copula_df > 2:
            chi2 = rng.chisquare(df=copula_df, size=n_simulations)
            scaling = np.sqrt(copula_df / chi2)
            correlated_z = correlated_z * scaling[:, np.newaxis]
            for i, name in enumerate(names):
                u = _t_cdf(correlated_z[:, i], copula_df)
                samples[:, i] = distributions[name].ppf(u)
        else:
            for i, name in enumerate(names):
                samples[:, i] = distributions[name].ppf(_norm_cdf(correlated_z[:, i]))
    else:
        for i, name in enumerate(names):
            samples[:, i] = distributions[name].rvs(n_simulations, rng=rng)

    return samples


def _prepare_base_state(base_state: dict, n_simulations: int) -> dict:
    """Convert scalar base_state values to constant arrays for vectorized model_fn."""
    prepared = {}
    for key, val in base_state.items():
        if isinstance(val, np.ndarray):
            prepared[key] = val
        else:
            prepared[key] = np.full(n_simulations, float(val))
    return prepared


def run_monte_carlo_cumulative(
    yearly_assumptions: dict[str, dict[str, NormalDist | LogNormalDist]],
    model_fn,
    base_state: dict | None = None,
    correlation_matrix: np.ndarray = None,
    n_simulations: int = None,
    copula_df: float = None,
    seed: int | None = None,
    store_raw_draws: bool = False,
) -> dict[str, dict]:
    """Run multi-year cumulative Monte Carlo simulation with t-Copula.

    Unlike run_monte_carlo() which simulates each year independently from
    the base year, this function chains years sequentially: Year N's model
    outputs feed into Year N+1 as prev_state.  This ensures FY2027E revenue
    grows from FY2026E's *simulated* revenue (not the FY2025A base),
    matching how EPS bridges compound in real financial models.

    Args:
        yearly_assumptions: {year_label: {var_name: Distribution}}.
            Processed in insertion order.  Each year has its own distributions
            (same variable names, different parameters).
        model_fn: callable(inputs, prev_state) -> (outputs, state).
            - inputs:    {var_name: np.ndarray} — stochastic draws, shape (n_sims,)
            - prev_state: {key: np.ndarray} | None — prior year state
            - outputs:   {key: np.ndarray} — results (target_price, eps, revenue)
            - state:     {key: np.ndarray} — rolled forward to next year
        base_state: Optional initial state dict.  Scalar values are broadcast
            to constant arrays.  If None, model_fn receives None for year 1.
        correlation_matrix: Shared across all years (same variables assumed).
        n_simulations: Number of paths.  Default from MONTE_CARLO_SIMULATIONS.
        copula_df: t-Copula degrees of freedom.  None = Gaussian copula.
        seed: Master seed.  All years draw sequentially from the same RNG.
        store_raw_draws: Include "raw_draws" array per year in output.

    Returns:
        {year_label: {key: np.ndarray, "seed": int, "n_simulations": int}}
    """
    if n_simulations is None:
        n_simulations = MONTE_CARLO_SIMULATIONS

    actual_seed = seed if seed is not None else int(np.random.default_rng().integers(0, 2**63))

    rng = np.random.default_rng(actual_seed)

    results = {}
    prev_state = _prepare_base_state(base_state, n_simulations) if base_state else None

    for year_label, distributions in yearly_assumptions.items():
        names = list(distributions.keys())

        samples = _generate_samples(
            distributions,
            names,
            correlation_matrix,
            n_simulations,
            copula_df,
            rng,
        )

        inputs = {name: samples[:, i] for i, name in enumerate(names)}
        outputs, state = model_fn(inputs, prev_state)

        year_result = dict(outputs)
        year_result["seed"] = actual_seed
        year_result["n_simulations"] = n_simulations
        if store_raw_draws:
            year_result["raw_draws"] = samples

        results[year_label] = year_result
        prev_state = state

    return results


# ──────────────────────────────────────────────
#  RRR + Kelly Criterion
# ──────────────────────────────────────────────


def calc_rrr(price_distribution: np.ndarray, current_price: float) -> dict:
    """Calculate RRR and optimal position size via Kelly Criterion."""
    if price_distribution is None or len(price_distribution) == 0:
        return {
            "rrr": 0.0,
            "p_up": 0.0,
            "p_down": 0.0,
            "e_upside": 0.0,
            "e_downside": 0.0,
            "kelly_full": 0.0,
            "kelly_half": 0.0,
            "percentiles": {},
            "current_price": current_price,
        }

    upside = price_distribution - current_price
    up_mask = upside > 0
    down_mask = upside < 0

    p_up = np.mean(up_mask)
    p_down = np.mean(down_mask)
    e_upside = np.mean(upside[up_mask]) if p_up > 0 else 0
    e_downside = abs(np.mean(upside[down_mask])) if p_down > 0 else 0

    rrr = float("inf") if p_down * e_downside == 0 else p_up * e_upside / (p_down * e_downside)

    # Kelly Criterion: f* = (p*b - q) / b, where b = odds = E[up]/E[down]
    kelly_full = 0.0
    kelly_half = 0.0
    if e_downside > 0 and e_upside > 0 and p_down > 0:
        b = e_upside / e_downside  # payoff odds
        kelly_full = (p_up * b - p_down) / b
        kelly_full = max(kelly_full, 0.0)
        kelly_half = kelly_full / 2

    return {
        "rrr": rrr,
        "p_up": p_up,
        "p_down": p_down,
        "e_upside": e_upside,
        "e_downside": e_downside,
        "kelly_full": kelly_full,
        "kelly_half": kelly_half,
        "percentiles": {
            10: np.percentile(price_distribution, 10),
            25: np.percentile(price_distribution, 25),
            50: np.percentile(price_distribution, 50),
            75: np.percentile(price_distribution, 75),
            90: np.percentile(price_distribution, 90),
        },
        "current_price": current_price,
    }


# ──────────────────────────────────────────────
#  RRR from percentile table (no raw arrays)
# ──────────────────────────────────────────────


def rrr_from_percentiles(
    target_price_pctls: dict,
    current_price: float,
) -> dict:
    """Compute RRR and Kelly from MC percentile table (no raw arrays needed).

    Uses numerical integration in probability space over the quantile function
    Q(p) reconstructed from the provided percentile points via linear
    interpolation.

    Useful when only the persisted percentile table is available (no raw
    simulation arrays in memory), e.g. for report generation or entry-price
    recalculation.

    Args:
        target_price_pctls: {percentile_level: target_price, ...}
            e.g. {10: 4.77, 25: 5.41, 50: 6.28, 75: 7.35, 90: 8.47}
            Keys are int/float percentile levels (1-99), values are prices.
        current_price: Current market price (or entry price for recalc).

    Returns:
        dict with rrr, p_up, p_down, e_upside, e_downside,
        kelly_full, kelly_half, current_price, source.
    """
    if not target_price_pctls or current_price <= 0:
        return {
            "rrr": 0.0,
            "p_up": 0.0,
            "p_down": 0.0,
            "e_upside": 0.0,
            "e_downside": 0.0,
            "kelly_full": 0.0,
            "kelly_half": 0.0,
            "current_price": current_price,
            "source": "percentile_integration",
        }

    # Sort percentile levels and values
    levels = sorted(int(p) for p in target_price_pctls)
    values = np.array([float(target_price_pctls[p]) for p in levels])
    probs = np.array(levels, dtype=float) / 100.0  # convert to [0, 1]

    # ── Find F(current_price): the CDF value at current_price ──
    if current_price <= values[0]:
        p_current = probs[0]
    elif current_price >= values[-1]:
        p_current = probs[-1]
    else:
        idx = int(np.searchsorted(values, current_price)) - 1
        idx = max(0, min(idx, len(values) - 2))
        frac = (current_price - values[idx]) / (values[idx + 1] - values[idx])
        p_current = probs[idx] + frac * (probs[idx + 1] - probs[idx])

    p_up = 1.0 - p_current
    p_down = p_current

    # ── Numerical integration via dense interpolation of Q(p) ──
    n_interp = 200
    p_grid = np.linspace(probs[0], probs[-1], n_interp)
    v_grid = np.interp(p_grid, probs, values)

    # Compute unconditional upside/downside integrals
    upside = np.maximum(v_grid - current_price, 0.0)
    downside = np.maximum(current_price - v_grid, 0.0)

    # Trapezoidal integration over interior of percentile range
    dp = np.diff(p_grid)
    e_upside_interior = np.sum((upside[:-1] + upside[1:]) / 2 * dp)
    e_downside_interior = np.sum((downside[:-1] + downside[1:]) / 2 * dp)

    # Tail contributions (assume Q(p) = boundary value for tails)
    e_upside_tail = max(float(values[-1]) - current_price, 0.0) * (1.0 - probs[-1])
    e_downside_tail = max(current_price - float(values[0]), 0.0) * probs[0]

    e_upside_raw = e_upside_interior + e_upside_tail
    e_downside_raw = e_downside_interior + e_downside_tail

    # ── Derive RRR and Kelly ──
    if e_downside_raw > 1e-10 and p_down > 1e-10:
        rrr = e_upside_raw / e_downside_raw
        e_upside = e_upside_raw / p_up if p_up > 0 else 0.0
        e_downside = e_downside_raw / p_down
        b = e_upside / e_downside if e_downside > 0 else 0.0
        kelly_full = max((p_up * b - p_down) / b, 0.0) if b > 0 else 0.0
    else:
        rrr = float("inf")
        e_upside = e_upside_raw / p_up if p_up > 0 else 0.0
        e_downside = 0.0
        kelly_full = 1.0

    kelly_half = kelly_full / 2

    return {
        "rrr": round(rrr, 4),
        "p_up": round(p_up, 4),
        "p_down": round(p_down, 4),
        "e_upside": round(e_upside, 4),
        "e_downside": round(e_downside, 4),
        "kelly_full": round(kelly_full, 4),
        "kelly_half": round(kelly_half, 4),
        "current_price": current_price,
        "source": "percentile_integration",
    }


def entry_price_rrr(
    target_price_pctls: dict,
    entry_price: float,
) -> dict:
    """Recalculate RRR at a different entry price.

    The target price distribution (percentile table) is unchanged; only the
    reference price shifts.  A lower entry price increases upside and
    decreases downside, raising RRR.

    Args:
        target_price_pctls: MC percentile table (typically filtered).
        entry_price: Hypothetical entry price.

    Returns:
        Same structure as rrr_from_percentiles().
    """
    return rrr_from_percentiles(target_price_pctls, entry_price)


# ──────────────────────────────────────────────
#  Assumption consistency guard
# ──────────────────────────────────────────────


def save_reviewed_assumptions(
    workspace_dir: str,
    assumptions: dict,
) -> Path:
    """Save the user-reviewed assumption matrix as the source of truth.

    Call this AFTER the user confirms the assumption matrix in Step 4 Layer 6.
    The saved file is checked by verify_assumption_consistency() before
    running Monte Carlo to prevent post-review drift.
    """
    ws = resolve_workspace_path(workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    store = AtomicJSON(ws)
    lock_file = ws / "_reviewed_assumptions.json"
    store.save(
        "_reviewed_assumptions.json",
        {
            "reviewed_at": pd.Timestamp.now().isoformat(),
            "assumptions": assumptions,
        },
    )
    return lock_file


def verify_assumption_consistency(
    workspace_dir: str,
    monte_carlo_assumptions: dict,
    tolerance: float = 0.05,
    correlation_matrix: np.ndarray | None = None,
    copula_df: float | None = None,
    n_simulations: int | None = None,
) -> dict:
    """Verify Monte Carlo assumptions match the user-reviewed matrix.

    Compares the reviewed percentiles (P10/P50/P90 when present) of each
    variable against the actual distributions passed to run_monte_carlo().
    New simulation variables and omitted reviewed variables are hard failures:
    the Monte Carlo model must be identical to the user-reviewed matrix.

    Also validates:
    - Correlation matrix: symmetry, positive-definiteness, unit diagonal, off-diag in [-1,1]
    - copula_df > 2 (required for valid t-distribution scaling)
    - n_simulations sufficiency (>= 10,000 recommended)
    - dist_type consistency with variable naming conventions

    Returns {passed: bool, warnings: list, violations: list}.
    """
    ws = resolve_workspace_path(workspace_dir)
    store = AtomicJSON(ws)

    reviewed = store.load("_reviewed_assumptions.json")
    if not reviewed or "assumptions" not in reviewed:
        return {
            "passed": False,
            "warnings": ["No reviewed assumptions found. Run save_reviewed_assumptions() first."],
            "violations": [],
        }

    reviewed_assumptions = reviewed.get("assumptions", {})

    violations = []
    warnings = []

    sim_vars = set(monte_carlo_assumptions.keys())
    reviewed_vars = set(reviewed_assumptions.keys())

    for var_name in sorted(sim_vars - reviewed_vars):
        violations.append(
            f"Variable '{var_name}' not in reviewed matrix — new variable added post-review"
        )

    for var_name in sorted(reviewed_vars - sim_vars):
        violations.append(f"Reviewed variable '{var_name}' is absent from Monte Carlo assumptions")

    percentile_map = {"p10": 0.10, "p50": 0.50, "p90": 0.90}

    for var_name, dist in monte_carlo_assumptions.items():
        if var_name not in reviewed_assumptions:
            continue

        reviewed_var = reviewed_assumptions[var_name]
        if isinstance(reviewed_var, dict):
            for key, q in percentile_map.items():
                if key not in reviewed_var:
                    continue
                reviewed_value = reviewed_var[key]
                actual_value = float(dist.ppf(q))

                if reviewed_value != 0:
                    drift = abs(actual_value - reviewed_value) / abs(reviewed_value)
                else:
                    drift = abs(actual_value - reviewed_value)

                if drift > tolerance:
                    violations.append(
                        f"Variable '{var_name}': {key.upper()} drifted from {reviewed_value} "
                        f"(reviewed) to {actual_value:.4f} (simulation) — {drift:.1%} "
                        f"change exceeds {tolerance:.0%} tolerance"
                    )

    # ── P3: Extended validation checks ──

    # Correlation matrix validation
    if correlation_matrix is not None:
        n = correlation_matrix.shape[0]
        if correlation_matrix.shape != (n, n):
            violations.append(f"Correlation matrix is not square: shape={correlation_matrix.shape}")
        else:
            # Symmetry
            if not np.allclose(correlation_matrix, correlation_matrix.T, atol=1e-8):
                violations.append("Correlation matrix is not symmetric")

            # Unit diagonal
            diag = np.diag(correlation_matrix)
            if not np.allclose(diag, 1.0, atol=1e-8):
                bad = [(i, diag[i]) for i in range(n) if abs(diag[i] - 1.0) > 1e-8]
                violations.append(f"Correlation matrix diagonal != 1.0 at: {bad}")

            # Off-diagonal in [-1, 1]
            off_diag = correlation_matrix[~np.eye(n, dtype=bool)]
            if np.any(np.abs(off_diag) > 1.0 + 1e-8):
                oob = np.where(np.abs(off_diag) > 1.0 + 1e-8)[0]
                violations.append(
                    f"Correlation matrix has {len(oob)} off-diagonal entries outside [-1, 1]"
                )

            # Positive-definiteness (Cholesky test)
            try:
                np.linalg.cholesky(correlation_matrix)
            except np.linalg.LinAlgError:
                violations.append(
                    "Correlation matrix is not positive-definite — Cholesky decomposition failed"
                )

            # Dimension match
            if n != len(sim_vars):
                warnings.append(
                    f"Correlation matrix dimension ({n}) != number of variables ({len(sim_vars)})"
                )

    # copula_df validation
    if copula_df is not None:
        if copula_df <= 2:
            violations.append(f"copula_df={copula_df} must be > 2 for valid t-Copula variance")
        elif copula_df < 4:
            warnings.append(
                f"copula_df={copula_df} is very low — very heavy tails, consider >= 4 for stability"
            )

    # Simulation count sufficiency
    if n_simulations is not None:
        if n_simulations < 10_000:
            warnings.append(
                f"n_simulations={n_simulations:,} is below 10,000 — "
                f"percentile estimates (especially P5/P95) may be noisy"
            )
        elif n_simulations < 50_000:
            warnings.append(
                f"n_simulations={n_simulations:,} — P5/P95 estimates have moderate noise; "
                f"100,000+ recommended for production"
            )

    # dist_type consistency: PE/PB should be lognormal
    pe_like_keywords = {"pe", "pb", "ps"}
    for var_name, dist in monte_carlo_assumptions.items():
        if isinstance(dist, LogNormalDist):
            name_lower = var_name.lower()
            is_ratio = any(kw in name_lower for kw in pe_like_keywords)
            if not is_ratio:
                warnings.append(
                    f"Variable '{var_name}' uses lognormal distribution — "
                    f"confirm this is intentional (typically only PE/PB/PS are lognormal)"
                )

    passed = len(violations) == 0

    return {
        "passed": passed,
        "warnings": warnings,
        "violations": violations,
        "summary": (
            "Assumptions consistent with reviewed matrix"
            if passed and not warnings
            else f"{len(violations)} violation(s), {len(warnings)} warning(s)"
            if warnings
            else f"{len(violations)} violation(s): post-review assumption drift detected"
        ),
    }


# ──────────────────────────────────────────────
#  Calibration tracking
# ──────────────────────────────────────────────


def save_calibration(
    workspace_dir: str,
    ticker: str,
    predicted_eps: float,
    predicted_year: str,
    confidence: str = "medium",
    predicted_percentiles: dict | None = None,
) -> Path:
    """Save a calibration record for post-earnings verification.

    Call this at the end of Step 4 for each stock analyzed.
    After earnings, call update_calibration_actual() with the actual EPS.
    """
    ws = resolve_workspace_path(workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    store = AtomicJSON(ws)

    records = store.load("calibration_record.json", default=[])
    if not isinstance(records, list):
        records = []

    record = {
        "ticker": ticker,
        "predicted_year": predicted_year,
        "predicted_eps_p50": predicted_eps,
        "confidence": confidence,
        "predicted_percentiles": predicted_percentiles,
        "actual_eps": None,
        "actual_date": None,
    }
    records.append(record)
    store.save("calibration_record.json", records)
    return ws / "calibration_record.json"


def update_calibration_actual(
    workspace_dir: str,
    predicted_year: str,
    actual_eps: float,
    actual_date: str | None = None,
) -> dict:
    """Update calibration record with actual EPS after earnings release.

    Returns a summary with calibration statistics.
    """
    from datetime import datetime

    ws = resolve_workspace_path(workspace_dir)
    store = AtomicJSON(ws)

    records = store.load("calibration_record.json", default=[])
    if not records:
        return {"error": "No calibration record found"}

    updated = False
    for rec in records:
        if rec["predicted_year"] == predicted_year and rec["actual_eps"] is None:
            rec["actual_eps"] = actual_eps
            rec["actual_date"] = actual_date or datetime.now().strftime("%Y-%m-%d")
            updated = True
            break

    if not updated:
        return {"error": f"No unmatched record for year {predicted_year}"}

    store.save("calibration_record.json", records)

    # Compute calibration stats from all completed records
    completed = [r for r in records if r["actual_eps"] is not None]
    return _compute_calibration_stats(completed)


def _compute_calibration_stats(records: list) -> dict:
    """Compute calibration statistics from completed predictions."""
    if not records:
        return {"n_predictions": 0}

    errors = []
    in_range_count = 0
    for r in records:
        pred = r["predicted_eps_p50"]
        actual = r["actual_eps"]
        err_pct = (actual - pred) / abs(pred) if pred != 0 else 0
        errors.append(err_pct)

        # Check if actual fell within P30-P70
        pctl = r.get("predicted_percentiles")
        if pctl and 30 in pctl and 70 in pctl and pctl[30] <= actual <= pctl[70]:
            in_range_count += 1

    n = len(errors)
    mean_err = sum(errors) / n
    has_range = any(r.get("predicted_percentiles", {}).get(30) for r in records)

    return {
        "n_predictions": n,
        "mean_error_pct": f"{mean_err:+.1%}",
        "bias": "optimistic"
        if mean_err > 0.05
        else ("pessimistic" if mean_err < -0.05 else "neutral"),
        "in_p30_p70_rate": f"{in_range_count}/{sum(1 for r in records if r.get('predicted_percentiles', {}).get(30))}"
        if has_range
        else "N/A",
        "suggestion": _calibration_suggestion(mean_err),
    }


def _calibration_suggestion(bias: float) -> str:
    if abs(bias) < 0.05:
        return "Well calibrated. No adjustment needed."
    direction = "optimistic" if bias > 0 else "pessimistic"
    magnitude = f"{abs(bias):.0%}"
    return f"Systematically {direction} by ~{magnitude}. Consider adjusting P50 {('down' if bias > 0 else 'up')} by this margin."


def load_calibration_stats() -> dict:
    """Load and aggregate calibration stats across all workspaces."""
    all_completed = []
    if not WORKSPACES_DIR.exists():
        return {"n_predictions": 0}

    for ws in WORKSPACES_DIR.iterdir():
        if not ws.is_dir():
            continue
        cal_file = ws / "calibration_record.json"
        if not cal_file.exists():
            continue
        try:
            store = AtomicJSON(ws)
            records = store.load("calibration_record.json", default=[])
            all_completed.extend(r for r in records if r.get("actual_eps") is not None)
        except Exception:
            continue

    return _compute_calibration_stats(all_completed)


def validate_mc_p50_alignment(
    mc_results: dict,
    forecast_model: dict,
    tolerance: float = 5.0,
    primary_forward_year: str = "T+1",
) -> dict:
    """Compare Monte Carlo P50 outputs with forecast_model values.

    Catches unit-convention bugs and model-function errors that produce
    wildly wrong MC results (e.g. EPS 58.9 instead of 0.78).

    Supports two input formats:
    1. In-memory arrays: {"eps": np.array([...]), "bps": np.array([...]), ...}
    2. Persisted JSON percentiles: {"eps_percentiles": {"50": 0.78}, ...}

    Args:
        mc_results: Monte Carlo output dict (arrays or JSON with percentile keys).
        forecast_model: Parsed forecast_model.json dict.
        tolerance: Max acceptable percent drift (default 5%).
        primary_forward_year: Which period to compare (default "T+1").

    Returns:
        {"passed": bool, "checks": [...], "summary": str}
        Each check: {"metric", "mc_p50", "forecast_p50", "pct_diff", "passed"}
    """
    period_data = forecast_model.get("periods", {}).get(primary_forward_year, {})

    # Detect format: arrays (in-memory) vs percentiles (persisted JSON)
    has_arrays = isinstance(mc_results.get("eps"), np.ndarray)
    has_pctls = "eps_percentiles" in mc_results or "bps_percentiles" in mc_results

    def _get_mc_p50(metric: str) -> float | None:
        """Extract P50 for a metric from either format."""
        if has_arrays and metric in mc_results:
            return float(np.percentile(mc_results[metric], 50))
        if has_pctls:
            pctl_key = f"{metric}_percentiles"
            pctls = mc_results.get(pctl_key, {})
            p50 = pctls.get("50") or pctls.get(50)
            if p50 is not None:
                return float(p50)
        return None

    checks = []

    # EPS
    eps_forecast = period_data.get("eps")
    eps_mc = _get_mc_p50("eps")
    if eps_mc is not None and eps_forecast:
        pct_diff = (eps_mc / eps_forecast - 1) * 100
        checks.append(
            {
                "metric": "eps",
                "mc_p50": round(eps_mc, 4),
                "forecast_p50": round(eps_forecast, 4),
                "pct_diff": round(pct_diff, 1),
                "passed": abs(pct_diff) <= tolerance,
            }
        )

    # BPS
    bps_forecast = period_data.get("bps")
    bps_mc = _get_mc_p50("bps")
    if bps_mc is not None and bps_forecast:
        pct_diff = (bps_mc / bps_forecast - 1) * 100
        checks.append(
            {
                "metric": "bps",
                "mc_p50": round(bps_mc, 4),
                "forecast_p50": round(bps_forecast, 4),
                "pct_diff": round(pct_diff, 1),
                "passed": abs(pct_diff) <= tolerance,
            }
        )

    # ROE (forecast stores as roe_pct or roe; MC stores as roe_percentiles)
    roe_forecast = period_data.get("roe_pct", period_data.get("roe", 0))
    roe_mc = _get_mc_p50("roe")
    if roe_mc is not None and roe_forecast:
        pct_diff = (roe_mc / roe_forecast - 1) * 100
        checks.append(
            {
                "metric": "roe",
                "mc_p50": round(roe_mc, 4),
                "forecast_p50": round(roe_forecast, 4),
                "pct_diff": round(pct_diff, 1),
                "passed": abs(pct_diff) <= tolerance,
            }
        )

    n_fail = sum(1 for c in checks if not c["passed"])
    return {
        "passed": n_fail == 0,
        "checks": checks,
        "summary": f"{len(checks)} checks, {n_fail} failed",
    }
