"""
HTML template constants for the InvestPilot report generator.

Contains the CSS stylesheet, JavaScript, HTML skeleton, and step
configuration used to produce self-contained HTML research reports.
"""

# ---------------------------------------------------------------------------
# Inline CSS
# ---------------------------------------------------------------------------

REPORT_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; color: #333; background: #f0f2f5; line-height: 1.8; }

/* Sticky Header */
.sticky-header { position: fixed; top: 0; left: 0; right: 0; z-index: 1000; background: linear-gradient(135deg, #1a2744 0%, #2a3f6b 100%); color: #fff; padding: 10px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 12px rgba(0,0,0,0.3); height: 56px; }
.sticky-header .logo { font-size: 18px; font-weight: 700; letter-spacing: 1px; }
.sticky-header .logo span { color: #5b9bd5; }
.sticky-header .meta { font-size: 13px; color: rgba(255,255,255,0.75); }
.sticky-header .meta strong { color: #fff; }

/* Sidebar */
.sidebar { position: fixed; top: 56px; left: 0; width: 260px; height: calc(100vh - 56px); background: #fff; border-right: 1px solid #e0e0e0; overflow-y: auto; z-index: 999; padding: 20px 0; box-shadow: 2px 0 8px rgba(0,0,0,0.05); }
.sidebar h3 { font-size: 13px; color: #999; text-transform: uppercase; letter-spacing: 2px; padding: 10px 24px 8px; }
.sidebar a { display: flex; align-items: center; gap: 10px; padding: 10px 24px; color: #555; text-decoration: none; font-size: 14px; transition: all 0.2s; border-left: 3px solid transparent; }
.sidebar a:hover { background: #f5f7fa; color: #1a2744; border-left-color: #5b9bd5; }
.sidebar a i { width: 18px; text-align: center; font-size: 13px; color: #5b9bd5; }
.sidebar .nav-section { margin-bottom: 8px; }

/* Main Content */
.main-content { margin-left: 260px; margin-top: 56px; padding: 30px 40px 60px; max-width: 1100px; }

/* Section Cards */
.section-card { background: #fff; border-radius: 12px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); margin-bottom: 24px; overflow: hidden; transition: box-shadow 0.3s; }
.section-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
.section-header { background: linear-gradient(135deg, #1a2744 0%, #2a3f6b 100%); color: #fff; padding: 18px 28px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; }
.section-header h2 { font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
.section-header h2 i { font-size: 16px; }
.section-header .toggle { font-size: 14px; transition: transform 0.3s; }
.section-header.collapsed .toggle { transform: rotate(-90deg); }
.section-body { padding: 28px; animation: fadeSlideDown 0.3s ease; }
.section-body.hidden { display: none; }

@keyframes fadeSlideDown { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }

/* Executive Summary Cards */
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }
.summary-card { background: linear-gradient(135deg, #1a2744, #2a3f6b); color: #fff; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(26,39,68,0.3); }
.summary-card .label { font-size: 12px; color: rgba(255,255,255,0.65); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
.summary-card .value { font-size: 26px; font-weight: 700; }
.summary-card .sub { font-size: 12px; color: rgba(255,255,255,0.5); margin-top: 4px; }
.summary-card.green { background: linear-gradient(135deg, #1b5e20, #2e7d32); }
.summary-card.red { background: linear-gradient(135deg, #b71c1c, #c62828); }
.summary-card.blue { background: linear-gradient(135deg, #0d47a1, #1565c0); }
.summary-card.amber { background: linear-gradient(135deg, #e65100, #f57c00); }

/* Content Styling */
h3 { font-size: 16px; color: #1a2744; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #e8ecf2; }
h4 { font-size: 15px; color: #2a3f6b; margin: 18px 0 10px; }
p { margin-bottom: 12px; color: #444; font-size: 14px; }
ul, ol { margin: 8px 0 16px 24px; font-size: 14px; }
li { margin-bottom: 6px; }
strong { color: #1a2744; }

/* Tables */
table { width: 100%; border-collapse: collapse; margin: 14px 0 20px; font-size: 13.5px; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
thead { background: #1a2744; color: #fff; }
th { padding: 12px 16px; text-align: left; font-weight: 600; font-size: 13px; }
td { padding: 10px 16px; border-bottom: 1px solid #eef0f4; }
tbody tr:nth-child(even) { background: #f8f9fb; }
tbody tr:hover { background: #eef3fa; }

/* Callout Boxes */
.callout { border-radius: 8px; padding: 16px 20px; margin: 16px 0; font-size: 14px; }
.callout-green { background: #e8f5e9; border-left: 4px solid #2e7d32; color: #1b5e20; }
.callout-red { background: #ffebee; border-left: 4px solid #c62828; color: #b71c1c; }
.callout-blue { background: #e3f2fd; border-left: 4px solid #1565c0; color: #0d47a1; }
.callout-amber { background: #fff3e0; border-left: 4px solid #e65100; color: #e65100; }

/* Charts */
.chart-container { text-align: center; margin: 24px 0; }
.chart-container img { max-width: 100%; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.chart-caption { font-size: 13px; color: #888; margin-top: 8px; font-style: italic; }

/* Blockquote */
blockquote { border-left: 4px solid #5b9bd5; padding: 12px 20px; margin: 14px 0; background: #f5f8fc; border-radius: 0 6px 6px 0; font-size: 14px; color: #555; }

/* Horizontal Rule */
hr { border: none; border-top: 1px solid #e0e0e0; margin: 24px 0; }

/* TOC */
.toc { background: #fff; border-radius: 12px; padding: 28px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); margin-bottom: 24px; }
.toc h2 { font-size: 18px; color: #1a2744; margin-bottom: 16px; }
.toc-list { list-style: none; padding: 0; }
.toc-list li { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.toc-list li:last-child { border: none; }
.toc-list a { color: #2a3f6b; text-decoration: none; font-size: 14px; display: flex; align-items: center; gap: 8px; transition: color 0.2s; }
.toc-list a:hover { color: #5b9bd5; }
.toc-list a i { font-size: 12px; color: #5b9bd5; width: 20px; text-align: center; }

/* Footer */
.footer { background: #1a2744; color: rgba(255,255,255,0.6); padding: 24px 40px; margin-left: 260px; font-size: 12px; line-height: 1.6; }
.footer strong { color: rgba(255,255,255,0.85); }

/* Badge */
.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.badge-green { background: #e8f5e9; color: #2e7d32; }
.badge-red { background: #ffebee; color: #c62828; }
.badge-blue { background: #e3f2fd; color: #1565c0; }
.badge-amber { background: #fff3e0; color: #e65100; }

/* Print */
@media print {
    .sticky-header, .sidebar { display: none !important; }
    .main-content { margin: 0; padding: 20px; }
    .section-body { display: block !important; }
    .section-card { break-inside: avoid; box-shadow: none; border: 1px solid #ddd; }
    .footer { margin: 0; }
    body { background: #fff; }
}

/* Responsive */
@media (max-width: 1024px) {
    .sidebar { display: none; }
    .main-content, .footer { margin-left: 0; }
    .summary-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
    .summary-grid { grid-template-columns: 1fr; }
    .main-content { padding: 16px; }
}
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

REPORT_JS = """\
function toggleSection(header) {
    const body = header.nextElementSibling;
    const isHidden = body.classList.contains('hidden');
    if (isHidden) {
        body.classList.remove('hidden');
        header.classList.remove('collapsed');
    } else {
        body.classList.add('hidden');
        header.classList.add('collapsed');
    }
}

document.querySelectorAll('.sidebar a, .toc-list a').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            const headerOffset = 70;
            const elementPosition = target.getBoundingClientRect().top;
            const offsetPosition = elementPosition + window.pageYOffset - headerOffset;
            window.scrollTo({ top: offsetPosition, behavior: 'smooth' });
        }
    });
});
"""

# ---------------------------------------------------------------------------
# HTML skeleton
# ---------------------------------------------------------------------------

HTML_SKELETON = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>{css}</style>
</head>
<body>

<!-- Sticky Header -->
{header_html}

<!-- Sidebar Navigation -->
{sidebar_html}

<!-- Main Content -->
<div class="main-content">

    <!-- Executive Summary -->
    {summary_html}

    <!-- Table of Contents -->
    {toc_html}

    <!-- Report Sections -->
    {sections_html}

</div>

<!-- Footer -->
{footer_html}

<script>{js}</script>

</body>
</html>
"""

# ---------------------------------------------------------------------------
# Step configuration
# ---------------------------------------------------------------------------

STEP_CONFIG = [
    {
        "key": "step0",
        "file": "step0_quick_triage.md",
        "icon": "fas fa-filter",
        "title": "Step 0: 快速筛选",
        "optional": True,
    },
    {
        "key": "step1",
        "file": "step1_business_analysis.md",
        "icon": "fas fa-building",
        "title": "Step 1: 业务面深入研究",
    },
    {
        "key": "step2",
        "file": "step2_competitive_moat.md",
        "icon": "fas fa-shield-halved",
        "title": "Step 2: 竞争壁垒与护城河",
    },
    {
        "key": "step3",
        "file": "step3_marginal_changes.md",
        "icon": "fas fa-arrows-spin",
        "title": "Step 3: 边际变化与预期差",
    },
    {
        "key": "step4",
        "file": "step4_quantitative_model.md",
        "icon": "fas fa-chart-line",
        "title": "Step 4: 量化基本面建模",
    },
    {
        "key": "step5",
        "file": "step5_rrr_strategy.md",
        "icon": "fas fa-scale-balanced",
        "title": "Step 5: RRR 估算与交易策略",
    },
    {
        "key": "step6",
        "file": "step6_auditing.md",
        "icon": "fas fa-clipboard-check",
        "title": "Step 6: 审计",
    },
    {
        "key": "step7",
        "file": "step7_research_director_review.md",
        "icon": "fas fa-user-tie",
        "title": "Step 7: 研究总监审核",
    },
]
