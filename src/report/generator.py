import re
import base64
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime


def format_currency(value, currency: str = "USD") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    prefixes = {"USD": "$", "HKD": "HK$", "CNY": "¥"}
    prefix = prefixes.get(currency, "")
    if abs(value) >= 1e12:
        return f"{prefix}{value/1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{prefix}{value/1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{prefix}{value/1e6:.2f}M"
    return f"{prefix}{value:,.2f}"


def format_pct(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    try:
        return f"{value:.1%}"
    except (TypeError, ValueError):
        return "N/A"


def df_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df is None or df.empty:
        return "*No data available*"
    display_df = df.head(max_rows)
    return display_df.to_markdown()


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


def generate_report_md(
    ticker: str,
    market: str,
    sections: dict,
    output_dir: Path,
) -> Path:
    """Assemble final Markdown report from sections dict.

    sections: {"executive_summary": "...", "business_analysis": "...", ...}
    """
    currency = {"US": "USD", "HK": "HKD", "ASHARE": "CNY"}[market]
    date_str = datetime.now().strftime("%Y-%m-%d")

    report = f"""# {ticker} Investment Research Report
> Date: {date_str} | Market: {market} | Currency: {currency}

---

"""

    section_order = [
        ("executive_summary", "Executive Summary"),
        ("business_analysis", "1. Business Analysis"),
        ("competitive_moat", "2. Competitive Moat"),
        ("marginal_changes", "3. Marginal Changes & Expectation Gap"),
        ("quantitative_model", "4. Quantitative Model & Monte Carlo"),
        ("rrr_and_strategy", "5. RRR & Trading Strategy"),
        ("auditing", "6. Auditing & Quality Control"),
        ("research_director_review", "7. Research Director Review"),
    ]

    for key, title in section_order:
        if key in sections and sections[key]:
            report += f"## {title}\n\n{sections[key]}\n\n---\n\n"

    report += """---
*Disclaimer: This report is generated by an AI research assistant for informational purposes only. It does not constitute investment advice.*
"""

    filename = f"{ticker}_{datetime.now().strftime('%Y%m%d')}.md"
    output_path = output_dir / filename
    output_path.write_text(report, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# HTML report generation: markdown-to-HTML converter + helpers
# ---------------------------------------------------------------------------

def _convert_inline(text: str) -> str:
    """Convert inline markdown: **bold** -> <strong>, `code` -> <code>."""
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


def _convert_image(line: str, workspace_dir) -> str:
    """Convert ![alt](file.png) to base64-embedded <img>."""
    m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
    if not m:
        return f'<p>{_convert_inline(line.strip())}</p>'
    alt, src = m.group(1), m.group(2)
    if workspace_dir:
        img_path = workspace_dir / src
        if img_path.exists():
            data = base64.b64encode(img_path.read_bytes()).decode('ascii')
            return (f'<div class="chart-container">'
                    f'<img src="data:image/png;base64,{data}" alt="{alt}">'
                    f'<p class="chart-caption">{alt}</p></div>')
    return f'<p><em>Image not found: {src}</em></p>'


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

        # Headings: #### -> h5, ### -> h4, ## -> h3
        if stripped.startswith('####'):
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
# Summary metrics extraction
# ---------------------------------------------------------------------------

def _extract_summary_metrics(workspace_dir, ticker: str) -> dict:
    """Extract key metrics from step files and JSON artifacts."""
    from pathlib import Path
    import json

    ws = Path(workspace_dir)
    metrics = {}

    def _read_file(name):
        p = ws / name
        return p.read_text(encoding='utf-8') if p.exists() else ''

    # From step4: current price, forward PE, target price
    s4 = _read_file('step4_quantitative_model.md')
    m = re.search(r'当前股价[：:]\s*[~～]?([\d.]+)', s4)
    if m:
        metrics['current_price'] = m.group(1)
    m = re.search(r'Forward PE[^(]*?([\d.]+)x', s4)
    if m:
        metrics['forward_pe'] = m.group(1) + 'x'
    # P50 target price — prefer T+2 if present (重大变化期), else T+1
    # Strategy: find T+2 results section, extract P50 from it; fallback to last bold P50
    t2_section = re.search(
        r'(?:T\+2.*?蒙特卡洛结果|主估算.*?蒙特卡洛结果)(.*?)(?=\n##|\Z)',
        s4, re.DOTALL | re.IGNORECASE
    )
    t2_tp = None
    if t2_section:
        m = re.search(r'\|\s*\*{0,2}P50\*{0,2}\s*\|\s*\*{0,2}([\d.]+)\*{0,2}', t2_section.group(1))
        if m:
            t2_tp = m.group(1)

    # All bold P50 rows (target price tables use **P50**)
    all_bold_p50 = list(re.finditer(
        r'\|\s*\*{2}P50\*{2}\s*\|\s*\*{2}([\d.]+)\*{2}', s4
    ))

    if t2_tp:
        metrics['target_price'] = t2_tp
        metrics['forward_year'] = 'T+2'
    elif all_bold_p50:
        # Last bold P50 is likely T+2 (appears after T+1 in the document)
        metrics['target_price'] = all_bold_p50[-1].group(1)
    else:
        m = re.search(r'\|\s*\*?\*?P50\*?\*?\s*\|\s*\*?\*?([\d.]+)', s4)
        if m:
            metrics['target_price'] = m.group(1)

    # From step5: RRR — prefer T+2 row if present
    s5 = _read_file('step5_rrr_strategy.md')
    # Look for T+2 RRR first
    m = re.search(r'T\+2.*?RRR.*?([\d.]+)', s5, re.DOTALL)
    if not m:
        m = re.search(r'主估算.*?RRR.*?([\d.]+)', s5, re.DOTALL)
    if not m:
        m = re.search(r'RRR\s*[=：:]\s*([\d.]+)', s5)
    if m:
        metrics['rrr'] = m.group(1)

    # From step2: moat rating
    s2 = _read_file('step2_competitive_moat.md')
    m = re.search(r'(Wide|Narrow|None)\s*(?:Moat)?\s*,?\s*(Widening|Stable|Narrowing)', s2, re.IGNORECASE)
    if m:
        metrics['moat'] = f"{m.group(1)} {m.group(2)}"
    elif re.search(r'Narrow', s2):
        metrics['moat'] = 'Narrow'

    # From edge_score.json
    ej = ws / 'edge_score.json'
    if ej.exists():
        try:
            data = json.loads(ej.read_text(encoding='utf-8'))
            if isinstance(data, list):
                data = data[-1]
            metrics['edge_score'] = str(data.get('composite', data.get('edge_score', '')))
            metrics['edge_grade'] = data.get('composite_grade', '')
        except Exception:
            pass

    # From step7: decision
    s7 = _read_file('step7_research_director_review.md')
    m = re.search(r'\b(Buy|Hold|Pass)\b', s7)
    if m:
        metrics['decision'] = m.group(1)

    # --- Sanity checks on extracted metrics ---
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
                f'<div class="label">{label}</div>'
                f'<div class="value">{val}</div>'
                f'<div class="sub">{sub}</div></div>'
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

    # --- Build header ---
    display_name = company_name or ticker
    title = f"{display_name} ({ticker}) 深度投研报告 | {date_str}"
    price_part = f' | Current: <strong>{metrics.get("current_price", "N/A")}</strong>' if metrics.get('current_price') else ''
    decision_part = metrics.get('decision', 'N/A')
    header_html = (
        f'<div class="sticky-header">'
        f'<div class="logo">Invest<span>Pilot</span> | {display_name} ({ticker})</div>'
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
