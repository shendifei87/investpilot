import warnings

import numpy as np
import pandas as pd
from pathlib import Path


def load_price_series(workspace_dir) -> pd.Series:
    """Load daily close price series from workspace price_history.csv.

    Handles column name differences between ASHARE (收盘) and US/HK (Close).
    Returns a datetime-indexed Series of close prices, or empty Series on failure.
    """
    workspace_dir = Path(workspace_dir)
    price_file = workspace_dir / "price_history.csv"
    if not price_file.exists():
        return pd.Series(dtype=float)

    df = pd.read_csv(price_file, index_col=0)

    # Detect date column — ASHARE uses 日期, yfinance uses index or Date, Tushare uses trade_date
    date_col = None
    for col in ["日期", "Date", "date", "trade_date"]:
        if col in df.columns:
            date_col = col
            break
    if date_col:
        df.index = pd.to_datetime(df[date_col])

    # Detect close price column
    for col in ["收盘", "Close", "close"]:
        if col in df.columns:
            prices = pd.to_numeric(df[col], errors="coerce")
            prices.index = pd.to_datetime(prices.index)
            prices = prices.sort_index()
            prices.name = "close"
            return prices

    # If only numeric columns, try the last column (common for simple CSVs)
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) >= 1:
        prices = pd.to_numeric(df[numeric_cols[-1]], errors="coerce")
        prices.index = pd.to_datetime(df.index)
        prices = prices.sort_index()
        prices.name = "close"
        return prices

    return pd.Series(dtype=float)


def forward_pe_band(
    prices: pd.Series,
    forward_eps: float,
    window_weeks: int = 260,
) -> dict:
    """Compute 5-year weekly forward PE series and percentile bands.

    Forward PE = weekly close price / forward_eps.

    Args:
        prices: Daily close prices, datetime-indexed.
        forward_eps: User-defined Forward EPS (typically P50 from Step 4).
        window_weeks: Number of weeks to include (default 260 = 5 years).

    Returns:
        dict with keys: dates, pe_series, bands, current_pe,
        current_percentile, current_price, forward_eps.
        Returns dict with key 'error' on failure.
    """
    if forward_eps <= 0:
        return {"error": f"forward_eps must be positive, got {forward_eps}"}
    if prices.empty:
        return {"error": "price series is empty"}

    prices = prices.dropna()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()

    # Resample to weekly (Friday close)
    weekly = prices.resample("W-FRI").last().dropna()

    if len(weekly) > window_weeks:
        weekly = weekly.iloc[-window_weeks:]

    if len(weekly) < 52:
        warnings.warn(
            f"Only {len(weekly)} weeks of price data available (minimum 52 recommended). "
            "PE band may not be statistically meaningful."
        )

    pe = weekly / forward_eps
    pe = pe.replace([np.inf, -np.inf], np.nan).dropna()

    if pe.empty:
        return {"error": "No valid PE values after computation"}

    bands = {
        "p10": float(np.percentile(pe, 10)),
        "p25": float(np.percentile(pe, 25)),
        "p50": float(np.percentile(pe, 50)),
        "p75": float(np.percentile(pe, 75)),
        "p90": float(np.percentile(pe, 90)),
    }

    current_pe = float(pe.iloc[-1])
    current_price = float(weekly.iloc[-1])
    current_percentile = float((pe <= current_pe).mean()) * 100

    return {
        "dates": pe.index,
        "pe_series": pe,
        "bands": bands,
        "current_pe": current_pe,
        "current_percentile": current_percentile,
        "current_price": current_price,
        "forward_eps": forward_eps,
        "n_weeks": len(pe),
    }


def pe_band_analysis(prices: pd.Series, eps_series: pd.Series) -> dict:
    """Calculate historical PE band and current percentile."""
    try:
        pe = prices / eps_series
        pe = pe.replace([np.inf, -np.inf], np.nan).dropna()
        if pe.empty:
            return {}

        current = pe.iloc[-1]
        return {
            "current_pe": float(current),
            "p10": float(pe.quantile(0.10)),
            "p25": float(pe.quantile(0.25)),
            "p50": float(pe.quantile(0.50)),
            "p75": float(pe.quantile(0.75)),
            "p90": float(pe.quantile(0.90)),
            "percentile_rank": float((pe <= current).mean()),
        }
    except Exception:
        return {}


def dcf_model(
    fcf: float,
    growth_rate: float,
    wacc: float,
    terminal_growth: float,
    years: int,
    shares_outstanding: float,
) -> dict:
    """Simple DCF model."""
    try:
        projected_fcf = []
        current_fcf = fcf
        for _ in range(years):
            current_fcf *= (1 + growth_rate)
            projected_fcf.append(current_fcf)

        terminal_value = projected_fcf[-1] * (1 + terminal_growth) / (wacc - terminal_growth)

        pv_fcf = sum(cf / (1 + wacc) ** (i + 1) for i, cf in enumerate(projected_fcf))
        pv_terminal = terminal_value / (1 + wacc) ** years

        intrinsic_value = pv_fcf + pv_terminal
        per_share = intrinsic_value / shares_outstanding if shares_outstanding > 0 else 0

        return {
            "projected_fcf": projected_fcf,
            "terminal_value": terminal_value,
            "pv_fcf": pv_fcf,
            "pv_terminal": pv_terminal,
            "intrinsic_value_total": intrinsic_value,
            "intrinsic_value_per_share": per_share,
            "assumptions": {
                "initial_fcf": fcf,
                "growth_rate": growth_rate,
                "wacc": wacc,
                "terminal_growth": terminal_growth,
                "projection_years": years,
            },
        }
    except Exception as e:
        return {"error": str(e)}


def reverse_dcf(
    current_price: float,
    shares_outstanding: float,
    base_fcf: float,
    wacc: float,
    terminal_growth: float = 0.03,
    years: int = 5,
    g_min: float = -0.10,
    g_max: float = 0.50,
    tolerance: float = 0.001,
    max_iter: int = 100,
) -> dict:
    """Reverse DCF: find the implied FCF growth rate baked into current price.

    Binary search for the growth rate g such that:
        DCF(base_fcf, g, wacc, terminal_growth, years, shares) = current_price

    Returns the implied growth rate and what it means for the investment thesis.
    """
    if current_price <= 0 or shares_outstanding <= 0 or base_fcf <= 0:
        return {"error": "Inputs must be positive"}

    target_value = current_price * shares_outstanding

    lo, hi = g_min, g_max
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        result = dcf_model(base_fcf, mid, wacc, terminal_growth, years, shares_outstanding)
        if "error" in result:
            return {"error": result["error"]}

        intrinsic = result["intrinsic_value_total"]
        if abs(intrinsic - target_value) / target_value < tolerance:
            break
        if intrinsic < target_value:
            lo = mid
        else:
            hi = mid

    implied_g = (lo + hi) / 2

    # Compute implied 5-year EPS trajectory for context
    fcf_path = []
    fcf = base_fcf
    for yr in range(1, years + 1):
        fcf *= (1 + implied_g)
        fcf_path.append({"year": yr, "fcf": round(fcf, 2)})

    # Revenue growth implied (assuming FCF margin stays constant)
    # This is a rough estimate: if FCF margin = base_fcf / current_revenue,
    # then FCF growth ≈ revenue growth

    # Interpretation
    if implied_g > 0.25:
        interpretation = "extremely aggressive — market pricing in hyper-growth (>25% CAGR)"
    elif implied_g > 0.15:
        interpretation = "aggressive — market expects high double-digit growth (15-25%)"
    elif implied_g > 0.08:
        interpretation = "moderate — market expects solid growth (8-15%)"
    elif implied_g > 0.03:
        interpretation = "conservative — market expects GDP-like growth (3-8%)"
    elif implied_g > 0:
        interpretation = "very conservative — near stagnation (0-3%)"
    else:
        interpretation = "negative — market expects declining cash flows"

    return {
        "implied_growth_rate": round(implied_g, 4),
        "implied_growth_pct": f"{implied_g:.1%}",
        "current_price": current_price,
        "base_fcf": base_fcf,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "years": years,
        "fcf_path": fcf_path,
        "interpretation": interpretation,
    }


def historical_valuation_range(
    valuation_data: dict,
    self_calculated_pe: pd.Series = None,
    self_calculated_pb: pd.Series = None,
) -> dict:
    """Summarize historical valuation range from fetched or self-calculated data.

    Prefers self-calculated PE/PB series when provided. Falls back to
    API-fetched data (e.g. Baidu) with a source tag indicating reference-only.

    Args:
        valuation_data: Dict with keys like "pe_history", "pb_history" (DataFrames).
        self_calculated_pe: Optional self-calculated historical PE Series.
        self_calculated_pb: Optional self-calculated historical PB Series.

    Returns:
        Dict with per-metric statistics including source tag.
    """
    result = {}

    # PE: prefer self-calculated
    if self_calculated_pe is not None and not self_calculated_pe.empty:
        pe_clean = self_calculated_pe.replace([np.inf, -np.inf], np.nan).dropna()
        if not pe_clean.empty:
            result["pe_history"] = {
                "mean": float(pe_clean.mean()),
                "median": float(pe_clean.median()),
                "p10": float(pe_clean.quantile(0.10)),
                "p25": float(pe_clean.quantile(0.25)),
                "p50": float(pe_clean.quantile(0.50)),
                "p75": float(pe_clean.quantile(0.75)),
                "p90": float(pe_clean.quantile(0.90)),
                "current": float(pe_clean.iloc[-1]),
                "n_points": len(pe_clean),
                "source": "self_calculated",
            }
    elif "pe_history" in valuation_data:
        df = valuation_data["pe_history"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                col = numeric_cols[0]
                result["pe_history"] = {
                    "mean": float(df[col].mean()),
                    "median": float(df[col].median()),
                    "p10": float(df[col].quantile(0.10)),
                    "p90": float(df[col].quantile(0.90)),
                    "current": float(df[col].iloc[-1]),
                    "source": "baidu_api_reference_only",
                }

    # PB: prefer self-calculated
    if self_calculated_pb is not None and not self_calculated_pb.empty:
        pb_clean = self_calculated_pb.replace([np.inf, -np.inf], np.nan).dropna()
        if not pb_clean.empty:
            result["pb_history"] = {
                "mean": float(pb_clean.mean()),
                "median": float(pb_clean.median()),
                "p10": float(pb_clean.quantile(0.10)),
                "p90": float(pb_clean.quantile(0.90)),
                "current": float(pb_clean.iloc[-1]),
                "n_points": len(pb_clean),
                "source": "self_calculated",
            }
    elif "pb_history" in valuation_data:
        df = valuation_data["pb_history"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                col = numeric_cols[0]
                result["pb_history"] = {
                    "mean": float(df[col].mean()),
                    "median": float(df[col].median()),
                    "p10": float(df[col].quantile(0.10)),
                    "p90": float(df[col].quantile(0.90)),
                    "current": float(df[col].iloc[-1]),
                    "source": "baidu_api_reference_only",
                }

    # Market cap: always from fetched data
    if "market_cap_history" in valuation_data:
        df = valuation_data["market_cap_history"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                col = numeric_cols[0]
                result["market_cap_history"] = {
                    "mean": float(df[col].mean()),
                    "median": float(df[col].median()),
                    "p10": float(df[col].quantile(0.10)),
                    "p90": float(df[col].quantile(0.90)),
                    "current": float(df[col].iloc[-1]),
                }

    return result


def calc_historical_pe_series(
    prices: pd.Series,
    eps_quarterly: pd.Series,
    method: str = "ttm_rolling",
) -> dict:
    """Calculate historical PE from price data and quarterly EPS.

    For each date in the price series, computes trailing TTM PE using
    the sum of the last 4 quarters of EPS (rolling window).

    Args:
        prices: Daily close prices, datetime-indexed.
        eps_quarterly: Quarterly EPS values, datetime-indexed.
            For yfinance data, use Net Income / Shares Outstanding per quarter.
            For akshare data, use 净利润 / 总股本 per quarter.
        method: "ttm_rolling" (sum of last 4Q EPS) or
                "annual" (use most recent annual EPS as constant).

    Returns:
        dict with pe_series (pd.Series), percentile bands, n_points,
        start_date, end_date. Returns dict with key 'error' on failure.
    """
    if prices.empty or eps_quarterly.empty:
        return {"error": "prices or eps_quarterly is empty"}

    prices = prices.dropna().sort_index()
    eps_quarterly = eps_quarterly.dropna().sort_index()

    if len(eps_quarterly) < 1:
        return {"error": "Not enough EPS data points"}

    if method == "annual":
        # Simple method: use latest annual EPS as constant denominator
        latest_eps = float(eps_quarterly.iloc[-1])
        if latest_eps <= 0:
            return {"error": f"Latest annual EPS is non-positive: {latest_eps}"}
        pe = prices / latest_eps
        pe = pe.replace([np.inf, -np.inf], np.nan).dropna()
    else:
        # TTM rolling: sum of last 4 quarters
        if len(eps_quarterly) < 4:
            # Fallback to annual if less than 4 quarters available
            warnings.warn(
                f"Only {len(eps_quarterly)} quarters of EPS data available. "
                "Falling back to annual method."
            )
            latest_eps = float(eps_quarterly.iloc[-1])
            if latest_eps <= 0:
                return {"error": f"Latest EPS is non-positive: {latest_eps}"}
            pe = prices / latest_eps
            pe = pe.replace([np.inf, -np.inf], np.nan).dropna()
        else:
            # Resample quarterly EPS to daily by forward-filling
            # Then compute rolling 4-quarter sum
            eps_daily = eps_quarterly.reindex(
                prices.index.union(eps_quarterly.index)
            ).sort_index()
            # Forward-fill: each day uses the most recent quarterly EPS known
            eps_daily = eps_daily.ffill()

            # Align to price dates
            eps_daily = eps_daily.reindex(prices.index, method="ffill")

            # Rolling TTM EPS: we need sum of last 4 unique quarters.
            # Since EPS is forward-filled daily, use the last reported quarterly value
            # and assume the last 4 quarters sum = 4x the latest quarterly value
            # (approximation when we only have quarterly totals, not individual quarter data).
            # Better approach: if eps_quarterly has per-quarter values, sum last 4.
            ttm_eps = eps_daily * 4  # annualize the latest quarterly EPS
            # More accurate: if we have actual quarterly data, compute proper TTM
            if len(eps_quarterly) >= 4:
                # Use the actual sum of last 4 quarters for the latest period
                ttm_eps_latest = float(eps_quarterly.iloc[-4:].sum())
                ttm_eps = pd.Series(ttm_eps_latest, index=prices.index)
                # For historical dates, compute TTM at each quarter-end
                # by summing the 4 quarters up to that date
                for i in range(4, len(eps_quarterly)):
                    q_date = eps_quarterly.index[i]
                    ttm_at_q = float(eps_quarterly.iloc[i-3:i+1].sum())
                    # Apply this TTM EPS to all price dates between this and next quarter
                    mask = prices.index >= q_date
                    if i + 1 < len(eps_quarterly):
                        mask = mask & (prices.index < eps_quarterly.index[i + 1])
                    ttm_eps.loc[mask] = ttm_at_q

            # Filter to dates with valid TTM EPS
            valid = ttm_eps > 0
            pe = pd.Series(np.nan, index=prices.index)
            pe[valid] = prices[valid] / ttm_eps[valid]
            pe = pe.replace([np.inf, -np.inf], np.nan).dropna()

    if pe.empty:
        return {"error": "No valid PE values after computation"}

    return {
        "pe_series": pe,
        "n_points": len(pe),
        "start_date": str(pe.index[0]),
        "end_date": str(pe.index[-1]),
        "method": method,
        "percentiles": {
            "p10": float(pe.quantile(0.10)),
            "p25": float(pe.quantile(0.25)),
            "p50": float(pe.quantile(0.50)),
            "p75": float(pe.quantile(0.75)),
            "p90": float(pe.quantile(0.90)),
        },
        "current_pe": float(pe.iloc[-1]),
        "current_percentile": float((pe <= pe.iloc[-1]).mean()) * 100,
        "source": "self_calculated",
    }
