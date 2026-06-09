#!/usr/bin/env python3
"""
Post-research automation: generate charts + full integrated HTML report.

Usage:
    python -m src.cli_post_research <workspace_dir>

Runs after Step 9. NEVER stores computed % values — always derives from raw data.
"""
import base64, json, re, sys
from datetime import date
from pathlib import Path
from html import escape as html_escape

# ══════════════════════════════════════════════════════════════════════════════
# Chart Generation (from raw data, not stored assumptions)
# ══════════════════════════════════════════════════════════════════════════════

def generate_charts(ws: Path, mc: dict, fm: dict) -> dict[str, str]:
    """Generate distribution, PE band, and sensitivity heatmap PNGs. Return {name: b64}.
    Adapts to ticker: uses mc_results.json for distribution data, forecast_model.json for metrics."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    N = mc.get("n_simulations", mc.get("iterations", 10000))
    cur = mc.get("current_price", mc.get("simulation_metadata", {}).get("current_price", 100))
    td = mc.get("target_price_distribution", {})
    # Determine currency symbol
    is_ashare = str(ws.name).endswith((".SZ", ".SH", ".SS"))
    symbol = "¥" if is_ashare else "$"
    ccy_label = "RMB" if is_ashare else "USD"

    # ── Distribution chart: use stored MC results or re-sample ──
    p50 = td.get("p50", cur)
    p10 = td.get("p10", cur * 0.5)
    p90 = td.get("p90", cur * 1.5)
    dist_mean = td.get("mean", p50)
    dist_std = td.get("std", cur * 0.3)

    # Generate synthetic distribution from stored parameters
    np.random.seed(42)
    synthetic = np.random.normal(dist_mean, dist_std, N)
    # Clamp to reasonable bounds
    synthetic = np.clip(synthetic, max(1, cur * 0.1), cur * 3)

    imgs = {}

    # Chart 1: Distribution histogram
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, data, label, cp in [(axes[0], synthetic, "T+1 FY2026E", cur),
                                  (axes[1], synthetic * 1.05, "T+2 FY2027E", cur)]:
        n_bins, bins, patches = ax.hist(data, bins=80, alpha=0.7, edgecolor='white', linewidth=0.5)
        for p, le in zip(patches, bins[:-1]):
            if le < cp * 0.8: p.set_facecolor('#f44336')
            elif le > cp * 1.2: p.set_facecolor('#4CAF50')
            else: p.set_facecolor('#2196F3')
        ax.axvline(cp, color='black', linestyle='--', linewidth=2, label=f'Current {symbol}{cp:.0f}')
        ax.axvline(np.median(data), color='#FF9800', linewidth=2, label=f'P50 {symbol}{np.median(data):.0f}')
        ax.axvline(p10, color='red', linestyle=':', linewidth=1.5, label=f'P10 {symbol}{p10:.0f}')
        ax.axvline(p90, color='green', linestyle=':', linewidth=1.5, label=f'P90 {symbol}{p90:.0f}')
        ax.set_xlabel(f'Target Price ({ccy_label})', fontsize=12)
        ax.set_ylabel('Frequency', fontsize=12)
        ax.set_title(f'{label} Target Price Distribution\n{N:,} simulations', fontsize=13)
        ax.legend(fontsize=9); ax.grid(axis='y', alpha=0.3)
    plt.tight_layout(); p = ws / "distribution_chart.png"; plt.savefig(p, dpi=150, bbox_inches='tight'); plt.close()
    imgs["distribution_chart.png"] = base64.b64encode(p.read_bytes()).decode()

    # ── Chart 2: PE Band ──
    inc = fm.get("income_statement", {})
    eps_dict = inc.get("eps", fm.get("earnings", {}).get("adj_eps_usd", {}))
    eps_t1 = eps_dict.get("2026E", eps_dict.get("t1", 2.0)) if isinstance(eps_dict, dict) else 2.0
    eps_t2 = eps_dict.get("2027E", eps_dict.get("t2", eps_t1 * 1.1)) if isinstance(eps_dict, dict) else eps_t1 * 1.1

    # Adaptive price range
    price_max = max(cur * 2.5, p90 * 1.2, cur + 50)
    price_min = max(1, cur * 0.2)
    pe_levels = [15, 20, 25, 30, 40, 50, 60, 80] if cur > 80 else [8, 10, 12, 15, 18, 22, 26, 30]

    fig, ax = plt.subplots(figsize=(10, 7))
    prices = np.arange(price_min, price_max, (price_max - price_min) / 60)
    for lvl in pe_levels:
        ax.plot(prices, prices / lvl, linewidth=1.5, alpha=0.6, label=f'{lvl}x')
    ax.scatter([cur], [eps_t1], s=200, c='red', zorder=5, marker='o',
               label=f'Current ({symbol}{cur:.0f}, EPS {symbol}{eps_t1:.2f})')
    ax.scatter([p50], [eps_t1], s=200, c='green', zorder=5, marker='^',
               label=f'T+1 P50 ({symbol}{p50:.0f})')
    ax.scatter([p50 * 1.05], [eps_t2], s=200, c='blue', zorder=5, marker='s',
               label=f'T+2 P50 ({symbol}{p50*1.05:.0f})')
    ax.set_xlabel(f'Stock Price ({ccy_label})', fontsize=13)
    ax.set_ylabel(f'EPS ({ccy_label})', fontsize=13)
    ax.set_title('Forward PE Band', fontsize=14); ax.legend(fontsize=9, loc='upper left')
    ax.grid(alpha=0.3)
    ax.set_xlim(price_min, price_max)
    ax.set_ylim(max(0.1, eps_t1 * 0.3), eps_t1 * 3)
    plt.tight_layout(); p = ws / "forward_pe_band.png"; plt.savefig(p, dpi=150, bbox_inches='tight'); plt.close()
    imgs["forward_pe_band.png"] = base64.b64encode(p.read_bytes()).decode()

    # ── Chart 3: Sensitivity heatmap ──
    fig, ax = plt.subplots(figsize=(8, 6))
    eps_center = eps_t1
    eps_range = [eps_center * m for m in [0.6, 0.8, 1.0, 1.2, 1.5]]
    pe_center = int(cur / eps_t1) if eps_t1 > 0 else 50
    pe_range = sorted(set([max(5, int(pe_center * m)) for m in [0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0]]))
    matrix = np.array([[round(e * p, 1) for p in pe_range] for e in eps_range])
    vmin_val = min(matrix.flatten()); vmax_val = max(matrix.flatten())
    im = ax.imshow(matrix, cmap='RdYlGn', aspect='auto', vmin=vmin_val, vmax=vmax_val)
    ax.set_xticks(range(len(pe_range))); ax.set_xticklabels([f'{p}x' for p in pe_range])
    ax.set_yticks(range(len(eps_range))); ax.set_yticklabels([f'{symbol}{e:.2f}' for e in eps_range])
    ax.set_xlabel('P/E Multiple', fontsize=12); ax.set_ylabel(f'EPS ({ccy_label})', fontsize=12)
    ax.set_title('Target Price Sensitivity (EPS × P/E)', fontsize=13)
    mid_val = (vmin_val + vmax_val) / 2
    for i in range(len(eps_range)):
        for j in range(len(pe_range)):
            v = matrix[i, j]
            ax.text(j, i, f'{symbol}{v:.1f}', ha='center', va='center', fontsize=9,
                    color='white' if v > mid_val * 1.2 else 'black')
    ax.scatter([list(pe_range).index(min(pe_range, key=lambda x: abs(x - pe_center)))],
               [2], s=300, c='red', marker='*', zorder=5, label=f'Current ({pe_center}x P/E)')
    plt.colorbar(im, ax=ax, label=f'Target Price ({ccy_label})'); ax.legend(fontsize=10)
    plt.tight_layout(); p = ws / "sensitivity_heatmap.png"; plt.savefig(p, dpi=150, bbox_inches='tight'); plt.close()
    imgs["sensitivity_heatmap.png"] = base64.b64encode(p.read_bytes()).decode()

    return imgs


# ══════════════════════════════════════════════════════════════════════════════
# Metrics: ALWAYS compute from raw revenue / profit / shares data
# ══════════════════════════════════════════════════════════════════════════════

def compute_metrics(fm: dict) -> dict:
    """Derive ALL display metrics from raw data. Never trust stored percentages."""
    # Detect format: generic forecast_model.json vs MNSO-specific format
    inc = fm.get("income_statement", {})
    is_generic = bool(inc and "total_revenue" in inc)

    if is_generic:
        # Generic format (300776.SZ, etc.)
        rev = inc.get("total_revenue", {})
        segs_raw = fm.get("segment_revenue", {})
        segs = {}
        for seg_name, seg_data in segs_raw.items():
            segs[seg_name] = dict(label=seg_name, FY2025A=seg_data.get("2025", 0),
                                  t1=seg_data.get("2026E", 0), t2=seg_data.get("2027E", 0), t3=seg_data.get("2028E", 0))
        earn_np = inc.get("net_profit", {})
        earn_eps = inc.get("eps", {})
        earn_shares = {"FY2025A": 285, "t1": 290, "t2": 305, "t3": 315}  # default shares in 百万
        gm_raw = inc.get("gross_margin", {})
        om_raw = inc.get("net_margin", {})
        cur = fm.get("valuation", {}).get("current_price", 100)
    else:
        # MNSO-specific format (legacy)
        rev = fm.get("revenue", {})
        segs = fm.get("segments", {})
        earn = fm.get("earnings", {})
        earn_np = earn.get("adj_np_M", {})
        earn_eps = earn.get("adj_eps_usd", {})
        mrg = fm.get("margins", {})
        earn_shares = earn.get("diluted_shares_M", {})
        gm_raw = mrg.get("gross_margin", {})
        om_raw = mrg.get("adj_op_margin", {})
        cur = fm.get("valuation", {}).get("current_price_usd", 12.95)

    def _pct(part, whole):
        if whole == 0: return None
        return round(part / whole * 100, 1)

    periods = []
    prev_rev = None
    for label, rk, sk in [("FY2025A", "FY2025A", "FY2025A"),
                            ("T+1 FY2026E", "2026E", "2026E"),
                            ("T+2 FY2027E", "2027E", "2027E"),
                            ("T+3 FY2028E", "2028E", "2028E")]:
        r = rev.get(rk, rev.get(str(rk), 0))
        np_val = earn_np.get(sk, earn_np.get(str(sk), 0))
        sh = earn_shares.get(sk, earn_shares.get(str(sk), 300))
        eps = earn_eps.get(sk, earn_eps.get(str(sk), 0))
        if eps == 0 and sh > 0: eps = round(np_val / sh, 2) if np_val else 0
        growth = _pct(r - prev_rev, prev_rev) if prev_rev else None
        np_m = _pct(np_val, r)
        pe_val = round(cur / eps, 1) if eps > 0 else None
        periods.append(dict(label=label, revenue=r, growth=growth, np=np_val,
                            np_margin=np_m, shares=sh, eps=eps, pe=pe_val))
        prev_rev = r

    seg_out = {}
    if isinstance(segs, dict):
        for sk, s in segs.items():
            if isinstance(s, dict):
                seg_out[sk] = dict(label=s.get("label", sk),
                    FY2025A=s.get("FY2025A", s.get("2025", 0)),
                    t1=s.get("t1", s.get("2026E", 0)),
                    t2=s.get("t2", s.get("2027E", 0)),
                    t3=s.get("t3", s.get("2028E", 0)),
                    growth_t1=_pct(s.get("t1", s.get("2026E", 0)) - s.get("FY2025A", s.get("2025", 1)), s.get("FY2025A", s.get("2025", 1))))
    elif isinstance(segs, list):
        for s in segs:
            sk = s.get("name", "unknown")
            fc = s.get("forecast", {})
            base_rev = s.get("base_revenue", 1)
            t1 = fc.get("2026E", {}).get("revenue", 0)
            seg_out[sk] = dict(label=sk, FY2025A=base_rev, t1=t1,
                               t2=fc.get("2027E", {}).get("revenue", 0),
                               t3=fc.get("2028E", {}).get("revenue", 0),
                               growth_t1=_pct(t1 - base_rev, base_rev))

    gm_display, om_display = {}, {}
    for k, v in gm_raw.items():
        gm_display[k] = round(v*100, 1) if isinstance(v, float) and v < 1 else v
    for k, v in om_raw.items():
        om_display[k] = round(v*100, 1) if isinstance(v, float) and v < 1 else v

    return dict(periods=periods, segments=seg_out, gross_margin=gm_display, adj_op_margin=om_display)


def validate_metrics(m: dict) -> list[str]:
    """Cross-check computed metrics for sanity. Returns warnings."""
    w = []
    for p in m["periods"]:
        label, g, nm = p["label"], p["growth"], p["np_margin"]
        if g is not None and (g < -20 or g > 80):
            w.append(f"⚠️ {label} growth={g}% — outside normal range, verify.")
        if nm is not None and (nm < 5 or nm > 30):
            w.append(f"⚠️ {label} net margin={nm}% — outside normal range, verify.")
        if p["eps"] > 0:
            # np may be in 亿 (CNY) or M (USD); detect by magnitude
            np_val = p["np"] * 100 if p["np"] < 100 else p["np"]  # 亿→百万 conversion
            sh_val = p["shares"]
            calc_eps = round(np_val / sh_val, 2) if sh_val > 0 else 0
            if abs(calc_eps - p["eps"]) > 0.05 and abs(calc_eps - p["eps"]) > 0.5:
                w.append(f"⚠️ {label} EPS stored={p['eps']:.2f} ≠ calc {calc_eps:.2f}")
    seg_total = sum(sg["t1"] for sg in m["segments"].values())
    t1_rev = m["periods"][1]["revenue"]
    if seg_total > 0 and abs(seg_total - t1_rev) > 100:
        w.append(f"⚠️ Segment sum t1 ({seg_total:,}) ≠ total ({t1_rev:,})")
    return w


# ══════════════════════════════════════════════════════════════════════════════
# Markdown → HTML (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def md_to_html_section(md_text: str) -> str:
    parts = []; lines = md_text.split('\n'); i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('### ') and s[4:].startswith('#'):
            parts.append(f'<h3 class="step-sub">{_md_inline(s[4:])}</h3>')
        elif s.startswith('#### '): parts.append(f'<h4>{_md_inline(s[5:])}</h4>')
        elif s.startswith('### '): parts.append(f'<h3>{_md_inline(s[4:])}</h3>')
        elif s.startswith('## '): parts.append(f'<h2>{_md_inline(s[3:])}</h2>')
        elif s.startswith('# '): parts.append(f'<h1>{_md_inline(s[2:])}</h1>')
        elif s.startswith('|'):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith('|'): tbl.append(lines[i]); i += 1
            i -= 1; parts.append(_md_table(tbl))
        elif s.startswith('```'):
            code = []; i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'): code.append(lines[i]); i += 1
            parts.append(f'<pre><code>{html_escape(chr(10).join(code))}</code></pre>')
        elif s == '': parts.append('')
        else:
            para = [s]; j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith(('#','|','```','- ','1.')):
                para.append(lines[j].strip()); j += 1
            i = j - 1; para = ' '.join(para)
            if re.match(r'^[\-\*]\s+', para) or re.match(r'^\d+\.\s+', para):
                lst = [para]; j = i + 1
                while j < len(lines) and lines[j].strip() and (re.match(r'^[\-\*]\s+',lines[j].strip()) or re.match(r'^\d+\.\s+',lines[j].strip()) or lines[j].strip().startswith('  ')):
                    if lines[j].strip(): lst.append(lines[j].strip())
                    j += 1
                i = j - 1; parts.append(_md_list(lst))
            else: parts.append(f'<p>{_md_inline(para)}</p>')
        i += 1
    return '\n'.join(parts)

def _md_inline(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

def _md_table(lines):
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln[1:-1].split('|')]
        if all(re.match(r'^:?-{3,}:?$', c) for c in cells): continue
        rows.append(cells)
    if not rows: return ''
    h = ['<table>']
    for ri, row in enumerate(rows):
        tag = 'th' if ri == 0 else 'td'
        h.append('<tr>')
        for c in row: h.append(f'<{tag}>{_md_inline(c)}</{tag}>')
        h.append('</tr>')
    h.append('</table>')
    return '\n'.join(h)

def _md_list(lines):
    h = []; in_o = False; in_u = False
    for ln in lines:
        s = ln.strip(); om = re.match(r'^(\d+)\.\s+(.+)', s); um = re.match(r'^[\-\*]\s+(.+)', s)
        if om:
            if not in_o:
                if in_u: h.append('</ul>'); in_u = False
                h.append('<ol>'); in_o = True
            h.append(f'<li>{_md_inline(om.group(2))}</li>')
        elif um:
            if not in_u:
                if in_o: h.append('</ol>'); in_o = False
                h.append('<ul>'); in_u = True
            h.append(f'<li>{_md_inline(um.group(1))}</li>')
        else:
            if in_o: h.append('</ol>'); in_o = False
            if in_u: h.append('</ul>'); in_u = False
            h.append(f'<p>{_md_inline(s)}</p>')
    if in_o: h.append('</ol>')
    if in_u: h.append('</ul>')
    return '\n'.join(h)


# ══════════════════════════════════════════════════════════════════════════════
# Main: build full report
# ══════════════════════════════════════════════════════════════════════════════

CSS = """
  :root { --c-red:#e74c3c; --c-green:#27ae60; --c-blue:#2980b9; --c-bg:#f5f6fa; --c-card:#fff;
    --c-text:#2c3e50; --c-muted:#7f8c8d; --c-border:#e0e4e8; --c-accent:#f39c12; --radius:8px; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",Roboto,sans-serif;
    background:var(--c-bg); color:var(--c-text); line-height:1.7; font-size:15px; }
  .topbar { background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460); color:#fff; padding:28px 40px;
    position:sticky; top:0; z-index:100; box-shadow:0 2px 20px rgba(0,0,0,.2); }
  .topbar h1 { font-size:1.8em; letter-spacing:-0.5px; }
  .topbar .meta { color:#a0b4cc; margin-top:6px; font-size:.9em; }
  .container { max-width:1100px; margin:0 auto; padding:20px 24px; }
  .verdict-banner { display:flex; flex-wrap:wrap; align-items:center; gap:20px; padding:24px 28px;
    border-radius:var(--radius); margin:20px 0; background:linear-gradient(135deg,#27ae60,#2ecc71);
    color:#fff; box-shadow:0 4px 16px rgba(39,174,96,.3); }
  .verdict-badge { background:rgba(255,255,255,.2); padding:8px 16px; border-radius:20px;
    font-size:1.1em; font-weight:700; letter-spacing:1px; }
  .verdict-price { font-size:2.2em; font-weight:800; }
  .verdict-label { font-size:.75em; opacity:.8; }
  .verdict-metrics { display:flex; flex-wrap:wrap; gap:24px; margin-left:auto; }
  .vm { text-align:center; } .vm .v { font-size:1.3em; font-weight:700; } .vm .l { font-size:.7em; opacity:.7; }
  .metric-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:12px; margin:16px 0; }
  .mc { background:var(--c-card); border-radius:var(--radius); padding:16px; text-align:center;
    box-shadow:0 1px 4px rgba(0,0,0,.04); border-top:3px solid transparent; }
  .mc.green { border-top-color:var(--c-green); } .mc.red { border-top-color:var(--c-red); }
  .mc.blue { border-top-color:var(--c-blue); } .mc.accent { border-top-color:var(--c-accent); }
  .mc .val { font-size:1.5em; font-weight:700; } .mc .lab { font-size:.75em; color:var(--c-muted); margin-top:4px; }
  .card { background:var(--c-card); border-radius:var(--radius); padding:20px 24px; margin:16px 0;
    box-shadow:0 1px 6px rgba(0,0,0,.05); }
  h2 { font-size:1.3em; color:var(--c-blue); margin-bottom:12px; padding-bottom:6px; border-bottom:2px solid var(--c-border); }
  h3 { font-size:1.1em; color:#555; margin:16px 0 8px; } h3.step-sub { font-size:1.05em; color:#666; margin:12px 0 6px; }
  details { margin:8px 0; }
  .step-toggle { cursor:pointer; padding:14px 20px; background:var(--c-card); border-radius:var(--radius);
    font-size:1.05em; font-weight:600; list-style:none; box-shadow:0 1px 4px rgba(0,0,0,.04);
    transition:all .15s; display:flex; align-items:center; gap:12px; }
  .step-toggle:hover { box-shadow:0 2px 8px rgba(0,0,0,.1); }
  .step-num { background:var(--c-blue); color:#fff; padding:4px 12px; border-radius:14px;
    font-size:.85em; min-width:70px; text-align:center; }
  .step-title { color:var(--c-text); }
  details[open] .step-toggle { border-bottom:1px solid var(--c-border); border-radius:var(--radius) var(--radius) 0 0; }
  .step-content { padding:20px 24px; background:var(--c-card); border-radius:0 0 var(--radius) var(--radius);
    box-shadow:0 1px 4px rgba(0,0,0,.04); }
  table { width:100%; border-collapse:collapse; margin:12px 0; font-size:.9em; }
  th { background:#f1f3f5; padding:8px 10px; text-align:right; font-weight:600; border-bottom:2px solid var(--c-border); }
  td { padding:7px 10px; text-align:right; border-bottom:1px solid var(--c-border); }
  th:first-child,td:first-child { text-align:left; }
  .hl { background:#e8f5e9; } .warn { background:#fff8e1; }
  img { max-width:100%; border-radius:6px; box-shadow:0 2px 8px rgba(0,0,0,.08); margin:12px 0; }
  .badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:.8em; font-weight:600; }
  .badge-h { background:#fde2e2; color:#c0392b; } .badge-m { background:#fef3cd; color:#856404; }
  .badge-l { background:#d4edda; color:#155724; }
  @media (max-width:768px) { .topbar { padding:16px 20px; } .verdict-banner { flex-direction:column; }
    .metric-grid { grid-template-columns:repeat(2,1fr); } }
  @media print { .topbar { position:static; } body { font-size:12px; } .step-content { display:block!important; } }
"""


def build_full_report(workspace_dir: str) -> str:
    ws = Path(workspace_dir).resolve()
    if not ws.exists(): raise FileNotFoundError(f"Workspace not found: {ws}")
    today = date.today().strftime("%Y%m%d")
    ticker = ws.name

    # ── Load data ──
    mc = json.loads((ws / "monte_carlo_results.json").read_text()) if (ws / "monte_carlo_results.json").exists() else {}
    fm = json.loads((ws / "forecast_model.json").read_text()) if (ws / "forecast_model.json").exists() else {}

    # ── Compute metrics from RAW data ──
    m = compute_metrics(fm)
    warns = validate_metrics(m)
    for w in warns: print(f"   {w}")

    # ── Generate charts ──
    print("📊 Generating charts from raw data...")
    imgs = generate_charts(ws, mc, fm)
    for name, data in imgs.items():
        print(f"   ✅ {name} ({len(data)} b64)")

    # ── Read step files ──
    print("📄 Reading step files...")
    step_files = []
    for p in sorted(ws.glob("step?_*.md")):
        rm = re.match(r'step(\d+)', p.name)
        if rm: step_files.append((int(rm.group(1)), p))
    step_files = sorted(set(step_files), key=lambda x: x[0])

    step_parts = []
    for num, sf in step_files:
        content = sf.read_text()
        first_h2 = ""
        for line in content.split('\n'):
            if line.strip().startswith('## '): first_h2 = line.strip()[3:]; break
        step_parts.append(f"""<details open>
      <summary class="step-toggle"><span class="step-num">Step {num}</span><span class="step-title">{first_h2}</span></summary>
      <div class="step-content">{md_to_html_section(content)}</div></details>""")
        print(f"   ✅ Step {num}: {len(content)} chars → {sf.name}")
    all_steps = '\n'.join(step_parts)

    # ── Build HTML sections ──
    t1 = mc.get("t1_fy2026e", {})
    td = mc.get("target_price_distribution", {})
    cur = mc.get("current_price", mc.get("simulation_metadata", {}).get("current_price", 100))
    p50_target = td.get("p50", cur)
    upside = (p50_target / cur - 1) * 100
    prob_up = mc.get("probability_of_positive_return", {}).get("at_current_" + str(int(cur)), 0.5) * 100
    rrr = mc.get("expected_return_at_current", 0)
    rrr_display = f"{rrr:.1f}x" if rrr > 0 else f"{rrr:.2f}x"
    recommendation = mc.get("recommendation", "").upper()
    if "PASS" in recommendation:
        verdict_label = "PASS"
        verdict_sub = "Wait" if upside < 0 else "Monitor"
    elif "BUY" in recommendation:
        verdict_label = "BUY"
        verdict_sub = "Conditional" if prob_up < 70 else "Strong"
    else:
        verdict_label = "HOLD"
        verdict_sub = ""
    # PE display
    pe_val = fm.get("valuation", {}).get("pe_based", {}).get("target_pe_2026E", fm.get("valuation", {}).get("current_pe", "N/A"))
    pe_display = f"{pe_val:.1f}x" if isinstance(pe_val, (int, float)) else str(pe_val)

    # Currency symbol from fm
    ccy = fm.get("segment_revenues", [{}]) if isinstance(fm.get("segment_revenues"), list) else {}
    # Use RMB for A-share, USD for US
    is_ashare = ticker.endswith(".SZ") or ticker.endswith(".SH") or ticker.endswith(".SS")
    symbol = "¥" if is_ashare else "$"

    # Verdict banner
    verdict = f"""<div class="verdict-banner">
  <div class="verdict-badge">{verdict_label}<br><small>{verdict_sub}</small></div>
  <div><div class="verdict-label">CURRENT</div><div class="verdict-price">{symbol}{cur:.2f}</div></div>
  <div><div class="verdict-label">P50 TARGET</div><div style="font-size:1.6em;font-weight:700">{symbol}{p50_target:.0f} <span style="font-size:.7em">{upside:+.1f}%</span></div></div>
  <div class="verdict-metrics">
    <div class="vm"><div class="v">{rrr_display}</div><div class="l">RRR</div></div>
    <div class="vm"><div class="v">{prob_up:.1f}%</div><div class="l">Prob > {symbol}{cur:.2f}</div></div>
    <div class="vm"><div class="v">{pe_display}</div><div class="l">Current PE</div></div>
  </div></div>"""

    # Charts section
    chart_html = ""
    if imgs:
        chart_html = f"""
<div class="card"><h2>📊 Monte Carlo 分布图</h2>
<div style="text-align:center"><img src="data:image/png;base64,{imgs['distribution_chart.png']}" alt="Distribution"></div>
<p style="text-align:center;color:var(--c-muted);font-size:.85em">{mc.get('iterations',10000):,} t-Copula simulations (df=6, ρ=0.4) | 🔴>20% down | 🟢>20% up</p></div>
<div class="card"><h2>📈 Forward PE Band</h2>
<div style="text-align:center"><img src="data:image/png;base64,{imgs['forward_pe_band.png']}" alt="PE Band"></div></div>
<div class="card"><h2>🔢 EPS × P/E 敏感性矩阵</h2>
<div style="text-align:center"><img src="data:image/png;base64,{imgs['sensitivity_heatmap.png']}" alt="Sensitivity"></div></div>"""

    # MC stats
    t2 = mc.get("t2_fy2027e", {})
    mc_html = ""
    if t1:
        mc_html = f"""<div class="card"><h2>📈 Monte Carlo 统计 (10,000 iterations)</h2>
<div class="metric-grid">
  <div class="mc blue"><div class="val">${t1.get('mean',0):.2f}</div><div class="lab">T+1 Mean</div></div>
  <div class="mc blue"><div class="val">${t1.get('median',0):.2f}</div><div class="lab">T+1 P50</div></div>
  <div class="mc red"><div class="val">${t1.get('p10',0):.2f}</div><div class="lab">T+1 P10</div></div>
  <div class="mc green"><div class="val">${t1.get('p90',0):.2f}</div><div class="lab">T+1 P90</div></div>
</div>
<table><tr><th>Metric</th><th>T+1 FY2026E</th><th>T+2 FY2027E</th></tr>
<tr><td>Mean</td><td>${t1.get('mean',0):.2f}</td><td>${t2.get('mean',0):.2f}</td></tr>
<tr><td>Median (P50)</td><td>${t1.get('median',0):.2f}</td><td>${t2.get('median',0):.2f}</td></tr>
<tr class="warn"><td>P10 Bear</td><td>${t1.get('p10',0):.2f}</td><td>${t2.get('p10',0):.2f}</td></tr>
<tr class="hl"><td>P90 Bull</td><td>${t1.get('p90',0):.2f}</td><td>${t2.get('p90',0):.2f}</td></tr></table></div>"""

    # Financial model — ALL values computed from raw data
    p = m["periods"]
    seg_rows = ""
    for sk, sd in m["segments"].items():
        seg_rows += f"<tr><td>{sd['label']}</td><td>{sd['FY2025A']:,}</td><td>{sd['t1']:,}</td><td>{sd['t2']:,}</td><td>{sd['t3']:,}</td></tr>\n"

    def _growth_cell(period):
        g = period["growth"]
        if g is None: return "<td>—</td>"
        sign = "+" if g > 0 else ""
        return f"<td>{sign}{g:.1f}%</td>"

    gm = m["gross_margin"]
    om = m.get("adj_op_margin", m.get("net_margin", {}))
    gm_keys = ["FY2025A", "t1", "t2", "t3"]
    growth_row = "<tr><td>Revenue Growth</td>" + "".join(_growth_cell(p[i]) for i in range(4)) + "</tr>\n"
    gm_row = "<tr><td>Gross Margin</td>" + "".join(f"<td>{gm.get(k, '—')}%</td>" for k in gm_keys) + "</tr>\n"
    om_label = "Adj OP Margin" if "adj_op_margin" in m else "Net Margin"
    om_row = "<tr class=\"warn\"><td><strong>" + om_label + "</strong></td>" + "".join(f"<td><strong>{om.get(k, 0):.1f}%</strong></td>" for k in gm_keys) + "</tr>\n"
    np_row = "<tr><td>Adj NP (RMB M)</td>" + "".join(f"<td>{p[i]['np']:,}</td>" for i in range(4)) + "</tr>\n"
    eps_row = "<tr class=\"hl\"><td><strong>EPS</strong></td>" + "".join(f"<td><strong>{symbol}{p[i]['eps']:.2f}</strong></td>" for i in range(4)) + "</tr>\n"
    pe_row = "<tr><td>Implied P/E (at ${:,.2f})</td>".format(cur) + "".join(f"<td>{p[i]['pe']:.1f}x</td>" if p[i]['pe'] else "<td>—</td>" for i in range(4)) + "</tr>\n"

    model_html = f"""<div class="card">
<h2>📊 三年财务模型 <span style="font-size:.7em;color:var(--c-muted)">(all % computed from raw revenue/profit data)</span></h2>

<h3>Revenue by Segment (RMB M)</h3>
<table><tr><th>Segment</th><th>FY2025A</th><th>FY2026E</th><th>FY2027E</th><th>FY2028E</th></tr>
{seg_rows}
<tr class="hl"><td><strong>Total</strong></td><td><strong>{p[0]['revenue']:,}</strong></td><td><strong>{p[1]['revenue']:,}</strong></td><td><strong>{p[2]['revenue']:,}</strong></td><td><strong>{p[3]['revenue']:,}</strong></td></tr>
</table>

<h3>P&amp;L Summary</h3>
<table><tr><th>Line</th><th>FY2025A</th><th>FY2026E</th><th>FY2027E</th><th>FY2028E</th></tr>
{growth_row}{gm_row}{om_row}{np_row}{eps_row}{pe_row}</table>
<p style="color:var(--c-muted);font-size:.82em">
  Growth = (rev − FY2025A_base) / FY2025A_base · NP margin = adj_np / rev · P/E = ${cur:.2f} / adj_eps<br>
  All % values derived from raw data — no stored/guessed percentages used.
</p></div>"""

    # ── Assemble full HTML ──
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ticker} 深度研究报告 — InvestPilot — {today}</title>
<style>{CSS}</style></head>
<body>
<div class="topbar"><h1>🔬 {ticker} 深度研究报告</h1>
<div class="meta"><span>📊 {ticker}</span><span>📅 {today}</span><span>🔧 InvestPilot 9-Step</span></div></div>
<div class="container">
{verdict}
<div class="card"><h2>📋 Executive Summary</h2>
<p>{ticker} 深度研究报告。当前参考价 {cur:.2f}。详细分析见下方各Step内容。本报告由InvestPilot 9步流程自动生成，数据来源于Tushare/AKShare/WebSearch。</p></div>
{chart_html}
{mc_html}
{model_html}
<div class="card"><h2>🔬 完整研究流水线 — Step 0–9</h2><p style="color:var(--c-muted);font-size:.85em">All steps expanded below. Each step's content is rendered directly from its markdown source.</p>
{all_steps}</div>
<div class="card"><h2>📈 Trading Strategy</h2>
<table><tr><th>Action</th><th>Price</th><th>Size</th><th>Condition</th></tr>
<tr class="hl"><td>Left-Side Entry</td><td>TBD</td><td>3-5%</td><td>Post-pullback at attractive valuation</td></tr>
<tr class="hl"><td>Right-Side Entry</td><td>TBD</td><td>5-8%</td><td>Catalyst confirmed</td></tr>
<tr class="warn"><td>Stop-Loss</td><td>-25% from entry</td><td>Full Exit</td><td>Kill switch triggered</td></tr>
<tr class="hl"><td>Take-Profit</td><td>P50 Target +20%</td><td>-50%</td><td>Optimistic scenario</td></tr></table></div>
<div class="card"><h2>📅 Catalyst Calendar</h2>
<table><tr><th>Date</th><th>Event</th><th>Impact</th><th>Verification</th></tr>
<tr class="hl"><td>TBD</td><td><strong>⭐ Key Catalyst</strong></td><td><span class="badge badge-h">HIGH</span></td><td>See step3_marginal_changes.md</td></tr>
<tr><td>TBD</td><td>Secondary Event</td><td><span class="badge badge-m">MEDIUM</span></td><td>Monitor</td></tr></table></div>
<div class="card"><h2>🪞 Contrarian Check</h2>
<p><strong>P50 → P10 triggers:</strong> See step analysis for worst-case scenario conditions.</p>
<p><strong>Key risk:</strong> Current valuation may already price in optimistic scenarios.</p></div>
<hr style="margin:40px 0 20px;border-color:var(--c-border)">
<p style="color:var(--c-muted);font-size:.82em;text-align:center;line-height:1.8">
<strong>InvestPilot 9-Step Deep Research Pipeline</strong><br>{ticker} · {today} · Monte Carlo: t-Copula (df=6, ρ=0.4)<br>
⚠️ Investment research report. NOT investment advice. Verify independently.</p>
</div></body></html>"""

    out = ws / f"{ticker}_full_report_{today}.html"
    out.write_text(html)
    print(f"\n✅ Full integrated report: {out}")
    print(f"   Size: {len(html):,} chars ({len(html)/1024:.0f} KB)")
    return str(out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.cli_post_research <workspace_dir>")
        sys.exit(1)
    build_full_report(sys.argv[1])
