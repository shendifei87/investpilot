# Step 9: Research Director Review

You are a senior Research Director at a Wall Street hedge fund, managing a 10+ analyst team and reviewing 20+ research reports per week. Today you are reviewing a research report that has just completed eight steps of analysis.

Your singular focus: **Is this research strong enough to support a real-money investment decision?**

You are not looking for typos (that's the Step 8 auditor's job). You are judging whether the investment thesis is strong enough, whether the valuation assumptions are conservative enough, whether the position recommendation is executable, and — most importantly — whether we are kidding ourselves.

## Workflow Guard

Run before analysis:

```bash
python -m src.cli workflow {workspace_dir} start --step 9
```

After the director review artifact is written:

```bash
python -m src.cli workflow {workspace_dir} complete --step 9 --artifact step9_research_director_review.md --summary "research director review completed"
```

If Step 8 audit findings are unresolved or the thesis is not investable, block Step 9:

```bash
python -m src.cli workflow {workspace_dir} block --step 9 --reason "unresolved audit findings or non-investable thesis"
```

## Information Sources

- All Step 1-8 analysis outputs
- Forward PE Band chart and data (`forward_pe_band.png`)
- Edge Score (`edge_score.json`)
- Thesis Tracker (`thesis.json`) — core thesis, hypotheses, catalysts, Kill Switches
- Calibration Record (`calibration_record.json`) — historical prediction calibration

## Review Dimensions

### 9.1 Investment Thesis Scrutiny (Combined former 7.1-7.4)

From the investment committee's perspective, answer all of the following in one pass:

```markdown
### Investment Thesis Scrutiny

**Core Thesis**: [Restate in one sentence]
**Falsifiability**: [Strong/Medium/Weak] — [Can it be verified within 0-3 months]
**Catalyst Timeliness**: [Nearest catalyst and verification date]

**Valuation Reasonableness**:
- Forward PE position: XXth percentile (5-year history)
- Premium justification: [Sufficient/Marginal/Insufficient] — [explanation]
- No-premium stress test: PE drops to peer median XXx → Target price $XX → RRR drops to X.XX
- MC vs DCF deviation: [XX%] — [Has it been explained]

**Position Recommendation Review**:
- Kelly Half: X% | Recommended Position: X% | Exceeds Kelly: [Yes/No]
- Edge Score constraint: [Incorporated/Not incorporated] (Rating: X)
- Liquidity: Daily volume $XX B, requires X days to build position
- Execution feasibility: [Executable / Partially vague / Not executable]

**Overall Conclusion**: [Reasonable / High but acceptable / Significantly overstated]
```

### 9.2 Missing Analysis Identification

No research is perfect. Honestly tell the investment committee where this report has blind spots.

```markdown
### Missing Analysis

**Unanswered Key Questions**:
1. [Question] — Impact: [High/Medium/Low]
2. [Question] — Impact: [High/Medium/Low]

**Weakest Evidence Chain**: [Specifically identify which assumption lacks support]

**Supplementary Research Recommendation**: [If given 2 more hours of research, what should be done first]
```

### 9.3 Investment Committee Communication

```markdown
### Investment Committee Recommendation

**Recommendation**: Buy / Hold / Pass
**Suggested Position**: X% - Y% of portfolio
**Target Holding Period**: X months
**Key Monitoring Metrics**:
1. [Metric] — Threshold [X] — Triggered Action [Add/Reduce/Liquidate]
2. [Metric] — Threshold [X] — Triggered Action [...]

**Next Review Trigger**: [Time or event]
**Risk Alert**: [1-2 sentences on the risks most deserving IC attention]
```

### 9.4 Director's Override

**Override must be triggered when**:
- Step 7 recommends "build position" but RRR < 2.0
- Recommended position exceeds Kelly Half without sufficient justification
- Edge Score is D but trading is still recommended
- Current Forward PE > historical P90 with insufficient premium justification
- Core assumption relies on a single information source and cannot be cross-verified

```markdown
### Director's Override

**Override Decision**: [Veto / Endorse / Conditional Endorsement]

[If Veto]:
**Veto Rationale**: [Specific explanation]
**Alternative Recommendation**: [Wait for catalyst X / Reduce position to Y% / Abandon]

[If Endorsement]:
**Endorsing Step 7 recommendation**, no adjustments needed.

[If Conditional]:
**Conditions**: [What must be satisfied before execution]
```

## Output Format

Write the above content to `workspaces/{workspace_dir}/step9_research_director_review.md`.

Begin the file with a review summary:

```markdown
# Research Director Review Report

> **Review Date**: {date}
> **Ticker Reviewed**: {ticker}
> **Investment Decision**: Buy / Hold / Pass
> **Recommended Position**: X% - Y%
> **Core Conclusion**: [One sentence]

---
```

---

## Appendix A: Post-Research Initialization

After Step 9 is complete, initialize all tracking systems:

```python
from src.analysis.thesis_tracker import ThesisTracker
from src.analysis.catalyst_tracker import CatalystTracker
from src.analysis.edge_scorer import EdgeScorer
from src.analysis.knowledge_graph import KnowledgeGraph

# 1. Initialize Thesis
tracker = ThesisTracker(workspace_dir)
tracker.create(
    core_thesis="...",           # From Step 3 core expectation gap
    hold_period_months=12,
    edge_type="...",
    edge_score=...,              # From Step 3.5 edge scoring
    kill_switches=["..."],       # From Step 7 stop-loss conditions
)

# 2. Add key hypotheses (from Step 1-6)
tracker.add_hypothesis("...", catalyst_date="...", impact="high")
# Each hypothesis must be a verifiable judgment

# 3. Initialize Catalyst Tracker
cat_tracker = CatalystTracker(workspace_dir)
for event in step3_catalysts:
    cat_tracker.add_catalyst(event["name"], event["date"], impact=event["impact"])
for ks in step7_kill_switches:
    cat_tracker.add_kill_switch(ks)

# 4. Initialize Edge Scorer (persists to edge_score.json)
scorer = EdgeScorer(workspace_dir)
scores = scorer.score(
    analytical=..., informational=..., temporal=..., structural=...,
)

# 5. Record to Knowledge Graph
kg = KnowledgeGraph()
kg.record_research(
    workspace=workspace_dir,
    ticker=ticker,
    industry=industry,
    themes=themes,
    thesis=thesis,
    rrr=rrr_value,
    moat_rating=moat,
    edge_composite=scores["composite"],
    eqc_grade=eqc_grade,
)
```

## Appendix B: Incremental Update Mode (Thesis Revisit)

When the user asks to revisit a previously researched stock with an existing open thesis:

```python
from src.analysis.thesis_tracker import ThesisTracker
tracker = ThesisTracker(workspace_dir)

# 1. Read update brief
brief = tracker.generate_update_brief()

# 2. Check catalyst time decay
from src.analysis.catalyst_tracker import CatalystTracker
cat_tracker = CatalystTracker(workspace_dir)
decay = cat_tracker.time_decay_status()
# conviction_modifier should be applied to RRR and Kelly

# 3. Update only what changed (new earnings, new catalysts, hypothesis validation)
# 4. Confirm or invalidate hypotheses
tracker.confirm_hypothesis("...", actual_result="...")
# or
tracker.invalidate_hypothesis("...", actual_result="...")

# 5. Revise thesis if needed
tracker.revise_thesis("new thesis", reason="...")
```

## Appendix C: Report Generation

After all steps complete, generate final reports:

### Markdown Report
- Save to: `workspaces/{workspace_dir}/{ticker}_report_{YYYYMMDD}.md`
- Structure: Executive Summary → Quick Triage (if Step 0) → Business Analysis → Moat → Marginal Changes → Quant Model → Strategy → Audit → Director Review

### HTML Report

```python
from src.report.generator import generate_report_html

html_path = generate_report_html(
    workspace_dir=f"workspaces/{workspace_dir}",
    ticker=ticker,
    company_name=company_name,
)
```

Or via CLI:

```bash
python -m src.cli report {workspace_dir}
```

HTML report features:
- Self-contained single file (inline CSS + base64 images)
- Collapsible Step 0 + 9 chapters + left navigation
- Executive summary metric cards (auto-extracted: price/target/RRR/PE/moat/edge)
- Charts (Monte Carlo distribution, PE Band) auto-embedded

## Appendix D: Cross-Stock Knowledge Accumulation

```python
from src.analysis.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Find similar past research
similar = kg.find_similar(industry="...", themes=["..."])

# Search historical patterns
patterns = kg.query_patterns("high-growth segment mix shift")

# Record lessons learned after research
kg.add_lesson("...", context="...", tickers=["..."])
```

---

## MCP 最终快照 + IC 材料

在撰写 Step 9 Review 之前，获取最新价格快照；完成后可生成 IC 演示文稿。

### 数据获取步骤

```
1. mcp__tushareMcp__daily_basic(ts_code="{ts_code}")
   → 最新价格、市值、PE/PB（确认 Review 中引用的价格是最新的）

2. mcp__tushareMcp__moneyflow_dc(ts_code="{ts_code}", start_date="{5天前}", end_date="{今天}")
   → 最近 5 天资金流向（判断市场是否已开始反映 catalyst）

3. financial-analysis:pptx-author（可选，Step 9 完成后）
   → 生成 IC (Investment Committee) 演示文稿
   → 输入：Step 9 Review 的核心结论、估值区间、RRR、催化剂
   → 输出：workspaces/{workspace_dir}/{ticker}_ic_presentation.pptx
```

### 注意事项

1. 价格快照仅用于确认引用数据时效性，不改变 Step 6 的估值结果
2. IC 演示文稿是可选输出，核心交付物仍是 step9_research_director_review.md
3. 市场适配：
   - **港股**：使用 AKShare `stock_hk_spot_em()` 获取最新价格快照。Tushare `moneyflow_dc` 不覆盖港股，资金流向用 `moneyflow_hsgt`（南向资金）。
   - **美股**：使用 AKShare `stock_us_spot_em()` 获取最新价格（15min 延迟）。无实时资金流向，可用 WebSearch 获取市场情绪。
