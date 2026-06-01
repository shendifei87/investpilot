from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import t as t_dist
from config.settings import MONTE_CARLO_SIMULATIONS, WORKSPACES_DIR
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
        return np.exp(self.mu + self.sigma ** 2 / 2)

    @property
    def std(self):
        return self.mean * np.sqrt(np.exp(self.sigma ** 2) - 1)


# ──────────────────────────────────────────────
#  Numerical helpers
# ──────────────────────────────────────────────

def _ndtri(p):
    """Normal inverse CDF (Beasley-Springer-Moro, pure numpy, array-safe)."""
    p = np.asarray(p, dtype=float)
    p = np.clip(p, 1e-10, 1 - 1e-10)

    a = np.array([-3.969683028665376e+01,  2.209460984245205e+02,
                   -2.759285104469687e+02,  1.383577518672690e+02,
                   -3.066479806614716e+01,  2.506628277459239e+00])
    b = np.array([-5.447609879822406e+01,  1.615858368580409e+02,
                   -1.556989798598866e+02,  6.680131188771972e+01,
                   -1.328068155288572e+01])
    c = np.array([-7.784894002430293e-03, -3.223964580411365e-01,
                   -2.400758277161838e+00, -2.549732539343734e+00,
                    4.374664141464968e+00,  2.938163982698783e+00])
    d = np.array([ 7.784695709041462e-03,  3.224671290700398e-01,
                    2.445134137142996e+00,  3.754408661907416e+00])

    p_low = 0.02425
    p_high = 1 - p_low
    x = np.zeros_like(p)

    mask = p < p_low
    if np.any(mask):
        q = np.sqrt(-2 * np.log(p[mask]))
        x[mask] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                   ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)

    mask = (p >= p_low) & (p <= p_high)
    if np.any(mask):
        q = p[mask] - 0.5
        r = q * q
        x[mask] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
                   (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

    mask = p > p_high
    if np.any(mask):
        q = np.sqrt(-2 * np.log(1 - p[mask]))
        x[mask] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                    ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)

    return x


def _norm_cdf(x):
    """Standard normal CDF (Abramowitz & Stegun 26.2.17, pure numpy)."""
    x = np.asarray(x, dtype=float)
    a = np.array([0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429])
    p = 0.3275911
    sign = np.sign(x)
    x_abs = np.abs(x) / np.sqrt(2)
    t = 1.0 / (1.0 + p * x_abs)
    y = 1.0 - (((((a[4]*t + a[3])*t + a[2])*t + a[1])*t + a[0]) * t * np.exp(-x_abs * x_abs))
    return 0.5 * (1.0 + sign * y)


def _t_cdf(x, df):
    """Student-t CDF via scipy.stats.t.

    Accurate for all df values including low df (3-6) where tail
    dependency matters most for t-Copula modeling.

    The previous implementation used a scaled-normal approximation that
    severely underestimated tail probabilities at low df (e.g. 3.5x error
    at df=6, x=-3). This is the mathematically correct implementation.
    """
    return t_dist.cdf(x, df)


# ──────────────────────────────────────────────
#  Distribution fitting
# ──────────────────────────────────────────────

def _wls_fit(z_scores: np.ndarray, values: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Weighted least-squares: values = intercept + slope * z_scores."""
    W = np.diag(weights)
    X = np.column_stack([np.ones(len(z_scores)), z_scores])
    beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ values)
    return float(beta[0]), float(beta[1])


def fit_distribution_from_percentiles(percentiles: dict, dist_type: str = "normal") -> NormalDist | LogNormalDist:
    """Fit a distribution from percentile points using weighted least-squares.

    percentiles: {p: val, ...} where p is percentile level (e.g. 10, 25, 50, 75, 90).
                 Accepts any number of points >= 2. More points = better fit.
    dist_type: "normal" or "lognormal"

    Uses inverse-variance weighted least squares over all provided percentiles.
    Central percentiles receive higher weight (they are estimated more precisely).

    Truncation: bounds are set to P1/P99 of the fitted distribution so that
    simulations stay within the analyst's intended range. Override by passing
    lower=/upper= to the returned distribution after construction.
    """
    levels = sorted(percentiles.keys())
    values = np.array([percentiles[p] for p in levels])
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
    weights = np.exp(-0.5 * z_scores ** 2)
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
        eigvals = np.maximum(eigvals, 0)
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
                        f"adjusted={actual:.2f} (delta={actual-target:+.2f})"
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
    if seed is not None:
        actual_seed = seed
    else:
        actual_seed = int(np.random.default_rng().integers(0, 2**63))

    rng = np.random.default_rng(actual_seed)

    names = list(assumption_distributions.keys())
    n_vars = len(names)

    if correlation_matrix is not None and correlation_matrix.shape == (n_vars, n_vars):
        L = np.linalg.cholesky(correlation_matrix)
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

    # Discover output keys from first simulation
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
    return output


# ──────────────────────────────────────────────
#  RRR + Kelly Criterion
# ──────────────────────────────────────────────

def calc_rrr(price_distribution: np.ndarray, current_price: float) -> dict:
    """Calculate RRR and optimal position size via Kelly Criterion."""
    upside = price_distribution - current_price
    up_mask = upside > 0
    down_mask = upside < 0

    p_up = np.mean(up_mask)
    p_down = np.mean(down_mask)
    e_upside = np.mean(upside[up_mask]) if p_up > 0 else 0
    e_downside = abs(np.mean(upside[down_mask])) if p_down > 0 else 0

    if p_down * e_downside == 0:
        rrr = float("inf")
    else:
        rrr = (p_up * e_upside) / (p_down * e_downside)

    # Kelly Criterion: f* = (p*b - q) / b, where b = odds = E[up]/E[down]
    kelly_full = 0.0
    kelly_half = 0.0
    if e_downside > 0 and p_down > 0:
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
    ws = WORKSPACES_DIR / workspace_dir
    ws.mkdir(parents=True, exist_ok=True)
    store = AtomicJSON(ws)
    lock_file = ws / "_reviewed_assumptions.json"
    store.save("_reviewed_assumptions.json", {
        "reviewed_at": pd.Timestamp.now().isoformat(),
        "assumptions": assumptions,
    })
    return lock_file


def verify_assumption_consistency(
    workspace_dir: str,
    monte_carlo_assumptions: dict,
    tolerance: float = 0.05,
) -> dict:
    """Verify Monte Carlo assumptions match the user-reviewed matrix.

    Compares the P10/P50/P90 of each variable between the reviewed matrix
    and the actual distributions passed to run_monte_carlo().

    Returns {passed: bool, warnings: list, violations: list}.
    """
    ws = WORKSPACES_DIR / workspace_dir
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

    for var_name, dist in monte_carlo_assumptions.items():
        if var_name not in reviewed_assumptions:
            warnings.append(f"Variable '{var_name}' not in reviewed matrix — new variable added post-review")
            continue

        reviewed_var = reviewed_assumptions[var_name]
        if isinstance(reviewed_var, dict) and "p50" in reviewed_var:
            reviewed_p50 = reviewed_var["p50"]
            # Use median (P50) for comparison, not mean — lognormal mean is skewed above median
            actual_p50 = float(dist.ppf(0.5))

            if reviewed_p50 != 0:
                drift = abs(actual_p50 - reviewed_p50) / abs(reviewed_p50)
            else:
                drift = abs(actual_p50 - reviewed_p50)

            if drift > tolerance:
                violations.append(
                    f"Variable '{var_name}': P50 drifted from {reviewed_p50} (reviewed) "
                    f"to {actual_p50:.4f} (simulation) — {drift:.1%} change exceeds {tolerance:.0%} tolerance"
                )

    passed = len(violations) == 0

    return {
        "passed": passed,
        "warnings": warnings,
        "violations": violations,
        "summary": (
            "Assumptions consistent with reviewed matrix"
            if passed
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
    ws = WORKSPACES_DIR / workspace_dir
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

    ws = WORKSPACES_DIR / workspace_dir
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
        if pctl and 30 in pctl and 70 in pctl:
            if pctl[30] <= actual <= pctl[70]:
                in_range_count += 1

    n = len(errors)
    mean_err = sum(errors) / n
    has_range = any(r.get("predicted_percentiles", {}).get(30) for r in records)

    return {
        "n_predictions": n,
        "mean_error_pct": f"{mean_err:+.1%}",
        "bias": "optimistic" if mean_err > 0.05 else ("pessimistic" if mean_err < -0.05 else "neutral"),
        "in_p30_p70_rate": f"{in_range_count}/{sum(1 for r in records if r.get('predicted_percentiles', {}).get(30))}" if has_range else "N/A",
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
