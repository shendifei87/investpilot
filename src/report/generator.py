from __future__ import annotations

import base64
import contextlib
import json
import logging
import re
from datetime import datetime
from html import escape
from pathlib import Path

import mistune
import numpy as np

logger = logging.getLogger(__name__)


def generate_distribution_chart(
    data: np.ndarray,
    title: str,
    current_price: float = None,
    save_path: Path = None,
) -> str:
    """Generate probability distribution chart and save to file."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.hist(data, bins=100, density=True, alpha=0.7, color="steelblue", edgecolor="white")

    for p, color, label in [(10, "red", "P10"), (50, "green", "P50"), (90, "red", "P90")]:
        val = np.percentile(data, p)
        ax.axvline(val, color=color, linestyle="--", alpha=0.8, label=f"{label}: {val:.2f}")

    if current_price is not None:
        ax.axvline(current_price, color="black", linewidth=2, label=f"Current: {current_price:.2f}")

    ax.set_title(title, fontsize=14)
    ax.legend()
    ax.set_ylabel("Density")

    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = Path(f"distribution_{timestamp}.png")

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(save_path)


def generate_distribution_from_percentiles(
    p10: float,
    p30: float,
    p50: float,
    p70: float,
    p90: float,
    title: str = "Monte Carlo Target Price Distribution",
    current_price: float = None,
    save_path: Path = None,
    currency: str = "HKD",
    n_samples: int = 20000,
) -> str:
    """Synthesize a target-price distribution from percentile inputs.

    Uses a skew-normal distribution calibrated so that P50 sits near the
    visual center of the chart (not buried in the left tail).  The x-axis
    range is bounded by P10 and P90 with moderate padding, ensuring the
    right tail is not excessively long.

    Args:
        p10, p30, p50, p70, p90: Percentile values (e.g. target prices).
        title: Chart title.
        current_price: Current market price (vertical line).
        save_path: Output PNG path.  Auto-generated if None.
        currency: Currency label for axis.
        n_samples: Number of synthetic samples.

    Returns:
        str: Path to saved PNG file.
    """
    # --- Calibrate skew-normal to match P10 / P30 / P50 / P70 / P90 ---
    # We use scipy.optimize to find (a, loc, scale) such that the
    # skew-normal percentiles match the supplied ones.
    from scipy.optimize import minimize
    from scipy.stats import skewnorm

    target_pcts = np.array([10, 30, 50, 70, 90])
    target_vals = np.array([p10, p30, p50, p70, p90])

    def _loss(params):
        a, loc, scale = params
        if scale <= 0:
            return 1e12
        fitted = skewnorm.ppf(target_pcts / 100.0, a, loc=loc, scale=scale)
        return np.sum((fitted - target_vals) ** 2)

    # Initial guess: use the spread between P10 and P90 as scale
    spread = p90 - p10
    init_loc = p50
    init_scale = spread / 3.0
    result = minimize(
        _loss, x0=[0.0, init_loc, init_scale], method="Nelder-Mead", options={"maxiter": 5000}
    )
    a_opt, loc_opt, scale_opt = result.x
    if scale_opt <= 0:
        scale_opt = init_scale

    # Generate synthetic samples
    samples = skewnorm.rvs(a_opt, loc=loc_opt, scale=scale_opt, size=n_samples, random_state=42)

    # --- Plot ---
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6), facecolor="white")
    ax.set_facecolor("white")

    # Determine x-axis bounds: P10 to P90 with 30% padding each side
    x_low = p10 - 0.30 * (p50 - p10)
    x_high = p90 + 0.30 * (p90 - p50)
    # Clip any samples outside visible range for clean histogram
    visible = samples[(samples >= x_low) & (samples <= x_high)]

    ax.hist(
        visible, bins=80, density=True, alpha=0.7, color="#4361ee", edgecolor="white", linewidth=0.3
    )

    # Percentile lines
    pct_data = {
        10: (p10, "#e63946", "P10 (Bear)"),
        30: (p30, "#f4a261", "P30"),
        50: (p50, "#2a9d8f", "P50 (Base)"),
        70: (p70, "#f4a261", "P70"),
        90: (p90, "#e63946", "P90 (Bull)"),
    }
    for _pct, (val, color, label) in pct_data.items():
        ax.axvline(
            val,
            color=color,
            linestyle="--",
            linewidth=1.5,
            alpha=0.85,
            label=f"{label}: {val:.1f} {currency}",
        )

    # Current price
    if current_price is not None:
        ax.axvline(
            current_price,
            color="black",
            linewidth=2.5,
            label=f"Current: {current_price:.1f} {currency}",
        )

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(f"Target Price ({currency})", fontsize=11)
    ax.set_ylabel("Probability Density", fontsize=11)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(x_low, x_high)

    plt.tight_layout()

    if save_path is None:
        save_path = Path("monte_carlo_distribution.png")

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(save_path)


def generate_histogram_from_percentiles(
    scenarios: list[dict],
    title: str = "Monte Carlo Target Price Distribution",
    save_path: Path = None,
    currency: str = "HKD",
    n_samples: int = 20000,
) -> str:
    """Generate side-by-side histogram charts from percentile data.

    Produces the "Pop Mart style" distribution chart: colored frequency
    histograms (red / blue / green zones) with vertical reference lines
    for Current, P10, P50, P90.

    Args:
        scenarios: List of dicts, each with keys:
            - label (str): e.g. "T+1 FY2026E"
            - percentiles (dict): e.g. {"5": 97.57, "10": 111.39, ..., "95": 317.53}
            - current_price (float | None)
            - n_simulations (int, optional)
            - subtitle (str, optional): e.g. "20,000 simulations"
        title: Overall chart title.
        save_path: Output PNG path.
        currency: Currency symbol for axis label.
        n_samples: Number of synthetic samples to generate per scenario.

    Returns:
        str: Path to saved PNG.
    """
    from scipy.optimize import minimize
    from scipy.stats import skewnorm

    n_scenarios = len(scenarios)
    if n_scenarios == 0:
        return ""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(
        1,
        n_scenarios,
        figsize=(7 * n_scenarios, 6),
        facecolor="white",
        squeeze=False,
    )

    for idx, scenario in enumerate(scenarios):
        ax = axes[0][idx]
        ax.set_facecolor("white")

        label = scenario.get("label", f"Scenario {idx + 1}")
        pctls = scenario.get("percentiles", {})
        cur_price = scenario.get("current_price")
        n_sims = scenario.get("n_simulations", n_samples)
        subtitle = scenario.get("subtitle", f"{n_sims:,} simulations")

        # Extract key percentiles
        p5 = _pct_val(pctls, 5)
        p10 = _pct_val(pctls, 10)
        p50 = _pct_val(pctls, 50)
        p90 = _pct_val(pctls, 90)
        p95 = _pct_val(pctls, 95)

        if p50 is None:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center")
            ax.set_title(label, fontsize=13, fontweight="bold")
            continue

        # Calibrate skew-normal to the densest available percentile grid.
        p30 = _pct_val(pctls, 30)
        p70 = _pct_val(pctls, 70)
        if all(v is not None for v in [p10, p30, p50, p70, p90]):
            target_pcts = np.array([10, 30, 50, 70, 90])
            target_vals = np.array([p10, p30, p50, p70, p90])
        else:
            target_pcts = np.array([10, 50, 90])
            target_vals = np.array([p10 or p5, p50, p90 or p95])

        def _loss(params, _tp=target_pcts, _tv=target_vals):
            a, loc, scale = params
            if scale <= 0:
                return 1e12
            fitted = skewnorm.ppf(_tp / 100.0, a, loc=loc, scale=scale)
            return np.sum((fitted - _tv) ** 2)

        spread = (p90 or p95) - (p10 or p5)
        init_loc = p50
        init_scale = max(spread / 3.0, 0.01)
        result = minimize(
            _loss,
            x0=[0.0, init_loc, init_scale],
            method="Nelder-Mead",
            options={"maxiter": 5000},
        )
        a_opt, loc_opt, scale_opt = result.x
        if scale_opt <= 0:
            scale_opt = init_scale

        samples = skewnorm.rvs(
            a_opt,
            loc=loc_opt,
            scale=scale_opt,
            size=n_sims,
            random_state=42,
        )

        # X-axis bounds
        x_low = (p5 or p10) - 0.3 * (p50 - (p5 or p10))
        x_high = (p95 or p90) + 0.3 * ((p95 or p90) - p50)
        visible = samples[(samples >= x_low) & (samples <= x_high)]

        # Bin the data into colored zones
        bins = np.linspace(x_low, x_high, 81)
        counts, bin_edges = np.histogram(visible, bins=bins)

        # Color each bin based on which zone it falls in
        for i in range(len(counts)):
            left = bin_edges[i]
            right = bin_edges[i + 1]
            mid = (left + right) / 2

            if mid < (p10 or p5):
                color = "#e74c3c"  # red zone
            elif mid > (p90 or p95):
                color = "#2ecc71"  # green zone
            else:
                color = "#3498db"  # blue zone

            ax.bar(
                mid,
                counts[i],
                width=right - left,
                color=color,
                edgecolor="white",
                linewidth=0.2,
                alpha=0.75,
            )

        # Reference lines
        ref_lines = [
            (p10, "#e74c3c", "--", f"P10 {p10:.1f}"),
            (p50, "#e67e22", "-", f"P50 {p50:.1f}"),
            (p90, "#27ae60", "--", f"P90 {p90:.1f}"),
        ]
        for val, color, ls, lbl in ref_lines:
            if val is not None:
                ax.axvline(val, color=color, linestyle=ls, linewidth=1.8, alpha=0.9, label=lbl)

        if cur_price is not None:
            ax.axvline(cur_price, color="black", linewidth=2.5, label=f"Current {cur_price:.1f}")

        ax.set_title(f"{label}\n{subtitle}", fontsize=13, fontweight="bold")
        ax.set_xlabel(f"Target Price ({currency})", fontsize=11)
        ax.set_ylabel("Frequency", fontsize=11)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
        ax.grid(axis="y", alpha=0.3, linestyle=":")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlim(x_low, x_high)

    plt.tight_layout()

    if save_path is None:
        save_path = Path("distribution_chart.png")

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(save_path)


def _pct_val(pctls: dict, pctile: int) -> float | None:
    """Extract percentile value from dict (keys may be int or str)."""
    for key in (pctile, str(pctile), f"p{pctile}"):
        v = pctls.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def generate_pe_band_chart(
    pe_band_data: dict,
    title: str = "1-Year Forward PE Band (5Y History)",
    save_path: Path = None,
) -> str:
    """Generate a PE band time-series chart from forward_pe_band() output.

    Renders weekly PE series with horizontal percentile bands (P10-P90, P25-P75),
    median line, and current PE highlighted.

    Args:
        pe_band_data: Output dict from forward_pe_band().
        title: Chart title.
        save_path: Where to save the PNG. Auto-generated if None.

    Returns:
        str: Path to saved PNG file, or empty string on error.
    """
    if "error" in pe_band_data or "dates" not in pe_band_data:
        return ""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    dates = pe_band_data["dates"]
    pe_series = pe_band_data["pe_series"]
    bands = pe_band_data["bands"]
    current_pe = pe_band_data["current_pe"]
    current_pct = pe_band_data["current_percentile"]
    eps = pe_band_data["forward_eps"]

    fig, ax = plt.subplots(figsize=(12, 6), facecolor="white")
    ax.set_facecolor("white")

    # Horizontal percentile bands (constant across time)
    ax.fill_between(
        dates,
        bands["p10"],
        bands["p90"],
        alpha=0.15,
        color="#4361ee",
        label="P10-P90",
    )
    ax.fill_between(
        dates,
        bands["p25"],
        bands["p75"],
        alpha=0.25,
        color="#4361ee",
        label="P25-P75",
    )

    # Median line
    ax.axhline(
        bands["p50"],
        color="#4361ee",
        linestyle="--",
        linewidth=1,
        alpha=0.7,
        label=f"Median: {bands['p50']:.1f}x",
    )

    # PE time series
    ax.plot(dates, pe_series, color="#1a1a2e", linewidth=1.0, label="Forward PE")

    # Current PE line
    ax.axhline(
        current_pe,
        color="#e63946",
        linewidth=2,
        alpha=0.9,
        label=f"Current: {current_pe:.1f}x ({current_pct:.0f}th %ile)",
    )

    # Annotate current PE
    ax.annotate(
        f"  {current_pe:.1f}x ({current_pct:.0f}th)",
        xy=(dates[-1], current_pe),
        fontsize=10,
        fontweight="bold",
        color="#e63946",
        va="center",
    )

    # Formatting
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel(f"Forward PE (EPS={eps})", fontsize=11)
    ax.set_xlabel("")

    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()

    # Y-axis: show "x" suffix
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}x"))

    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()

    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = Path(f"pe_band_{timestamp}.png")

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(save_path)


# ---------------------------------------------------------------------------
# HTML report generation: markdown-to-HTML converter + helpers
# ---------------------------------------------------------------------------


def _safe_workspace_file(workspace_dir: Path, user_path: str) -> Path | None:
    """Resolve a markdown asset path and require it to stay under workspace."""
    resolved = (workspace_dir / user_path).resolve()
    base = workspace_dir.resolve()
    try:
        resolved.relative_to(base)
        return resolved
    except ValueError:
        return None


def _image_mime(img_path: Path) -> str:
    suffix = img_path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")


class _ResearchReportRenderer(mistune.HTMLRenderer):
    """Custom mistune renderer for InvestPilot research reports.

    - Offsets heading levels (## → h3) to leave room for section headers.
    - Skips top-level # headings (step titles are rendered in section headers).
    - Base64-encodes local images referenced in markdown.
    """

    def __init__(self, workspace_dir=None):
        super().__init__()
        self._ws = Path(workspace_dir) if workspace_dir else None

    def heading(self, text, level, **attrs):
        if level == 1:
            return ""
        tag = f"h{min(level + 1, 6)}"
        return f"<{tag}>{text}</{tag}>\n"

    def image(self, text, url, title=None):
        alt = text or ""
        if self._ws:
            img_path = _safe_workspace_file(self._ws, url)
            if (
                img_path is not None
                and img_path.exists()
                and img_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ):
                data = base64.b64encode(img_path.read_bytes()).decode("ascii")
                mime = _image_mime(img_path)
                return (
                    '<div class="chart-container">'
                    f'<img data-source="{escape(img_path.name, quote=True)}" '
                    f'src="data:{mime};base64,{data}" alt="{escape(alt, quote=True)}">'
                    f'<p class="chart-caption">{escape(alt, quote=True)}</p></div>'
                )
        return f"<p><em>Image not found: {escape(url, quote=True)}</em></p>"


def md_to_html(md_text: str, workspace_dir=None) -> str:
    """Convert InvestPilot step markdown to structured HTML via mistune.

    Uses a custom renderer that offsets headings, base64-embeds local images,
    and preserves all standard markdown features (tables, code blocks, links,
    nested lists, blockquotes) handled correctly by the mistune engine.
    """
    renderer = _ResearchReportRenderer(workspace_dir)
    markdown = mistune.create_markdown(
        renderer=renderer, plugins=["table", "strikethrough", "task_lists", "speedup"]
    )
    return markdown(md_text)


# ---------------------------------------------------------------------------
# Summary metrics extraction — JSON-first with canonical markdown parsing
# ---------------------------------------------------------------------------


def _read_json_safe(ws: Path, filename: str):
    """Read a JSON file from workspace, returning None on any failure.

    Handles both object and array JSON roots.
    """
    p = ws / filename
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def _normalize_mc_json(mc: dict) -> dict:
    """Normalize any Monte Carlo JSON schema to a canonical dict.

    Canonical keys: current_price, p50_target, rrr, target_price_percentiles.
    Handles Schema A (top-level p50_target), B (target_price_percentiles.50),
    C (target_price.50), D (nested rrr.rrr).
    """
    if not isinstance(mc, dict):
        return {}
    result = {}

    # current_price — same in all schemas
    cp = mc.get("current_price")
    if cp is not None:
        result["current_price"] = cp

    # p50_target — Schema A has it at top level; B/D have target_price_percentiles.50;
    # C has target_price.50; E (A-share) has filtered_target_price_percentiles.50
    if mc.get("p50_target") is not None:
        result["p50_target"] = mc["p50_target"]
    else:
        # Try all known percentile dict keys in priority order
        for key in (
            "filtered_target_price_percentiles",
            "target_price_percentiles",
            "target_price",
        ):
            tp = mc.get(key)
            if isinstance(tp, dict):
                p50 = tp.get("50", tp.get(50))
                if p50 is not None:
                    result["target_price_percentiles"] = tp
                    result["p50_target"] = p50
                    break

    # rrr — Schema A/C: top-level float; Schema D: nested rrr.rrr
    rrr = mc.get("rrr")
    if isinstance(rrr, (int, float)):
        result["rrr"] = rrr
    elif isinstance(rrr, dict) and rrr.get("rrr") is not None:
        result["rrr"] = rrr["rrr"]

    return result


# ---------------------------------------------------------------------------
# Per-metric extractors (split from _extract_summary_metrics for readability)
# ---------------------------------------------------------------------------


def _extract_current_price(ws: Path, mc: dict, cv: dict | None, read_model_text) -> str | None:
    """Extract current_price from JSON artifacts or markdown."""
    if mc.get("current_price"):
        return str(mc["current_price"])
    if cv and isinstance(cv, dict):
        if "price_hkd" in cv:
            return str(cv["price_hkd"])
        if isinstance(cv.get("pe_trailing"), dict) and cv["pe_trailing"].get("price"):
            return str(cv["pe_trailing"]["price"])
    vcp = _read_json_safe(ws, "valuation_current_price.json")
    if vcp is not None and isinstance(vcp, (int, float)):
        return str(vcp)
    s4 = read_model_text()
    for pattern in (
        r"当前价[格：:]*\s*[~～]?HKD\s*([\d.]+)",
        r"当前股价[：:]\s*[~～]?([\d.]+)",
        r"当前价格[：:]\s*[~～]?([\d.]+)",
        r"\|\s*当前价[^|]*\|\s*([\d.]+)",
        r"当前价[^(|\n]*?([\d]+\.[\d]+)",
    ):
        m = re.search(pattern, s4)
        if m:
            return m.group(1)
    return None


def _extract_target_price(ws: Path, mc: dict, sa: dict | None, read_model_text) -> str | None:
    """Extract P50 target_price from JSON artifacts or markdown.

    Priority: monte_carlo_results.json > step4 structured > bridge_analysis > regex.
    Year-like numbers (19xx-20xx) and numbers in year context are excluded.
    """
    # Priority 1: monte_carlo_results.json p50_case.target_price_hkd
    if mc.get("p50_target") is not None:
        tp = mc["p50_target"]
        return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    if isinstance(mc.get("p50_case"), dict):
        tp = mc["p50_case"].get("target_price_hkd")
        if tp is not None:
            return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    # Priority 2: step4 bridge_analysis
    if sa and isinstance(sa, dict):
        bridge = sa.get("bridge_analysis", {})
        from datetime import date as _date

        forward_year = _date.today().year + 1
        t1_key = f"t1_{forward_year}E"
        t1 = bridge.get(t1_key, {})
        tp = t1.get("target_price_hkd")
        if tp is not None:
            return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
        # Fallback within step4: search bridge keys
        for _bk, bv in bridge.items():
            if isinstance(bv, dict) and bv.get("target_price_hkd") is not None:
                tp = bv["target_price_hkd"]
                return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    # Priority 3: step4 financial_model_inputs
    if sa and isinstance(sa, dict):
        fmi = sa.get("financial_model_inputs", {})
        if fmi.get("p50_target_hkd") is not None:
            tp = fmi["p50_target_hkd"]
            return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    # Regex fallback — with year exclusion
    s4 = read_model_text()
    target_keywords = ("目标价", "target price", "target_price", "p50 target", "p50目标价")
    labeled_candidates = []
    # Year-like numbers to exclude: 19xx-20xx
    YEAR_PATTERN = re.compile(r"^(19\d\d|20\d\d)$")
    for line in s4.splitlines():
        low = line.lower()
        if "p50" not in low:
            continue
        if not any(kw in low for kw in target_keywords):
            continue
        nums = re.findall(r"(?<![-\d.])(\d+(?:\.\d+)?)(?![%\d.])", line)
        for num in nums:
            try:
                fnum = float(num)
                # Exclude year-like numbers and unreasonably large prices
                if fnum >= 10.0 and fnum <= 500.0 and not YEAR_PATTERN.match(num):
                    labeled_candidates.append(num)
            except ValueError:
                continue
    header_tp = None
    m = re.search(r"P50\s*目标价[：:]*\s*[~～]?([\d.]+)", s4)
    if m and float(m.group(1)) >= 1.0 and not YEAR_PATTERN.match(m.group(1)):
        header_tp = m.group(1)
    compute_tp = None
    m = re.search(r"[Tt]arget\s*=\s*[\d.]+\s*[*×/]\s*[\d.]+\s*/\s*[\d.]+\s*=\s*([\d.]+)\s*HKD", s4)
    if m:
        compute_tp = m.group(1)
    if compute_tp and float(compute_tp) >= 10.0:
        return compute_tp
    if labeled_candidates:
        labeled_candidates.sort(key=lambda x: float(x), reverse=True)
        return labeled_candidates[0]
    if header_tp:
        return header_tp
    m = re.search(
        r"(?:P50\s*)?(?:目标价|target price)[：:\s|]*\*{0,2}([\d.]+)\*{0,2}",
        s4,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _extract_forward_pe(ws: Path, peb: dict | None, cv: dict | None, read_model_text) -> str | None:
    """Extract forward PE from JSON artifacts or markdown."""
    if peb and isinstance(peb, dict) and "current_forward_pe" in peb:
        return f"{peb['current_forward_pe']:.1f}x"
    if cv and isinstance(cv, dict):
        for key in (
            "pe_forward",
            "pe_forward_t2_ngaap",
            "pe_forward_t1_ngaap",
            "pe_forward_t2",
            "pe_forward_t1",
            "pe_ttm_ngaap",
            "pe_ttm",
        ):
            if key in cv and cv[key]:
                v = cv[key]
                if isinstance(v, dict):
                    pe_value = v.get("pe", v.get("value"))
                    if pe_value is not None:
                        return (
                            f"{pe_value:.1f}x"
                            if isinstance(pe_value, (int, float))
                            else str(pe_value) + "x"
                        )
                elif isinstance(v, (int, float)):
                    return f"{v:.1f}x"
                else:
                    return str(v) + "x"
    s4 = read_model_text()
    for pattern in (
        r"当前\s*Forward\s*PE[：:]*\s*([\d.]+)x",
        r"P50\s*Forward\s*PE[^*]*?\*{0,2}([\d.]+)x",
        r"Forward\s*PE\s*\|[^|]*?([\d.]+)x",
        r"PE\(Forward[^)]*\)[^(]*?([\d.]+)x",
        r"Forward PE[^(]*?([\d.]+)x",
    ):
        m = re.search(pattern, s4)
        if m:
            return m.group(1) + "x"
    return None


def _extract_rrr(mc: dict, read_file) -> str | None:
    """Extract RRR from JSON or Step 7 markdown."""
    if mc.get("rrr") is not None:
        rrr_val = mc["rrr"]
        return f"{rrr_val:.2f}" if isinstance(rrr_val, float) else str(rrr_val)
    s5 = read_file("step7_rrr_strategy.md")
    for pattern in (
        r"\*\*RRR[^*]*\*\*\s*\|?\s*\*{0,2}([\d.]+)\*{0,2}",
        r"RRR\s*[=：:]\s*\*{0,2}([\d.]+)\*{0,2}",
        r"RRR\s*\([^)]*\)\s*[=：:]?\s*([\d.]+)",
        r"RRR.{0,30}?([\d]+\.[\d]+)",
    ):
        m = re.search(pattern, s5)
        if m:
            return m.group(1)
    return None


def _extract_moat(ws: Path, read_file) -> str | None:
    """Extract moat classification from Step 2 markdown."""
    s2 = read_file("step2_competitive_moat.md")
    m = re.search(
        r"(Wide|Narrow|None)\s*(?:Moat)?\s*,?\s*(Widening|Stable|Narrowing)", s2, re.IGNORECASE
    )
    if m:
        return f"{m.group(1)} {m.group(2)}"
    if re.search(r"Narrow", s2):
        return "Narrow"
    return None


def _extract_edge_score(ws: Path, thesis: dict | None) -> tuple[str | None, str | None]:
    """Extract edge_score and edge_grade from JSON artifacts."""
    ej = ws / "edge_score.json"
    if ej.exists():
        try:
            data = json.loads(ej.read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = data[-1]
            return str(data.get("composite", data.get("edge_score", ""))), data.get(
                "composite_grade", data.get("grade", "")
            )
        except Exception:
            pass
    if thesis and isinstance(thesis, dict):
        t = thesis
        if "history" in t and isinstance(t["history"], list) and t["history"]:
            latest = t["history"][-1]
            if "edge_score" in latest:
                return str(latest["edge_score"]), latest.get("edge_grade", "")
        if "edge_score" in t:
            return str(t["edge_score"]), t.get("edge_grade", "")
    return None, None


def _extract_decision(ws: Path, read_file) -> str | None:
    """Extract decision from Step 9 markdown."""
    s7 = read_file("step9_research_director_review.md")
    m = re.search(r"\b(Buy|Hold|Pass)\b", s7)
    return m.group(1) if m else None


def _sanity_check_metrics(metrics: dict, ws: Path, sa: dict | None, read_file):
    """Validate extracted metrics and attempt recovery if ratios look wrong."""
    current_price = float(metrics.get("current_price", 0)) if metrics.get("current_price") else 0
    target_price = float(metrics.get("target_price", 0)) if metrics.get("target_price") else 0
    if current_price > 0 and target_price > 0:
        ratio = target_price / current_price
        if ratio < 0.3 or ratio > 5.0:
            logger.warning(
                "Extracted target_price=%s vs current_price=%s (ratio=%.2f) looks unreasonable. "
                "Attempting structured JSON recovery.",
                target_price,
                current_price,
                ratio,
            )
            if sa and isinstance(sa, dict):
                fmi_rec = sa.get("financial_model_inputs", {})
                recovered = fmi_rec.get("p50_target_hkd")
                if recovered is not None:
                    metrics["target_price"] = (
                        f"{recovered:.2f}" if isinstance(recovered, float) else str(recovered)
                    )
                    logger.info(
                        "Recovered target_price=%s from step4_structured_assumptions.json",
                        metrics["target_price"],
                    )
            if float(metrics.get("target_price", 0)) / current_price < 0.3:
                s5 = read_file("step7_rrr_strategy.md")
                m5 = re.search(r"P50\s+Target\s*(?:Price\s*)?\|\s*[¥HKD]*\s*([\d.]+)", s5)
                if m5 and float(m5.group(1)) >= current_price * 0.3:
                    metrics["target_price"] = m5.group(1)


def _extract_summary_metrics(workspace_dir, ticker: str) -> dict:
    """Extract key metrics from workspace JSON artifacts first, then markdown parsing.

    Priority order for each metric:
      1. Structured JSON files (monte_carlo_results.json, pe_band_data.json, etc.)
      2. Markdown regex parsing of canonical step files
    """
    ws = Path(workspace_dir)
    metrics = {}

    def _read_file(name):
        p = ws / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _read_model_text():
        chunks = [
            _read_file(name)
            for name in (
                "step4_assumption_research.md",
                "step5_financial_model.md",
                "step6_monte_carlo_simulation.md",
            )
        ]
        return "\n\n".join(chunk for chunk in chunks if chunk)

    # ── Load all available JSON artifacts ──────────────────────────────────
    for summary_name in ("summary_metrics.json", "report_metrics.json"):
        summary = _read_json_safe(ws, summary_name)
        if isinstance(summary, dict):
            for key, value in summary.items():
                if value is not None:
                    metrics[key] = str(value)
            break

    mc_raw = _read_json_safe(ws, "monte_carlo_results.json")
    if mc_raw is None:
        mc_raw = _read_json_safe(ws, "monte_carlo_result.json")
    mc = _normalize_mc_json(mc_raw) if isinstance(mc_raw, dict) else {}
    cv = _read_json_safe(ws, "calculated_valuation.json")
    peb = _read_json_safe(ws, "pe_band_data.json")
    thesis = _read_json_safe(ws, "thesis.json")
    sa = _read_json_safe(ws, "step4_structured_assumptions.json")

    # ── Extract each metric ────────────────────────────────────────────────
    if "current_price" not in metrics:
        cp = _extract_current_price(ws, mc, cv, _read_model_text)
        if cp:
            metrics["current_price"] = cp

    if "target_price" not in metrics:
        tp = _extract_target_price(ws, mc, sa, _read_model_text)
        if tp:
            metrics["target_price"] = tp

    if "forward_pe" not in metrics:
        fpe = _extract_forward_pe(ws, peb, cv, _read_model_text)
        if fpe:
            metrics["forward_pe"] = fpe

    if "rrr" not in metrics:
        rrr = _extract_rrr(mc, _read_file)
        if rrr:
            metrics["rrr"] = rrr

    moat = _extract_moat(ws, _read_file)
    if moat:
        metrics["moat"] = moat

    es, eg = _extract_edge_score(ws, thesis)
    if es:
        metrics["edge_score"] = es
    if eg:
        metrics["edge_grade"] = eg

    decision = _extract_decision(ws, _read_file)
    if decision:
        metrics["decision"] = decision

    _sanity_check_metrics(metrics, ws, sa, _read_file)

    return metrics


# ---------------------------------------------------------------------------
# Auto-embed workspace images (prevents missing charts)
# ---------------------------------------------------------------------------

# Mapping of known PNG filenames to step keys for targeted embedding
_IMAGE_STEP_MAP = {
    "monte_carlo_distribution.png": "step6",
    "monte_carlo_distribution_corrected.png": "step6",
    "monte_carlo_distribution_v3.png": "step6",
    "monte_carlo_distributions.png": "step6",
    "forward_pe_band.png": "step6",
    "eps_distribution.png": "step6",
    "eps_pe_scatter.png": "step6",
    "revenue_driver_bridge.png": "step4",
    "revenue_bridge.png": "step4",
    "target_price_distribution.png": "step6",
    "distribution_chart.png": "step6",
}


def _embed_image_as_base64(img_path: Path, alt_text: str = "") -> str:
    """Embed a single image file as base64 into an HTML chart container."""
    if not img_path.exists():
        return ""
    data = base64.b64encode(img_path.read_bytes()).decode("ascii")
    caption = escape(alt_text or img_path.stem.replace("_", " ").title(), quote=True)
    source = escape(img_path.name, quote=True)
    mime = _image_mime(img_path)
    return (
        f'<div class="chart-container">'
        f'<img data-source="{source}" src="data:{mime};base64,{data}" alt="{caption}">'
        f'<p class="chart-caption">{caption}</p></div>'
    )


def _auto_embed_workspace_images(ws: Path, sections_html: str) -> str:
    """Inject un-embedded workspace PNGs via ``<!-- AUTO_IMAGES:stepN -->`` markers.

    Uses deterministic marker replacement instead of fragile HTML-structure slicing.
    Each marker is replaced with base64-encoded <img> blocks for PNGs mapped to
    that step. Unmatched images are appended to an appendix section.
    """
    png_files = sorted(ws.glob("*.png"))
    if not png_files:
        return sections_html

    # Detect already-embedded images by actual base64 data URIs in the HTML
    already_embedded = {
        png.name for png in png_files if f'data-source="{png.name}"' in sections_html
    }

    # Group un-embedded PNGs by target step
    step_images: dict[str, list[tuple[Path, str]]] = {}
    appendix_images: list[Path] = []

    for png in png_files:
        if png.name in already_embedded:
            continue
        target_step = _IMAGE_STEP_MAP.get(png.name)
        if target_step:
            step_images.setdefault(target_step, []).append(
                (png, png.stem.replace("_", " ").title())
            )
        else:
            appendix_images.append(png)

    # Replace each marker with the matching image HTML
    for step_key, images in step_images.items():
        injection = ""
        for img_path, alt_text in images:
            chunk = _embed_image_as_base64(img_path, alt_text)
            if chunk:
                injection += chunk
        if not injection:
            continue
        marker = f"<!-- AUTO_IMAGES:{step_key} -->"
        sections_html = sections_html.replace(marker, injection + marker, 1)

    # Build appendix for unmatched images
    if appendix_images:
        appendix_body = ""
        for img_path in appendix_images:
            alt = img_path.stem.replace("_", " ").title()
            chunk = _embed_image_as_base64(img_path, alt)
            if chunk:
                appendix_body += chunk
        if appendix_body:
            appendix_section = (
                '<div id="charts-appendix" class="section-card">'
                '<div class="section-header" onclick="toggleSection(this)">'
                '<h2><i class="fas fa-chart-bar"></i> Charts & Exhibits</h2>'
                '<span class="toggle"><i class="fas fa-chevron-down"></i></span></div>'
                f'<div class="section-body">{appendix_body}</div></div>'
            )
            sections_html += appendix_section

    return sections_html


# ---------------------------------------------------------------------------
# Auto-generated 1-Page Summary (Markdown)
# ---------------------------------------------------------------------------


def _extract_conclusion(text: str, max_len: int = 200) -> str:
    """Extract the strongest one-sentence conclusion from a step markdown file."""
    # Priority 1: Explicit "**Conclusion**:" line (not too long)
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**Conclusion**") or stripped.startswith("**核心结论**"):
            content = stripped.split("：", 1)[-1].split(":", 1)[-1].strip().lstrip("*").strip()
            if 15 < len(content) < max_len:
                return content

    # Priority 2: "**Decision**:" line
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**Decision:"):
            content = stripped.replace("**Decision:", "").strip().lstrip("*").strip()
            if 5 < len(content) < max_len:
                return content

    # Priority 3: "**Rating**:" line
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**Rating**"):
            content = stripped.split(":", 1)[-1].strip().lstrip("*").strip()
            if 5 < len(content) < max_len:
                return content

    # Priority 4: First bold sentence that looks like a key finding
    for line in text.split("\n"):
        stripped = line.strip()
        m = re.match(r"\*\*(.+?)\*\*[:：]\s*(.+)$", stripped)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            # Skip meta keys, keep finding keys
            if key.lower() not in ("note", "source", "see", "date", "example", "usage"):
                combined = f"{key}: {val}"
                if 10 < len(combined) < max_len:
                    return combined

    return ""


def _extract_metrics(text: str) -> dict:
    """Extract key metrics from step files (table rows with numbers)."""
    metrics = {}
    # Look for common metric patterns in tables
    for line in text.split("\n"):
        # Match table rows like "| EPS | 12.0 | ..." or "| **EPS** | **12.0** |"
        m = re.match(
            r"\|\s*\*{0,2}(EPS|PE|毛利率|Gross Margin|P50 Target|Revenue Growth|净利|营收增速|RRR|ROE|目标价)\*{0,2}\s*\|\s*\*{0,2}([0-9.]+[%x]?)\*{0,2}",
            line,
        )
        if m:
            metrics[m.group(1).strip("*")] = m.group(2).strip("*")
    return metrics


def generate_summary_md(
    workspace_dir, ticker: str, company_name: str = "", lang: str = "zh"
) -> Path:
    """Auto-generate a compact 1-page summary MD from step files + structured data.

    Args:
        lang: 'zh' (default, Chinese) or 'en' (English).
    """
    from datetime import datetime

    ws = Path(workspace_dir)
    date_str = datetime.now().strftime("%Y%m%d")
    is_zh = lang == "zh"

    # ── Language dictionaries ──
    if is_zh:
        TITLE = "一页研报摘要"
        FRAMEWORK = "InvestPilot 深度研究"
        TRIAGE = "筛选"
        STEP_TITLES = {
            1: "业务深研",
            2: "护城河",
            3: "预期差",
            4: "假设矩阵",
            5: "财务模型",
            6: "蒙特卡洛",
            7: "赔率与策略",
            8: "审计",
            9: "投委会决策",
        }
        PE_LABEL = "PE TTM"
        EPS_LABEL = "EPS P50"
        TARGET_LABEL = "目标价"
        WIN_LABEL = "胜率"
        MED_LABEL = "中位回报"
        CHARTS_LABEL = "图表与详情"
        HKD = "港元"
        RMB = "元"
    else:
        TITLE = "1-Page Research Summary"
        FRAMEWORK = "InvestPilot Deep Research"
        TRIAGE = "Triage"
        STEP_TITLES = {
            1: "Business",
            2: "Moat",
            3: "Catalyst",
            4: "Assumptions",
            5: "Model",
            6: "Monte Carlo",
            7: "RRR",
            8: "Audit",
            9: "Decision",
        }
        PE_LABEL = "PE TTM"
        EPS_LABEL = "EPS P50"
        TARGET_LABEL = "Target"
        WIN_LABEL = "Win"
        MED_LABEL = "Med R"
        CHARTS_LABEL = "Charts & details"
        HKD = "HKD"
        RMB = "RMB"

    # Load structured data
    mc_stats = {}
    if (ws / "monte_carlo_stats.json").exists():
        with contextlib.suppress(BaseException):
            mc_stats = json.loads((ws / "monte_carlo_stats.json").read_text(encoding="utf-8"))
    calc_val = {}
    if (ws / "calculated_valuation.json").exists():
        with contextlib.suppress(BaseException):
            calc_val = json.loads((ws / "calculated_valuation.json").read_text(encoding="utf-8"))

    # Find canonical step files
    step_files = sorted(ws.glob("step*_*.md"))
    canonical = {}
    for sf in step_files:
        if any(x in sf.name for x in ("_blockers", "_guard_", "_structured", "step4_quantitative")):
            continue
        m = re.match(r"step(\d+)_", sf.name)
        if m and 0 <= int(m.group(1)) <= 9:
            canonical[int(m.group(1))] = sf

    # Company name from step1 title
    if not company_name and 1 in canonical:
        first_line = canonical[1].read_text(encoding="utf-8").split("\n")[0]
        m = re.search(r"\((.+?)\)", first_line)
        if m:
            cn = m.group(1).strip().split("/")[0].strip()
            if cn and len(cn) > 1:
                company_name = cn
    if not company_name:
        company_name = ticker

    display_name = company_name.replace(f"({ticker})", "").replace(ticker, "").strip().rstrip("()")

    # ── Build ──
    pe_val = ""
    pe_ttm = calc_val.get("pe_trailing", {})
    if isinstance(pe_ttm, dict):
        pe_val = pe_ttm.get("value", "")
    eps_p50 = mc_stats.get("eps_p50", "")
    tp_hkd = mc_stats.get("target_p50_hkd", "")
    prob_pos = mc_stats.get("prob_positive", "")
    med_ret = mc_stats.get("median_return_pct", "")

    lines = [
        f"# {display_name} ({ticker}) — {TITLE}",
        f"**{datetime.now().strftime('%Y-%m-%d')}** | {FRAMEWORK}",
        "",
    ]

    # Metric bar
    parts = []
    if pe_val:
        parts.append(f"{PE_LABEL}: {pe_val}x")
    if eps_p50:
        parts.append(f"{EPS_LABEL}: {eps_p50} {RMB}")
    if tp_hkd:
        parts.append(f"{TARGET_LABEL}: {tp_hkd} {HKD}")
    if prob_pos:
        parts.append(f"{WIN_LABEL}: {prob_pos}%")
    if med_ret:
        parts.append(f"{MED_LABEL}: +{med_ret}%")
    if parts:
        lines.append("| " + " | ".join(parts) + " |\n")

    lines.append("---\n")

    # Step 0
    if 0 in canonical:
        text = canonical[0].read_text(encoding="utf-8")
        for ln in text.split("\n"):
            if ln.strip().startswith("**Decision:"):
                d = ln.strip().replace("**Decision:", "").strip().lstrip("*").strip()
                lines.append(f"**{TRIAGE}**: {d}")
                break

    # Steps 1-9
    for sn in range(1, 10):
        if sn not in canonical:
            continue
        text = canonical[sn].read_text(encoding="utf-8")
        f = _extract_conclusion(text)
        if not f:
            for ln in text.split("\n")[:50]:
                m = re.match(
                    r"\*\*(EPS|Target|PE|RRR|Revenue|概率|仓位|Rating|毛利率|ROE|Moat)\s*(?:P\d{2})?\*{0,2}\s*:\s*\*{0,2}(.+?)\*{0,2}$",
                    ln.strip(),
                )
                if m:
                    f = f"{m.group(1).strip('*')}: {m.group(2).strip('*')}"
                    break
        if f:
            if len(f) > 120:
                f = f[:117] + "..."
            lines.append(f"- **{STEP_TITLES.get(sn, f'S{sn}')}**: {f}")

    lines += [
        "",
        "---",
        f"*{CHARTS_LABEL}: [{ticker}_report_{date_str}.html]({ticker}_report_{date_str}.html)*",
    ]

    output_path = ws / f"{ticker}_summary_{date_str}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Main HTML report generator
# ---------------------------------------------------------------------------


def generate_report_html(
    workspace_dir,
    ticker: str,
    company_name: str = "",
    summary_overrides: dict = None,
) -> Path:
    """Generate a self-contained HTML research report.

    Args:
        workspace_dir: Path to workspace directory (string or Path).
        ticker: Stock ticker (e.g., "09992.HK").
        company_name: Display name. If empty, extracted from step1 title.
        summary_overrides: Optional dict to override auto-extracted metrics.

    Returns:
        Path to the generated HTML file.
    """
    from datetime import datetime
    from pathlib import Path

    from src.report._html_templates import HTML_SKELETON, REPORT_CSS, REPORT_JS, STEP_CONFIG

    ws = Path(workspace_dir)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Read step files ---
    steps = []
    for cfg in STEP_CONFIG:
        fpath = ws / cfg["file"]
        if fpath.exists():
            md = fpath.read_text(encoding="utf-8")
            # Extract company name from step1 title if not provided
            if cfg["key"] == "step1" and not company_name:
                m = re.match(r"#\s*Step\s*1:\s*(.+?)(?:\s*\(|$)", md, re.MULTILINE)
                if m:
                    company_name = m.group(1).strip()
            steps.append({**cfg, "content": md})
        else:
            if not cfg.get("optional"):
                logger.warning("%s not found, skipping", cfg["file"])
            steps.append({**cfg, "content": ""})

    # --- Extract summary metrics ---
    metrics = _extract_summary_metrics(ws, ticker)
    if summary_overrides:
        metrics.update(summary_overrides)

    # --- Determine currency from ticker ---
    from config.ticker_rules import detect_market

    market = detect_market(ticker)
    currency = {"ASHARE": "CNY", "HK": "HKD", "US": "USD"}.get(market, "CNY")

    # --- Build summary cards ---
    card_defs = [
        ("current_price", "Current Price", currency, "blue"),
        ("target_price", "P50 Target", currency, "green"),
        ("rrr", "RRR", "", "green"),
        ("forward_pe", "Forward PE", "", "blue"),
        ("moat", "Moat", "", "amber"),
        ("edge_score", "Edge Score", "", "amber"),
    ]
    summary_cards = []
    for key, label, unit, color in card_defs:
        val = metrics.get(key)
        if val:
            sub = (
                f" / {metrics['edge_grade']}"
                if key == "edge_score" and metrics.get("edge_grade")
                else unit
            )
            summary_cards.append(
                f'<div class="summary-card {color}">'
                f'<div class="label">{escape(label, quote=True)}</div>'
                f'<div class="value">{escape(str(val), quote=True)}</div>'
                f'<div class="sub">{escape(str(sub), quote=True)}</div></div>'
            )
    summary_html = (
        f'<div class="summary-grid">{"".join(summary_cards)}</div>' if summary_cards else ""
    )

    # --- Build TOC ---
    toc_items = []
    for cfg in STEP_CONFIG:
        toc_items.append(
            f'<li><a href="#{cfg["key"]}"><i class="{cfg["icon"]}"></i> {cfg["title"]}</a></li>'
        )
    model_html_body = ""
    model_link_html = ""
    forecast_model_html = ws / "forecast_model.html"
    if forecast_model_html.exists():
        try:
            model_html_body = forecast_model_html.read_text(encoding="utf-8")
            # Extract just the body content (between <body> and </body> or use as-is)
            body_match = re.search(r"<body>(.*?)</body>", model_html_body, re.DOTALL)
            if body_match:
                # Extract content between <h1> and end of body, or use full match
                inner = body_match.group(1)
                h1_start = inner.find("<h1>")
                if h1_start != -1:
                    inner = inner[h1_start + len("<h1>") :]
                    h1_end = inner.find("</h1>")
                    if h1_end != -1:
                        inner = inner[h1_end + len("</h1>") :]
                model_html_body = inner.strip()
            model_link_html = (
                "<p><strong>Standalone model:</strong> "
                f"{escape(forecast_model_html.name, quote=True)}</p>"
            )
        except Exception as e:
            model_html_body = (
                f"<p><em>Error reading forecast model: {escape(str(e), quote=True)}</em></p>"
            )
    if model_html_body:
        toc_items.append(
            '<li><a href="#forecast-model"><i class="fas fa-table"></i> Forecast Model</a></li>'
        )
    toc_html = f'<div class="toc"><h2>Table of Contents</h2><ul class="toc-list">{"".join(toc_items)}</ul></div>'

    # --- Build sidebar ---
    sidebar_items = []
    for cfg in STEP_CONFIG:
        sidebar_items.append(
            f'<a href="#{cfg["key"]}"><i class="{cfg["icon"]}"></i> {cfg["title"]}</a>'
        )
    if model_html_body:
        sidebar_items.append(
            '<a href="#forecast-model"><i class="fas fa-table"></i> Forecast Model</a>'
        )
    sidebar_html = (
        '<div class="sidebar"><div class="nav-section">'
        f"<h3>Navigation</h3>{''.join(sidebar_items)}"
        "</div></div>"
    )

    # --- Build sections ---
    sections_html = ""
    for step in steps:
        if not step["content"]:
            continue
        body_html = md_to_html(step["content"], ws)
        sections_html += (
            f'<div id="{step["key"]}" class="section-card">'
            f'<div class="section-header" onclick="toggleSection(this)">'
            f'<h2><i class="{step["icon"]}"></i> {step["title"]}</h2>'
            f'<span class="toggle"><i class="fas fa-chevron-down"></i></span></div>'
            f'<div class="section-body">{body_html}'
            f"<!-- AUTO_IMAGES:{step['key']} --></div></div>"
        )

    # --- Auto-generate Monte Carlo distribution chart from structured assumptions ---
    sa_path = ws / "step4_structured_assumptions.json"
    mc_dist_generated = False
    if sa_path.exists():
        try:
            sa = json.loads(sa_path.read_text(encoding="utf-8"))
            fmi = sa.get("financial_model_inputs", {})

            # ---------------------------------------------------------------
            # Approach D (PRIMARY): histogram from MC percentile data
            # Works for all model types (PB×BPS banks, EPS×PE equities)
            # Generates distribution_chart.png (Pop Mart style histogram)
            # ---------------------------------------------------------------
            mc_json = ws / "monte_carlo_results.json"
            if mc_json.exists():
                try:
                    mc_data = json.loads(mc_json.read_text(encoding="utf-8"))
                    scenarios = []

                    # Check for multi-year (Pop Mart style: per_year)
                    per_year = mc_data.get("per_year", {})
                    if per_year:
                        for yr_label, yr_data in per_year.items():
                            tp = yr_data.get("target_price_hkd") or yr_data.get("target_price")
                            if isinstance(tp, dict):
                                yr_price = (
                                    mc_data.get("current_price_hkd")
                                    or yr_data.get("current_price_hkd")
                                    or tp.get("current_price_hkd")
                                )
                                scenarios.append(
                                    {
                                        "label": yr_label,
                                        "percentiles": tp,
                                        "current_price": yr_price,
                                        "n_simulations": mc_data.get("n_simulations", 20000),
                                        "subtitle": f"{mc_data.get('n_simulations', 20000):,} simulations",
                                    }
                                )

                    # Single-year (A-share bank style)
                    if not scenarios:
                        tp_pctls = (
                            mc_data.get("filtered_target_price_percentiles")
                            or mc_data.get("target_price_percentiles")
                            or mc_data.get("target_price")
                        )
                        if isinstance(tp_pctls, dict) and len(tp_pctls) >= 3:
                            cur = mc_data.get("current_price")
                            n_sims = mc_data.get("n_simulations", 20000)
                            ks = mc_data.get("kill_switch", {})
                            filter_desc = ""
                            if ks:
                                parts = []
                                if ks.get("roe_threshold_pct"):
                                    parts.append(f"ROE ≥ {ks['roe_threshold_pct']}%")
                                if ks.get("npl_threshold_pct"):
                                    parts.append(f"NPL ≤ {ks['npl_threshold_pct']}%")
                                if parts:
                                    filter_desc = f"Filtered: {' & '.join(parts)}"
                            val_primary = mc_data.get("valuation_primary", "")
                            scenario_label = "T+1"
                            if val_primary:
                                scenario_label = f"T+1 ({val_primary.upper()})"
                            scenarios.append(
                                {
                                    "label": scenario_label,
                                    "percentiles": tp_pctls,
                                    "current_price": cur,
                                    "n_simulations": n_sims,
                                    "subtitle": (
                                        f"{n_sims:,} simulations"
                                        + (f"\n{filter_desc}" if filter_desc else "")
                                    ),
                                }
                            )

                    if scenarios:
                        dist_png = ws / "distribution_chart.png"
                        generate_histogram_from_percentiles(
                            scenarios=scenarios,
                            title=f"{ticker} Monte Carlo Target Price Distribution",
                            save_path=dist_png,
                            currency=currency,
                            n_samples=max(s.get("n_simulations", 20000) for s in scenarios),
                        )
                        if dist_png.exists():
                            print(f"  ✓ Distribution chart (histogram) generated: {dist_png}")
                            mc_dist_generated = True
                except Exception as e:
                    logger.warning("Approach D histogram generation failed: %s", e)

            # ---------------------------------------------------------------
            # Approach A/B/C (FALLBACK): old density-style chart
            # Only runs if Approach D did not produce a chart
            # Generates monte_carlo_distribution.png
            # ---------------------------------------------------------------

            # Helper: extract P10/P30/P50/P70/P90 from a list-based assumption_matrix
            def _find_in_matrix(am_list, variable, year="2026E"):
                for item in am_list if isinstance(am_list, list) else []:
                    if item.get("variable") == variable and item.get("year") == year:
                        return item
                return None

            # Approach A (new): list-based assumption_matrix
            am_raw = sa.get("assumption_matrix", [])
            if not mc_dist_generated and isinstance(am_raw, list):
                eps_item = _find_in_matrix(am_raw, "eps")
                pe_item = _find_in_matrix(am_raw, "pe")
                if eps_item and pe_item:
                    pcts = [10, 30, 50, 70, 90]
                    required_keys = [f"p{p}" for p in pcts]
                    has_eps = all(p in eps_item for p in required_keys)
                    has_pe = all(p in pe_item for p in required_keys)
                    if has_eps and has_pe:
                        price_pcts = {}
                        for p in pcts:
                            eps_val = eps_item.get(f"p{p}")
                            pe_val = pe_item.get(f"p{p}")
                            if eps_val is not None and pe_val is not None:
                                price_pcts[p] = float(eps_val) * float(pe_val)
                        if all(p in price_pcts for p in pcts):
                            mc_png = ws / "monte_carlo_distribution.png"
                            cur_price = sa.get("current_price_hkd")
                            generate_distribution_from_percentiles(
                                p10=price_pcts[10],
                                p30=price_pcts[30],
                                p50=price_pcts[50],
                                p70=price_pcts[70],
                                p90=price_pcts[90],
                                title=f"{ticker} Monte Carlo Target Price Distribution (20,000 runs, t-Copula df=6)",
                                current_price=cur_price,
                                save_path=mc_png,
                                currency=currency,
                            )
                            if mc_png.exists():
                                print(f"  ✓ Monte Carlo distribution chart generated: {mc_png}")
                                mc_dist_generated = True

            # Approach B (legacy): dict-based assumption_matrix with T1_FY2026E
            if not mc_dist_generated and isinstance(am_raw, dict):
                _am = am_raw
                am = _am.get("T1_FY2026E", {})
                rg = am.get("revenue_growth", {})
                npm = am.get("npm", am.get("net_profit_margin", am.get("pe", {})))
                pe = am.get("pe_fwd_t1", am.get("pe_multiple", am.get("pe", {})))

                def _pct_get(d, pct):
                    return (
                        d.get(f"p{pct}", d.get(str(pct), d.get(pct)))
                        if isinstance(d, dict)
                        else None
                    )

                def _ratio_value(d, pct):
                    v = _pct_get(d, pct)
                    if v is None:
                        return None
                    v = float(v)
                    return v / 100.0 if abs(v) > 1.0 else v

                def _number_value(d, pct):
                    v = _pct_get(d, pct)
                    return float(v) if v is not None else None

                required_pcts = [10, 30, 50, 70, 90]
                if all(
                    _ratio_value(rg, p) is not None
                    and _ratio_value(npm, p) is not None
                    and _number_value(pe, p) is not None
                    for p in required_pcts
                ):
                    base_rev = sa.get("base_revenue_cny_m", 0)
                    shares = fmi.get("shares_outstanding", 1)
                    fx = fmi.get("hkd_cny", 1.0)
                    if base_rev and shares and fx and float(shares) > 0 and float(fx) > 0:
                        price_pcts = {}
                        for p in required_pcts:
                            rev = float(base_rev) * (1 + _ratio_value(rg, p))
                            ni = rev * _ratio_value(npm, p)
                            eps = ni * 1e4 / float(shares)
                            target = eps * _number_value(pe, p) / float(fx)
                            price_pcts[p] = target
                        mc_png = ws / "monte_carlo_distribution.png"
                        cur_price = sa.get("current_price_hkd")
                        generate_distribution_from_percentiles(
                            p10=price_pcts[10],
                            p30=price_pcts[30],
                            p50=price_pcts[50],
                            p70=price_pcts[70],
                            p90=price_pcts[90],
                            title=f"{ticker} Monte Carlo Target Price Distribution (20,000 runs)",
                            current_price=cur_price,
                            save_path=mc_png,
                            currency=currency,
                        )
                        if mc_png.exists():
                            print(f"  ✓ Monte Carlo distribution chart generated: {mc_png}")
                            mc_dist_generated = True

            # Approach C: fallback to monte_carlo_results.json (old format)
            if not mc_dist_generated and mc_json.exists():
                mc_data = json.loads(mc_json.read_text(encoding="utf-8"))
                p10_data = mc_data.get("p10_case", {})
                p50_data = mc_data.get("p50_case", {})
                p90_data = mc_data.get("p90_case", {})
                if (
                    p10_data.get("target_price_hkd")
                    and p50_data.get("target_price_hkd")
                    and p90_data.get("target_price_hkd")
                ):
                    mc_png = ws / "monte_carlo_distribution.png"
                    n_sims = mc_data.get("n_simulations", 20000)
                    generate_distribution_from_percentiles(
                        p10=p10_data["target_price_hkd"],
                        p30=(p10_data["target_price_hkd"] + p50_data["target_price_hkd"]) / 2,
                        p50=p50_data["target_price_hkd"],
                        p70=(p50_data["target_price_hkd"] + p90_data["target_price_hkd"]) / 2,
                        p90=p90_data["target_price_hkd"],
                        title=f"{ticker} Monte Carlo Target Price Distribution ({n_sims:,} runs, t-Copula df=6)",
                        current_price=sa.get("current_price_hkd") if sa else None,
                        save_path=mc_png,
                        currency=currency,
                    )
                    if mc_png.exists():
                        print(
                            "  ✓ Monte Carlo distribution chart generated from monte_carlo_results.json"
                        )

        except Exception as e:
            logger.warning("Monte Carlo chart generation skipped: %s", e)

    # --- Auto-embed workspace images not referenced in markdown ---
    sections_html = _auto_embed_workspace_images(ws, sections_html)

    if model_html_body:
        sections_html += (
            '<div id="forecast-model" class="section-card">'
            '<div class="section-header" onclick="toggleSection(this)">'
            '<h2><i class="fas fa-table"></i> Forecast Model</h2>'
            '<span class="toggle"><i class="fas fa-chevron-down"></i></span></div>'
            f'<div class="section-body">{model_link_html}{model_html_body}</div></div>'
        )

    # --- Build header ---
    display_name = company_name or ticker
    display_name_html = escape(str(display_name), quote=True)
    ticker_html = escape(str(ticker), quote=True)
    title = escape(f"{display_name} ({ticker}) 深度投研报告 | {date_str}", quote=True)
    price_part = (
        f" | Current: <strong>{escape(str(metrics.get('current_price')), quote=True)}</strong>"
        if metrics.get("current_price")
        else ""
    )
    decision_part = escape(str(metrics.get("decision", "N/A")), quote=True)
    header_html = (
        f'<div class="sticky-header">'
        f'<div class="logo">Invest<span>Pilot</span> | {display_name_html} ({ticker_html})</div>'
        f'<div class="meta">Report Date: <strong>{date_str}</strong>{price_part}'
        f" | Decision: <strong>{decision_part}</strong></div></div>"
    )

    # --- Footer ---
    footer_text = (
        '<div class="footer">'
        "<p><strong>Disclaimer</strong></p>"
        "<p>This report is generated by InvestPilot AI Research for informational purposes only. "
        "It does not constitute investment advice. Past performance does not guarantee future results.</p>"
        f'<p style="margin-top:12px;color:rgba(255,255,255,0.4)">InvestPilot Deep Fundamental Research Harness | {date_str}</p>'
        "</div>"
    )

    # --- Assemble HTML ---
    html = HTML_SKELETON.format(
        title=title,
        css=REPORT_CSS,
        js=REPORT_JS,
        header_html=header_html,
        sidebar_html=sidebar_html,
        summary_html=summary_html,
        toc_html=toc_html,
        sections_html=sections_html,
        footer_html=footer_text,
    )

    filename = f"{ticker}_report_{datetime.now().strftime('%Y%m%d')}.html"
    output_path = ws / filename
    output_path.write_text(html, encoding="utf-8")
    return output_path
