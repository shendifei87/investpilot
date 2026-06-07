import mistune
import re
import json
import base64
import logging
from html import escape
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional

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
    n_samples: int = 50000,
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
    from scipy.stats import skewnorm

    # --- Calibrate skew-normal to match P10 / P50 / P90 ---
    # We use scipy.optimize to find (a, loc, scale) such that the
    # skew-normal percentiles match the supplied ones.
    from scipy.optimize import minimize

    target_pcts = np.array([10, 50, 90])
    target_vals = np.array([p10, p50, p90])

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
    result = minimize(_loss, x0=[0.0, init_loc, init_scale],
                      method="Nelder-Mead", options={"maxiter": 5000})
    a_opt, loc_opt, scale_opt = result.x
    if scale_opt <= 0:
        scale_opt = init_scale

    # Generate synthetic samples
    samples = skewnorm.rvs(a_opt, loc=loc_opt, scale=scale_opt,
                           size=n_samples, random_state=42)

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

    ax.hist(visible, bins=80, density=True, alpha=0.7,
            color="#4361ee", edgecolor="white", linewidth=0.3)

    # Percentile lines
    pct_data = {10: (p10, "#e63946", "P10 (Bear)"),
                30: (p30, "#f4a261", "P30"),
                50: (p50, "#2a9d8f", "P50 (Base)"),
                70: (p70, "#f4a261", "P70"),
                90: (p90, "#e63946", "P90 (Bull)")}
    for pct, (val, color, label) in pct_data.items():
        ax.axvline(val, color=color, linestyle="--", linewidth=1.5, alpha=0.85,
                   label=f"{label}: {val:.1f} {currency}")

    # Current price
    if current_price is not None:
        ax.axvline(current_price, color="black", linewidth=2.5,
                   label=f"Current: {current_price:.1f} {currency}")

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
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

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
        dates, bands["p10"], bands["p90"],
        alpha=0.15, color="#4361ee", label="P10-P90",
    )
    ax.fill_between(
        dates, bands["p25"], bands["p75"],
        alpha=0.25, color="#4361ee", label="P25-P75",
    )

    # Median line
    ax.axhline(bands["p50"], color="#4361ee", linestyle="--", linewidth=1, alpha=0.7,
               label=f"Median: {bands['p50']:.1f}x")

    # PE time series
    ax.plot(dates, pe_series, color="#1a1a2e", linewidth=1.0, label="Forward PE")

    # Current PE line
    ax.axhline(current_pe, color="#e63946", linewidth=2, alpha=0.9,
               label=f"Current: {current_pe:.1f}x ({current_pct:.0f}th %ile)")

    # Annotate current PE
    ax.annotate(
        f"  {current_pe:.1f}x ({current_pct:.0f}th)",
        xy=(dates[-1], current_pe),
        fontsize=10, fontweight="bold", color="#e63946",
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

def _safe_workspace_file(workspace_dir: Path, user_path: str) -> Optional[Path]:
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
            if img_path is not None and img_path.exists():
                if img_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    data = base64.b64encode(img_path.read_bytes()).decode("ascii")
                    mime = _image_mime(img_path)
                    return (
                        '<div class="chart-container">'
                        f'<img data-source="{escape(img_path.name, quote=True)}" '
                        f'src="data:{mime};base64,{data}" alt="{escape(alt, quote=True)}">'
                        f'<p class="chart-caption">{escape(alt, quote=True)}</p></div>'
                    )
        return f'<p><em>Image not found: {escape(url, quote=True)}</em></p>'


def md_to_html(md_text: str, workspace_dir=None) -> str:
    """Convert InvestPilot step markdown to structured HTML via mistune.

    Uses a custom renderer that offsets headings, base64-embeds local images,
    and preserves all standard markdown features (tables, code blocks, links,
    nested lists, blockquotes) handled correctly by the mistune engine.
    """
    renderer = _ResearchReportRenderer(workspace_dir)
    markdown = mistune.create_markdown(renderer=renderer, plugins=["table", "strikethrough", "task_lists", "speedup"])
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
        return json.loads(p.read_text(encoding='utf-8'))
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

    # p50_target — Schema A has it at top level; B/D have target_price_percentiles.50; C has target_price.50
    if mc.get("p50_target") is not None:
        result["p50_target"] = mc["p50_target"]
    elif isinstance(mc.get("target_price_percentiles"), dict):
        tp = mc["target_price_percentiles"]
        result["target_price_percentiles"] = tp
        if tp.get("50") is not None:
            result["p50_target"] = tp["50"]
    elif isinstance(mc.get("target_price"), dict):
        tp = mc["target_price"]
        result["target_price_percentiles"] = tp
        if tp.get("50") is not None:
            result["p50_target"] = tp["50"]

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
    if mc.get('current_price'):
        return str(mc['current_price'])
    if cv and isinstance(cv, dict):
        if 'price_hkd' in cv:
            return str(cv['price_hkd'])
        if isinstance(cv.get('pe_trailing'), dict) and cv['pe_trailing'].get('price'):
            return str(cv['pe_trailing']['price'])
    vcp = _read_json_safe(ws, 'valuation_current_price.json')
    if vcp is not None and isinstance(vcp, (int, float)):
        return str(vcp)
    s4 = read_model_text()
    for pattern in (
        r'当前价[格：:]*\s*[~～]?HKD\s*([\d.]+)',
        r'当前股价[：:]\s*[~～]?([\d.]+)',
        r'当前价格[：:]\s*[~～]?([\d.]+)',
        r'\|\s*当前价[^|]*\|\s*([\d.]+)',
        r'当前价[^(|\n]*?([\d]+\.[\d]+)',
    ):
        m = re.search(pattern, s4)
        if m:
            return m.group(1)
    return None


def _extract_target_price(ws: Path, mc: dict, sa: dict | None, read_model_text) -> str | None:
    """Extract P50 target_price from JSON artifacts or markdown."""
    if mc.get('p50_target') is not None:
        tp = mc['p50_target']
        return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    if sa and isinstance(sa, dict):
        fmi = sa.get('financial_model_inputs', {})
        if fmi.get('p50_target_hkd') is not None:
            tp = fmi['p50_target_hkd']
            return f"{tp:.2f}" if isinstance(tp, float) else str(tp)
        if fmi.get('p50_eps_cny') is not None:
            eps = fmi.get('p50_eps_cny', 0)
            fx = fmi.get('hkd_cny', 1.0)
            _am = sa.get('assumption_matrix', {})
            if not isinstance(_am, dict):
                _am = {}
            for period_key in ('T1_FY2026E', 'T1', 'FY1'):
                period = _am.get(period_key, {})
                pe_dist = period.get('pe_multiple', period.get('pe', {}))
                if isinstance(pe_dist, dict):
                    p50_pe = pe_dist.get('p50', pe_dist.get('50'))
                    if p50_pe and eps and fx:
                        return f"{eps * p50_pe / fx:.2f}"
    # Regex fallback
    s4 = read_model_text()
    target_keywords = ("目标价", "target price", "target_price", "p50 target", "p50目标价")
    labeled_candidates = []
    for line in s4.splitlines():
        low = line.lower()
        if "p50" not in low:
            continue
        if not any(kw in low for kw in target_keywords):
            continue
        nums = re.findall(r'(?<![-\d.])(\d+(?:\.\d+)?)(?![%\d.])', line)
        for num in nums:
            try:
                if float(num) >= 10.0:
                    labeled_candidates.append(num)
            except ValueError:
                continue
    header_tp = None
    m = re.search(r'P50\s*目标价[：:]*\s*[~～]?([\d.]+)', s4)
    if m and float(m.group(1)) >= 1.0:
        header_tp = m.group(1)
    compute_tp = None
    m = re.search(r'[Tt]arget\s*=\s*[\d.]+\s*[*×/]\s*[\d.]+\s*/\s*[\d.]+\s*=\s*([\d.]+)\s*HKD', s4)
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
        r'(?:P50\s*)?(?:目标价|target price)[：:\s|]*\*{0,2}([\d.]+)\*{0,2}',
        s4, re.IGNORECASE,
    )
    return m.group(1) if m else None


def _extract_forward_pe(ws: Path, peb: dict | None, cv: dict | None, read_model_text) -> str | None:
    """Extract forward PE from JSON artifacts or markdown."""
    if peb and isinstance(peb, dict) and 'current_forward_pe' in peb:
        return f"{peb['current_forward_pe']:.1f}x"
    if cv and isinstance(cv, dict):
        for key in ('pe_forward', 'pe_forward_t2_ngaap', 'pe_forward_t1_ngaap',
                    'pe_forward_t2', 'pe_forward_t1', 'pe_ttm_ngaap', 'pe_ttm'):
            if key in cv and cv[key]:
                v = cv[key]
                if isinstance(v, dict):
                    pe_value = v.get('pe', v.get('value'))
                    if pe_value is not None:
                        return f"{pe_value:.1f}x" if isinstance(pe_value, (int, float)) else str(pe_value) + 'x'
                elif isinstance(v, (int, float)):
                    return f"{v:.1f}x"
                else:
                    return str(v) + 'x'
    s4 = read_model_text()
    for pattern in (
        r'当前\s*Forward\s*PE[：:]*\s*([\d.]+)x',
        r'P50\s*Forward\s*PE[^*]*?\*{0,2}([\d.]+)x',
        r'Forward\s*PE\s*\|[^|]*?([\d.]+)x',
        r'PE\(Forward[^)]*\)[^(]*?([\d.]+)x',
        r'Forward PE[^(]*?([\d.]+)x',
    ):
        m = re.search(pattern, s4)
        if m:
            return m.group(1) + 'x'
    return None


def _extract_rrr(mc: dict, read_file) -> str | None:
    """Extract RRR from JSON or Step 7 markdown."""
    if mc.get('rrr') is not None:
        rrr_val = mc['rrr']
        return f"{rrr_val:.2f}" if isinstance(rrr_val, float) else str(rrr_val)
    s5 = read_file('step7_rrr_strategy.md')
    for pattern in (
        r'\*\*RRR[^*]*\*\*\s*\|?\s*\*{0,2}([\d.]+)\*{0,2}',
        r'RRR\s*[=：:]\s*\*{0,2}([\d.]+)\*{0,2}',
        r'RRR\s*\([^)]*\)\s*[=：:]?\s*([\d.]+)',
        r'RRR.{0,30}?([\d]+\.[\d]+)',
    ):
        m = re.search(pattern, s5)
        if m:
            return m.group(1)
    return None


def _extract_moat(ws: Path, read_file) -> str | None:
    """Extract moat classification from Step 2 markdown."""
    s2 = read_file('step2_competitive_moat.md')
    m = re.search(r'(Wide|Narrow|None)\s*(?:Moat)?\s*,?\s*(Widening|Stable|Narrowing)', s2, re.IGNORECASE)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    if re.search(r'Narrow', s2):
        return 'Narrow'
    return None


def _extract_edge_score(ws: Path, thesis: dict | None) -> tuple[str | None, str | None]:
    """Extract edge_score and edge_grade from JSON artifacts."""
    ej = ws / 'edge_score.json'
    if ej.exists():
        try:
            data = json.loads(ej.read_text(encoding='utf-8'))
            if isinstance(data, list):
                data = data[-1]
            return str(data.get('composite', data.get('edge_score', ''))), data.get('composite_grade', data.get('grade', ''))
        except Exception:
            pass
    if thesis and isinstance(thesis, dict):
        t = thesis
        if 'history' in t and isinstance(t['history'], list) and t['history']:
            latest = t['history'][-1]
            if 'edge_score' in latest:
                return str(latest['edge_score']), latest.get('edge_grade', '')
        if 'edge_score' in t:
            return str(t['edge_score']), t.get('edge_grade', '')
    return None, None


def _extract_decision(ws: Path, read_file) -> str | None:
    """Extract decision from Step 9 markdown."""
    s7 = read_file('step9_research_director_review.md')
    m = re.search(r'\b(Buy|Hold|Pass)\b', s7)
    return m.group(1) if m else None


def _sanity_check_metrics(metrics: dict, ws: Path, sa: dict | None, read_file):
    """Validate extracted metrics and attempt recovery if ratios look wrong."""
    current_price = float(metrics.get('current_price', 0)) if metrics.get('current_price') else 0
    target_price = float(metrics.get('target_price', 0)) if metrics.get('target_price') else 0
    if current_price > 0 and target_price > 0:
        ratio = target_price / current_price
        if ratio < 0.3 or ratio > 5.0:
            logger.warning(
                "Extracted target_price=%s vs current_price=%s (ratio=%.2f) looks unreasonable. "
                "Attempting structured JSON recovery.",
                target_price, current_price, ratio,
            )
            if sa and isinstance(sa, dict):
                fmi_rec = sa.get('financial_model_inputs', {})
                recovered = fmi_rec.get('p50_target_hkd')
                if recovered is not None:
                    metrics['target_price'] = f"{recovered:.2f}" if isinstance(recovered, float) else str(recovered)
                    logger.info("Recovered target_price=%s from step4_structured_assumptions.json", metrics['target_price'])
            if float(metrics.get('target_price', 0)) / current_price < 0.3:
                s5 = read_file('step7_rrr_strategy.md')
                m5 = re.search(r'P50\s+Target\s*\|\s*([\d.]+)\s*HKD', s5)
                if m5 and float(m5.group(1)) >= current_price * 0.3:
                    metrics['target_price'] = m5.group(1)


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
        return p.read_text(encoding='utf-8') if p.exists() else ''

    def _read_model_text():
        chunks = [
            _read_file(name)
            for name in (
                'step4_assumption_research.md',
                'step5_financial_model.md',
                'step6_monte_carlo_simulation.md',
            )
        ]
        return '\n\n'.join(chunk for chunk in chunks if chunk)

    # ── Load all available JSON artifacts ──────────────────────────────────
    for summary_name in ('summary_metrics.json', 'report_metrics.json'):
        summary = _read_json_safe(ws, summary_name)
        if isinstance(summary, dict):
            for key, value in summary.items():
                if value is not None:
                    metrics[key] = str(value)
            break

    mc_raw = _read_json_safe(ws, 'monte_carlo_results.json')
    if mc_raw is None:
        mc_raw = _read_json_safe(ws, 'monte_carlo_result.json')
    mc = _normalize_mc_json(mc_raw) if isinstance(mc_raw, dict) else {}
    cv = _read_json_safe(ws, 'calculated_valuation.json')
    peb = _read_json_safe(ws, 'pe_band_data.json')
    thesis = _read_json_safe(ws, 'thesis.json')
    sa = _read_json_safe(ws, 'step4_structured_assumptions.json')

    # ── Extract each metric ────────────────────────────────────────────────
    if 'current_price' not in metrics:
        cp = _extract_current_price(ws, mc, cv, _read_model_text)
        if cp:
            metrics['current_price'] = cp

    if 'target_price' not in metrics:
        tp = _extract_target_price(ws, mc, sa, _read_model_text)
        if tp:
            metrics['target_price'] = tp

    if 'forward_pe' not in metrics:
        fpe = _extract_forward_pe(ws, peb, cv, _read_model_text)
        if fpe:
            metrics['forward_pe'] = fpe

    if 'rrr' not in metrics:
        rrr = _extract_rrr(mc, _read_file)
        if rrr:
            metrics['rrr'] = rrr

    moat = _extract_moat(ws, _read_file)
    if moat:
        metrics['moat'] = moat

    es, eg = _extract_edge_score(ws, thesis)
    if es:
        metrics['edge_score'] = es
    if eg:
        metrics['edge_grade'] = eg

    decision = _extract_decision(ws, _read_file)
    if decision:
        metrics['decision'] = decision

    _sanity_check_metrics(metrics, ws, sa, _read_file)

    return metrics


# ---------------------------------------------------------------------------
# Auto-embed workspace images (prevents missing charts)
# ---------------------------------------------------------------------------

# Mapping of known PNG filenames to step keys for targeted embedding
_IMAGE_STEP_MAP = {
    'monte_carlo_distribution.png': 'step6',
    'monte_carlo_distribution_corrected.png': 'step6',
    'monte_carlo_distribution_v3.png': 'step6',
    'forward_pe_band.png': 'step6',
    'eps_distribution.png': 'step6',
    'eps_pe_scatter.png': 'step6',
    'revenue_driver_bridge.png': 'step4',
    'target_price_distribution.png': 'step6',
}


def _embed_image_as_base64(img_path: Path, alt_text: str = "") -> str:
    """Embed a single image file as base64 into an HTML chart container."""
    if not img_path.exists():
        return ''
    data = base64.b64encode(img_path.read_bytes()).decode('ascii')
    caption = escape(alt_text or img_path.stem.replace('_', ' ').title(), quote=True)
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

    # Detect already-embedded images by filename
    already_embedded = {
        png.name for png in png_files
        if png.stem in sections_html or png.name in sections_html
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
# Main HTML report generator
# ---------------------------------------------------------------------------

def generate_report_html(
    workspace_dir,
    ticker: str,
    company_name: str = "",
    summary_overrides: dict = None,
) -> 'Path':
    """Generate a self-contained HTML research report.

    Args:
        workspace_dir: Path to workspace directory (string or Path).
        ticker: Stock ticker (e.g., "09992.HK").
        company_name: Display name. If empty, extracted from step1 title.
        summary_overrides: Optional dict to override auto-extracted metrics.

    Returns:
        Path to the generated HTML file.
    """
    from pathlib import Path
    from datetime import datetime
    from src.report._html_templates import REPORT_CSS, REPORT_JS, HTML_SKELETON, STEP_CONFIG

    ws = Path(workspace_dir)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Read step files ---
    steps = []
    for cfg in STEP_CONFIG:
        fpath = ws / cfg['file']
        if fpath.exists():
            md = fpath.read_text(encoding='utf-8')
            # Extract company name from step1 title if not provided
            if cfg['key'] == 'step1' and not company_name:
                m = re.match(r'#\s*Step\s*1:\s*(.+?)(?:\s*\(|$)', md, re.MULTILINE)
                if m:
                    company_name = m.group(1).strip()
            steps.append({**cfg, 'content': md})
        else:
            if not cfg.get('optional'):
                logger.warning("%s not found, skipping", cfg['file'])
            steps.append({**cfg, 'content': ''})

    # --- Extract summary metrics ---
    metrics = _extract_summary_metrics(ws, ticker)
    if summary_overrides:
        metrics.update(summary_overrides)

    # --- Determine currency from ticker ---
    currency = 'CNY'  # default
    if '.HK' in ticker.upper():
        currency = 'HKD'
    elif ticker.replace('.', '').replace('S', '').replace('Z', '').isdigit() and len(ticker.split('.')[0]) <= 6:
        pass  # A-share, CNY
    else:
        # Check for US stocks (no suffix or .US)
        if not ticker[0].isdigit():
            currency = 'USD'

    # --- Build summary cards ---
    card_defs = [
        ('current_price', 'Current Price', currency, 'blue'),
        ('target_price', 'P50 Target', currency, 'green'),
        ('rrr', 'RRR', '', 'green'),
        ('forward_pe', 'Forward PE', '', 'blue'),
        ('moat', 'Moat', '', 'amber'),
        ('edge_score', 'Edge Score', '', 'amber'),
    ]
    summary_cards = []
    for key, label, unit, color in card_defs:
        val = metrics.get(key)
        if val:
            sub = f" / {metrics['edge_grade']}" if key == 'edge_score' and metrics.get('edge_grade') else unit
            summary_cards.append(
                f'<div class="summary-card {color}">'
                f'<div class="label">{escape(label, quote=True)}</div>'
                f'<div class="value">{escape(str(val), quote=True)}</div>'
                f'<div class="sub">{escape(str(sub), quote=True)}</div></div>'
            )
    summary_html = f'<div class="summary-grid">{"".join(summary_cards)}</div>' if summary_cards else ''

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
                    inner = inner[h1_start + len("<h1>"):]
                    h1_end = inner.find("</h1>")
                    if h1_end != -1:
                        inner = inner[h1_end + len("</h1>"):]
                model_html_body = inner.strip()
            model_link_html = (
                '<p><strong>Standalone model:</strong> '
                f'{escape(forecast_model_html.name, quote=True)}</p>'
            )
        except Exception as e:
            model_html_body = (
                '<p><em>Error reading forecast model: '
                f'{escape(str(e), quote=True)}</em></p>'
            )
    if model_html_body:
        toc_items.append('<li><a href="#forecast-model"><i class="fas fa-table"></i> Forecast Model</a></li>')
    toc_html = f'<div class="toc"><h2>Table of Contents</h2><ul class="toc-list">{"".join(toc_items)}</ul></div>'

    # --- Build sidebar ---
    sidebar_items = []
    for cfg in STEP_CONFIG:
        sidebar_items.append(
            f'<a href="#{cfg["key"]}"><i class="{cfg["icon"]}"></i> {cfg["title"]}</a>'
        )
    if model_html_body:
        sidebar_items.append('<a href="#forecast-model"><i class="fas fa-table"></i> Forecast Model</a>')
    sidebar_html = (
        '<div class="sidebar"><div class="nav-section">'
        f'<h3>Navigation</h3>{"".join(sidebar_items)}'
        '</div></div>'
    )

    # --- Build sections ---
    sections_html = ''
    for step in steps:
        if not step['content']:
            continue
        body_html = md_to_html(step['content'], ws)
        sections_html += (
            f'<div id="{step["key"]}" class="section-card">'
            f'<div class="section-header" onclick="toggleSection(this)">'
            f'<h2><i class="{step["icon"]}"></i> {step["title"]}</h2>'
            f'<span class="toggle"><i class="fas fa-chevron-down"></i></span></div>'
            f'<div class="section-body">{body_html}'
            f'<!-- AUTO_IMAGES:{step["key"]} --></div></div>'
        )

    # --- Auto-generate Monte Carlo distribution chart from structured assumptions ---
    sa_path = ws / "step4_structured_assumptions.json"
    if sa_path.exists():
        try:
            sa = json.loads(sa_path.read_text(encoding='utf-8'))
            _am_raw = sa.get("assumption_matrix", {})
            _am = _am_raw if isinstance(_am_raw, dict) else {}
            am = _am.get("T1_FY2026E", {})
            fmi = sa.get("financial_model_inputs", {})

            rg = am.get("revenue_growth", {})
            npm = am.get("npm") or am.get("net_profit_margin") or {}
            pe = am.get("pe_fwd_t1") or am.get("pe_multiple") or am.get("pe") or {}

            # JSON keys may be strings ("10") or ints (10) — normalize
            def _pct_get(d, pct):
                if not isinstance(d, dict):
                    return None
                return d.get(f"p{pct}", d.get(str(pct), d.get(pct)))

            def _ratio_value(d, pct):
                value = _pct_get(d, pct)
                if value is None:
                    return None
                value = float(value)
                return value / 100.0 if abs(value) > 1.0 else value

            def _number_value(d, pct):
                value = _pct_get(d, pct)
                return None if value is None else float(value)

            required_pcts = [10, 30, 50, 70, 90]
            has_all = all(
                _ratio_value(rg, p) is not None
                and _ratio_value(npm, p) is not None
                and _number_value(pe, p) is not None
                for p in required_pcts
            )

            if rg and npm and pe and has_all:
                base_rev = sa.get("base_revenue_cny_m", 0)
                shares = fmi.get("shares_outstanding", 1)
                fx = fmi.get("hkd_cny", 1.0)

                if base_rev and shares and fx and float(shares) > 0 and float(fx) > 0:
                    price_pcts = {}
                    for pct in required_pcts:
                        rev = float(base_rev) * (1 + _ratio_value(rg, pct))
                        ni = rev * _ratio_value(npm, pct)
                        eps = ni * 1e4 / float(shares)  # rev in 万元 → CNY
                        target = eps * _number_value(pe, pct) / float(fx)  # HKD
                        price_pcts[pct] = target

                    mc_png = ws / "monte_carlo_distribution.png"
                    cur_price = sa.get("current_price_hkd")
                    generate_distribution_from_percentiles(
                        p10=price_pcts[10],
                        p30=price_pcts[30],
                        p50=price_pcts[50],
                        p70=price_pcts[70],
                        p90=price_pcts[90],
                        title=f"{ticker} Monte Carlo Target Price Distribution (50K runs)",
                        current_price=cur_price,
                        save_path=mc_png,
                        currency=currency,
                    )
                    if mc_png.exists():
                        print(f"  ✓ Monte Carlo distribution chart generated: {mc_png}")
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
        f' | Current: <strong>{escape(str(metrics.get("current_price")), quote=True)}</strong>'
        if metrics.get('current_price') else ''
    )
    decision_part = escape(str(metrics.get('decision', 'N/A')), quote=True)
    header_html = (
        f'<div class="sticky-header">'
        f'<div class="logo">Invest<span>Pilot</span> | {display_name_html} ({ticker_html})</div>'
        f'<div class="meta">Report Date: <strong>{date_str}</strong>{price_part}'
        f' | Decision: <strong>{decision_part}</strong></div></div>'
    )

    # --- Footer ---
    footer_text = (
        '<div class="footer">'
        '<p><strong>Disclaimer</strong></p>'
        '<p>This report is generated by InvestPilot AI Research for informational purposes only. '
        'It does not constitute investment advice. Past performance does not guarantee future results.</p>'
        f'<p style="margin-top:12px;color:rgba(255,255,255,0.4)">InvestPilot Deep Fundamental Research Harness | {date_str}</p>'
        '</div>'
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
    output_path.write_text(html, encoding='utf-8')
    return output_path
