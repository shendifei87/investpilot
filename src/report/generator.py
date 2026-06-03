import re
import json
import base64
from html import escape
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional


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

def _convert_inline(text: str) -> str:
    """Convert inline markdown: **bold** -> <strong>, `code` -> <code>."""
    text = escape(str(text), quote=True)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text


def _convert_table(lines: list) -> str:
    """Convert pipe-delimited markdown table to HTML table."""
    if len(lines) < 2:
        return ''
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)
    # Remove separator rows (|:---|:---|)
    data_rows = [r for r in rows if not all(re.match(r'^:?-+:?$', c.strip()) for c in r)]
    if not data_rows:
        return ''
    header = ''.join(f'<th>{_convert_inline(c)}</th>' for c in data_rows[0])
    html = f'<thead><tr>{header}</tr></thead>'
    body = ''
    for row in data_rows[1:]:
        cells = ''.join(f'<td>{_convert_inline(c)}</td>' for c in row)
        body += f'<tr>{cells}</tr>'
    html += f'<tbody>{body}</tbody>'
    return f'<table>{html}</table>'


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


def _convert_image(line: str, workspace_dir) -> str:
    """Convert ![alt](file.png) to base64-embedded <img>."""
    m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
    if not m:
        return f'<p>{_convert_inline(line.strip())}</p>'
    alt, src = m.group(1), m.group(2)
    if workspace_dir:
        img_path = _safe_workspace_file(workspace_dir, src)
        if img_path is not None and img_path.exists():
            if img_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                return f'<p><em>Image not found: {escape(src, quote=True)}</em></p>'
            data = base64.b64encode(img_path.read_bytes()).decode('ascii')
            alt_html = escape(alt, quote=True)
            source_html = escape(img_path.name, quote=True)
            mime = _image_mime(img_path)
            return (f'<div class="chart-container">'
                    f'<img data-source="{source_html}" src="data:{mime};base64,{data}" alt="{alt_html}">'
                    f'<p class="chart-caption">{alt_html}</p></div>')
    return f'<p><em>Image not found: {escape(src, quote=True)}</em></p>'


def md_to_html(md_text: str, workspace_dir=None) -> str:
    """Convert InvestPilot step markdown to structured HTML.

    Handles: tables, h2-h4, bold, unordered/ordered lists,
    blockquotes, horizontal rules, inline images (base64).
    """
    from pathlib import Path
    ws = Path(workspace_dir) if workspace_dir else None
    lines = md_text.split('\n')
    html_parts = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Skip the top-level # heading (step title, already in section header)
        if stripped.startswith('# ') and not stripped.startswith('## '):
            i += 1
            continue

        # Headings: ##### -> h6, #### -> h5, ### -> h4, ## -> h3
        # Check longest match first to avoid ##### being caught by ####
        if stripped.startswith('#####'):
            html_parts.append(f'<h6>{_convert_inline(stripped[5:].strip())}</h6>')
            i += 1
        elif stripped.startswith('####'):
            html_parts.append(f'<h5>{_convert_inline(stripped[4:].strip())}</h5>')
            i += 1
        elif stripped.startswith('###'):
            html_parts.append(f'<h4>{_convert_inline(stripped[3:].strip())}</h4>')
            i += 1
        elif stripped.startswith('##'):
            html_parts.append(f'<h3>{_convert_inline(stripped[2:].strip())}</h3>')
            i += 1
        elif stripped == '---':
            html_parts.append('<hr>')
            i += 1
        elif stripped.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            html_parts.append(_convert_table(table_lines))
        elif stripped.startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip().lstrip('>').strip())
                i += 1
            quote_text = '<br>'.join(_convert_inline(l) for l in quote_lines if l)
            html_parts.append(f'<blockquote>{quote_text}</blockquote>')
        elif stripped.startswith('- ') or stripped.startswith('* '):
            items = []
            prefix = '- ' if stripped.startswith('- ') else '* '
            while i < len(lines) and (lines[i].strip().startswith('- ') or lines[i].strip().startswith('* ')):
                pfx = '- ' if lines[i].strip().startswith('- ') else '* '
                items.append(_convert_inline(lines[i].strip()[len(pfx):]))
                i += 1
            html_parts.append('<ul>' + ''.join(f'<li>{it}</li>' for it in items) + '</ul>')
        elif re.match(r'^\d+\.\s', stripped):
            items = []
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i].strip()):
                text = re.sub(r'^\d+\.\s', '', lines[i].strip())
                items.append(_convert_inline(text))
                i += 1
            html_parts.append('<ol>' + ''.join(f'<li>{it}</li>' for it in items) + '</ol>')
        elif re.match(r'!\[.*\]\(', stripped):
            html_parts.append(_convert_image(stripped, ws))
            i += 1
        else:
            html_parts.append(f'<p>{_convert_inline(stripped)}</p>')
            i += 1

    return '\n'.join(html_parts)


# ---------------------------------------------------------------------------
# Summary metrics extraction — JSON-first with markdown regex fallback
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


def _extract_summary_metrics(workspace_dir, ticker: str) -> dict:
    """Extract key metrics from workspace JSON artifacts first, then regex fallback.

    Priority order for each metric:
      1. Structured JSON files (monte_carlo_results.json, pe_band_data.json, etc.)
      2. Markdown regex parsing of step files (backward compatibility)

    Supported JSON schemas (multi-workspace compatibility):
      monte_carlo_results.json (Schema A): p50_target, current_price, rrr, kelly_*
      monte_carlo_results.json (Schema B): target_price_percentiles.50
      monte_carlo_results.json (Schema C): target_price.50, rrr, kelly_half_pct
      monte_carlo_result.json  (Schema D): rrr.rrr, rrr.kelly_half (singular filename)
    """
    ws = Path(workspace_dir)
    metrics = {}

    def _read_file(name):
        p = ws / name
        return p.read_text(encoding='utf-8') if p.exists() else ''

    def _normalize_summary_value(value):
        if value is None:
            return None
        return str(value)

    # ── Load all available JSON artifacts ──────────────────────────────────
    for summary_name in ('summary_metrics.json', 'report_metrics.json'):
        summary = _read_json_safe(ws, summary_name)
        if isinstance(summary, dict):
            for key, value in summary.items():
                normalized = _normalize_summary_value(value)
                if normalized not in (None, ''):
                    metrics[key] = normalized
            break

    mc = _read_json_safe(ws, 'monte_carlo_results.json')
    if mc is None:
        mc = _read_json_safe(ws, 'monte_carlo_result.json')  # singular variant
    cv = _read_json_safe(ws, 'calculated_valuation.json')
    peb = _read_json_safe(ws, 'pe_band_data.json')
    thesis = _read_json_safe(ws, 'thesis.json')

    # ── current_price ──────────────────────────────────────────────────────
    # Priority 1: monte_carlo JSON (Schema A/D have current_price at top level)
    if 'current_price' not in metrics and mc and isinstance(mc, dict) and mc.get('current_price'):
        metrics['current_price'] = str(mc['current_price'])
    # Priority 2: calculated_valuation.json
    elif 'current_price' not in metrics and cv and isinstance(cv, dict):
        if 'price_hkd' in cv:
            metrics['current_price'] = str(cv['price_hkd'])
        elif isinstance(cv.get('pe_trailing'), dict) and cv['pe_trailing'].get('price'):
            metrics['current_price'] = str(cv['pe_trailing']['price'])
    # Priority 3: valuation_current_price.json (scalar file)
    if 'current_price' not in metrics:
        vcp = _read_json_safe(ws, 'valuation_current_price.json')
        if vcp is not None and isinstance(vcp, (int, float)):
            metrics['current_price'] = str(vcp)
    # Fallback: regex from step4 markdown
    if 'current_price' not in metrics:
        s4 = _read_file('step4_quantitative_model.md')
        for pattern in (
            r'当前价[格：:]*\s*[~～]?HKD\s*([\d.]+)',
            r'当前股价[：:]\s*[~～]?([\d.]+)',
            r'当前价格[：:]\s*[~～]?([\d.]+)',
            r'\|\s*当前价[^|]*\|\s*([\d.]+)',
            r'当前价[^(|\n]*?([\d]+\.[\d]+)',
        ):
            m = re.search(pattern, s4)
            if m:
                metrics['current_price'] = m.group(1)
                break

    # ── target_price (P50 target) ──────────────────────────────────────────
    if 'target_price' not in metrics and mc and isinstance(mc, dict):
        tp = None
        # Schema A: p50_target (top-level)
        if 'p50_target' in mc and mc['p50_target'] is not None:
            tp = mc['p50_target']
        # Schema B/D: target_price_percentiles.50
        elif isinstance(mc.get('target_price_percentiles'), dict):
            tp = mc['target_price_percentiles'].get('50')
        # Schema C: target_price.50
        elif isinstance(mc.get('target_price'), dict):
            tp = mc['target_price'].get('50')
        if tp is not None:
            metrics['target_price'] = f"{tp:.2f}" if isinstance(tp, float) else str(tp)
    # Fallback: multi-strategy regex from step4 markdown
    if 'target_price' not in metrics:
        s4 = _read_file('step4_quantitative_model.md')

        target_keywords = ("目标价", "target price", "target_price", "p50 target", "p50目标价")
        labeled_candidates = []
        for line in s4.splitlines():
            low = line.lower()
            if "p50" not in low:
                continue
            if not any(kw in low for kw in target_keywords):
                continue
            nums = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])', line)
            for num in nums:
                try:
                    if float(num) >= 1.0:
                        labeled_candidates.append(num)
                except ValueError:
                    continue

        # Strategy 2: Header summary "P50 目标价: 8.34"
        header_tp = None
        m = re.search(r'P50\s*目标价[：:]*\s*[~～]?([\d.]+)', s4)
        if m and float(m.group(1)) >= 1.0:
            header_tp = m.group(1)

        if labeled_candidates:
            metrics['target_price'] = labeled_candidates[-1]
            metrics['forward_year'] = 'T+2'
        elif header_tp:
            metrics['target_price'] = header_tp
        else:
            m = re.search(
                r'(?:P50\s*)?(?:目标价|target price)[：:\s|]*\*{0,2}([\d.]+)\*{0,2}',
                s4,
                re.IGNORECASE,
            )
            if m:
                metrics['target_price'] = m.group(1)

    # ── forward_pe ─────────────────────────────────────────────────────────
    # Priority 1: pe_band_data.json (most accurate for "current forward PE")
    if 'forward_pe' not in metrics and peb and isinstance(peb, dict) and 'current_forward_pe' in peb:
        metrics['forward_pe'] = f"{peb['current_forward_pe']:.1f}x"
    # Priority 2: calculated_valuation.json forward PE keys
    if 'forward_pe' not in metrics and cv and isinstance(cv, dict):
        for key in ('pe_forward', 'pe_forward_t2_ngaap', 'pe_forward_t1_ngaap',
                    'pe_forward_t2', 'pe_forward_t1', 'pe_ttm_ngaap', 'pe_ttm'):
            if key in cv and cv[key]:
                v = cv[key]
                if isinstance(v, dict):
                    pe_value = v.get('pe', v.get('value'))
                    if pe_value is not None:
                        metrics['forward_pe'] = f"{pe_value:.1f}x" if isinstance(pe_value, (int, float)) else str(pe_value) + 'x'
                elif isinstance(v, (int, float)):
                    metrics['forward_pe'] = f"{v:.1f}x"
                else:
                    metrics['forward_pe'] = str(v) + 'x'
                if 'forward_pe' in metrics:
                    break
    # Fallback: regex from step4 markdown
    if 'forward_pe' not in metrics:
        s4 = _read_file('step4_quantitative_model.md')
        for pattern in (
            r'当前\s*Forward\s*PE[：:]*\s*([\d.]+)x',
            r'P50\s*Forward\s*PE[^*]*?\*{0,2}([\d.]+)x',
            r'Forward\s*PE\s*\|[^|]*?([\d.]+)x',
            r'PE\(Forward[^)]*\)[^(]*?([\d.]+)x',
            r'Forward PE[^(]*?([\d.]+)x',
        ):
            m = re.search(pattern, s4)
            if m:
                metrics['forward_pe'] = m.group(1) + 'x'
                break

    # ── rrr ────────────────────────────────────────────────────────────────
    # Priority 1: monte_carlo JSON
    if 'rrr' not in metrics and mc and isinstance(mc, dict):
        rrr_val = None
        # Schema A: top-level rrr
        if isinstance(mc.get('rrr'), (int, float)):
            rrr_val = mc['rrr']
        # Schema D: rrr.rrr
        elif isinstance(mc.get('rrr'), dict):
            rrr_val = mc['rrr'].get('rrr')
        if rrr_val is not None:
            metrics['rrr'] = f"{rrr_val:.2f}" if isinstance(rrr_val, float) else str(rrr_val)
    # Fallback: regex from step5 markdown
    if 'rrr' not in metrics:
        s5 = _read_file('step5_rrr_strategy.md')
        for pattern in (
            r'\*\*RRR[^*]*\*\*\s*\|?\s*\*{0,2}([\d.]+)\*{0,2}',
            r'RRR\s*[=：:]\s*\*{0,2}([\d.]+)\*{0,2}',
            r'RRR\s*\([^)]*\)\s*[=：:]?\s*([\d.]+)',
            r'RRR.{0,30}?([\d]+\.[\d]+)',
        ):
            m = re.search(pattern, s5)
            if m:
                metrics['rrr'] = m.group(1)
                break

    # ── moat (no JSON alternative — regex only) ────────────────────────────
    s2 = _read_file('step2_competitive_moat.md')
    m = re.search(r'(Wide|Narrow|None)\s*(?:Moat)?\s*,?\s*(Widening|Stable|Narrowing)', s2, re.IGNORECASE)
    if m:
        metrics['moat'] = f"{m.group(1)} {m.group(2)}"
    elif re.search(r'Narrow', s2):
        metrics['moat'] = 'Narrow'

    # ── edge_score ─────────────────────────────────────────────────────────
    # Priority 1: edge_score.json (handles both list and dict schemas)
    ej = ws / 'edge_score.json'
    if ej.exists():
        try:
            data = json.loads(ej.read_text(encoding='utf-8'))
            if isinstance(data, list):
                data = data[-1]
            metrics['edge_score'] = str(data.get('composite', data.get('edge_score', '')))
            metrics['edge_grade'] = data.get('composite_grade', data.get('grade', ''))
        except Exception:
            pass
    # Priority 2: thesis.json (fallback)
    if 'edge_score' not in metrics and thesis and isinstance(thesis, dict):
        t = thesis
        if 'history' in t and isinstance(t['history'], list) and t['history']:
            latest = t['history'][-1]
            if 'edge_score' in latest:
                metrics['edge_score'] = str(latest['edge_score'])
                metrics['edge_grade'] = latest.get('edge_grade', '')
        elif 'edge_score' in t:
            metrics['edge_score'] = str(t['edge_score'])
            metrics['edge_grade'] = t.get('edge_grade', '')

    # ── decision (no JSON alternative — regex only) ────────────────────────
    s7 = _read_file('step7_research_director_review.md')
    m = re.search(r'\b(Buy|Hold|Pass)\b', s7)
    if m:
        metrics['decision'] = m.group(1)

    # ── Sanity checks on extracted metrics ─────────────────────────────────
    current_price = float(metrics.get('current_price', 0)) if metrics.get('current_price') else 0
    target_price = float(metrics.get('target_price', 0)) if metrics.get('target_price') else 0
    if current_price > 0 and target_price > 0:
        ratio = target_price / current_price
        if ratio < 0.1 or ratio > 5.0:
            import warnings
            warnings.warn(
                f"Extracted target_price={target_price} vs current_price={current_price} "
                f"(ratio={ratio:.2f}) looks unreasonable. Likely extraction error. "
                f"Check step4_quantitative_model.md table formatting."
            )

    return metrics


# ---------------------------------------------------------------------------
# Auto-embed workspace images (prevents missing charts)
# ---------------------------------------------------------------------------

# Mapping of known PNG filenames to step keys for targeted embedding
_IMAGE_STEP_MAP = {
    'monte_carlo_distribution.png': 'step4',
    'monte_carlo_distribution_corrected.png': 'step4',
    'monte_carlo_distribution_v3.png': 'step4',
    'forward_pe_band.png': 'step4',
    'eps_distribution.png': 'step4',
    'eps_pe_scatter.png': 'step4',
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
    """Scan workspace for PNG files not already embedded, and inject them.

    1. Find all *.png in workspace (top-level only)
    2. Check which are already embedded (filename stem or name in HTML)
    3. For each un-embedded PNG: append to matched step or to appendix section
    """
    png_files = sorted(ws.glob('*.png'))
    if not png_files:
        return sections_html

    # Detect which PNGs are already embedded by checking if filename
    # appears in the HTML (via alt text, chart-caption, or direct reference)
    already_embedded = set()
    for png in png_files:
        if png.stem in sections_html or png.name in sections_html:
            already_embedded.add(png.name)

    # Group un-embedded PNGs by target step
    step_injections = {}   # step_key -> [(png_path, alt_text)]
    appendix_images = []   # PNGs with no step mapping

    for png in png_files:
        if png.name in already_embedded:
            continue
        target_step = _IMAGE_STEP_MAP.get(png.name)
        if target_step:
            step_injections.setdefault(target_step, []).append(
                (png, png.stem.replace('_', ' ').title())
            )
        else:
            appendix_images.append(png)

    # Inject images into existing step sections
    for step_key, images in step_injections.items():
        injection_html = ''
        for img_path, alt_text in images:
            chunk = _embed_image_as_base64(img_path, alt_text)
            if chunk:
                injection_html += chunk
        if not injection_html:
            continue

        marker = f'id="{step_key}"'
        if marker not in sections_html:
            # Can't find the step section — send to appendix instead
            appendix_images.extend([ip for ip, _ in images])
            continue

        # Find the section-body closing div for this step
        pos = sections_html.index(marker)
        body_start = sections_html.find('<div class="section-body">', pos)
        if body_start == -1:
            appendix_images.extend([ip for ip, _ in images])
            continue

        next_section = sections_html.find('<div id="', pos + len(marker))
        search_end = next_section if next_section != -1 else len(sections_html)
        body_end = sections_html.rfind('</div></div>', body_start, search_end)
        if body_end == -1:
            appendix_images.extend([ip for ip, _ in images])
            continue

        # Insert before the closing </div>
        sections_html = (
            sections_html[:body_end]
            + injection_html
            + sections_html[body_end:]
        )

    # Build appendix section for unmatched images
    if appendix_images:
        appendix_body = ''
        for img_path in appendix_images:
            alt = img_path.stem.replace('_', ' ').title()
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
                print(f"Warning: {cfg['file']} not found, skipping")
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
    toc_html = f'<div class="toc"><h2>Table of Contents</h2><ul class="toc-list">{"".join(toc_items)}</ul></div>'

    # --- Build sidebar ---
    sidebar_items = []
    for cfg in STEP_CONFIG:
        sidebar_items.append(
            f'<a href="#{cfg["key"]}"><i class="{cfg["icon"]}"></i> {cfg["title"]}</a>'
        )
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
            f'<div class="section-body">{body_html}</div></div>'
        )

    # --- Auto-embed workspace images not referenced in markdown ---
    sections_html = _auto_embed_workspace_images(ws, sections_html)

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
