# Step 2: Competitive Moat Analysis

You are a senior equity research analyst performing competitive moat analysis.

## Workflow Guard

Run before analysis:

```bash
python -m src.cli workflow {workspace_dir} start --step 2
```

After the artifact is written:

```bash
python -m src.cli workflow {workspace_dir} complete --step 2 --artifact step2_competitive_moat.md --summary "competitive moat analysis + comps analysis completed"
```

If Step 1 is incomplete or moat evidence is insufficient for a conclusion, block Step 2:

```bash
python -m src.cli workflow {workspace_dir} block --step 2 --reason "missing Step 1 output or moat evidence"
```

## Information Sources

- Step 1 analysis outputs (analysis files in the workspace)
- Industry data from `python -m src.cli fetch {ticker}`
- WebSearch for competitor information, industry landscape, latest competitive dynamics
- Industry comparison analysis from user-provided broker research
- Structured source-material brief from `material_extracts.json`

Before writing Step 2, load source-material extractions:

```python
from src.analysis.material_tracker import MaterialTracker
materials = MaterialTracker(workspace_dir)
brief = materials.generate_research_brief(focus="all")
```

Step 2 should especially use:
- `moat_evidence`: pricing power, switching cost, patent/license, scale, or customer-stickiness evidence
- `risk_factor`: disclosed forces that may erode the moat
- `broker_assumption`: peer comparison and competitive landscape assumptions from broker reports
- `thesis_conflict`: source-material evidence that contradicts the moat thesis

If broker reports contain competitive claims, record them before using them:

```python
materials.record_extraction(
    document_ref="broker_report.pdf",
    extraction_type="moat_evidence",
    topic="Switching cost / pricing power / scale advantage",
    value="...",
    evidence="...",
    page="p.XX",
    confidence="medium",
    impact="positive",
    tags=["step2", "moat"],
)
```

## Analysis Content

### 2.1 Moat Type Identification
Evaluate each moat type below for existence and strength:
- **Network Effects**: Does user growth enhance product value? Any specific data to prove it?
- **Intangible Assets**: Brand premium (can they raise prices? by how much?), patent/license barriers (what specifically? expiration dates?)
- **Cost Advantage**: Scale benefits / process advantages / geographic advantages — which metrics demonstrate this?
- **Switching Costs**: Actual cost to customers of changing suppliers (money/time/risk) — any case studies?
- **Scale Effects**: Advantages from market share leadership — are they expanding?

**Overall Assessment**: Single barrier or compound moat? What is the dominant barrier?

### 2.2 Moat Trend Assessment
- Is the current barrier widening / stable / narrowing? Provide judgment and evidence.
- Is technological change disrupting existing barriers? What specific technology?
- How do industry dynamics (consolidation / fragmentation / new entrants) affect the barrier direction?

### 2.3 Competitive Landscape Overview
- Direct competitor list (at least 3), with respective market shares and trends
- Is the industry consolidating or fragmenting? CR3/CR5 trends
- Are entry barriers rising or falling? Why?
- Potential disruptors or substitute threats

### 2.3.1 Comparable Company Analysis (Mandatory Skill)

After completing the qualitative competitive landscape above, **must** invoke `comps-analysis` skill to produce a structured peer valuation table:

```
Skill("financial-analysis:comps-analysis", args="{ticker} 可比公司分析，同业：{peer1}, {peer2}, {peer3}")
```

**Output artifacts** (saved to workspace):
- `step2_comps_analysis.xlsx` — professional comps Excel with:
  - Valuation multiples: PE, PB, PS, EV/EBITDA (all self-calculated per valuation discipline)
  - Statistical benchmarks: Max / 75th / Median / 25th / Min for each metric
  - Growth & profitability metrics: Revenue growth, EBITDA margin, Net margin, ROE, ROIC
  - Industry-specific metrics where relevant (e.g., SaaS: ARR per employee; Banks: NPL ratio; Retail: same-store sales)
  - Source citations with hyperlinks to SEC filings / annual reports
- `step2_comps_summary.md` — 3-5 sentence summary of relative positioning

**Integration rules**:
1. Peer list from MCP 同业识别 (section above) feeds into comps-analysis as the peer universe
2. All multiples in the comps Excel must be self-calculated (`calc_pe`, `calc_pb`, etc.) — tag every cell `source: calculated`
3. Statistical benchmarks (median, quartiles) set the **valuation corridor** that flows directly into:
   - Step 2 "Moat → Valuation Constraint" PE Reasonable Ceiling
   - Step 4 assumption ranges
   - Step 5 valuation sheet peer column
4. If the company trades at a premium to median, the premium must be justified by moat rating (2.1) or growth differential (2.5) — otherwise flag as **unjustified premium risk**
5. Market adaptation:
   - **A-share**: Tushare MCP provides all financial data; comps-analysis uses it as input
   - **HK**: AKShare `stock_hk_valuation_comparison_em()` + `stock_hk_growth_comparison_em()` as data source; comps-analysis formats the output
   - **US**: WebSearch + SEC EDGAR as data source; comps-analysis pulls and structures the data

### 2.4 Pricing Power Verification
- Has the company been able to raise prices above inflation over the past 3-5 years? (Specific price change data)
- Have margins remained stable during economic downturns? (Prove with historical data)
- Bargaining power vs. upstream suppliers and downstream customers — any substantive evidence?

### 2.5 Capital Return Quality
- ROIC historical trend (at least 3 years) — consistently above WACC?
- vs. peers — consistently outperforming competitors?
- Return on incremental invested capital (ROIIC) — improving or declining?

## Output Format

For each sub-item, **conclusion first, evidence follows** — no boilerplate:

```markdown
### [Sub-item Title]

**Conclusion**: [widening/stable/narrowing — one sentence]

**Evidence**:
1. [Specific data + brief evidence]
2. [Specific data + brief evidence]
```

**Required artifacts** (all saved to workspace):
1. `step2_competitive_moat.md` — moat analysis narrative (2.1–2.6)
2. `step2_comps_analysis.xlsx` — from `comps-analysis` skill (2.3.1)
3. `step2_comps_summary.md` — relative positioning summary (2.3.1)

**Final Moat Rating**:
- Wide Moat / Narrow Moat / No Moat
- Trend: Widening / Stable / Narrowing
- Core rationale (max 3 sentences)

### Moat → Valuation Constraint (passed directly to Step 4)

After the moat rating, output the following valuation constraint parameters (replaces former Section 2.7):

```markdown
### Moat → Valuation Constraint

**Rating**: [Wide/Narrow/None]  **Trend**: [Widening/Stable/Narrowing]
**PE Reasonable Ceiling**: [XXx] (based on peer comparison + historical median)
**Premium Support Factors**: [1-2 factors]
**Premium Risk**: [If moat is downgraded, PE could contract to XXx]
```

### Confidence & Data Source Summary

After completing 2.1-2.5, output a summary table:

```markdown
### Confidence & Data Source Summary

| Sub-item | Confidence | Key Data Source | Key Risk |
|:---------|:----------:|:---------------|:---------|
| 2.1 Moat Types | high | [source] | [risk] |
| 2.2 Trend Assessment | medium | [source] | [risk] |
| ... | ... | ... | ... |
```

Also cite the key `material_extracts.json` document/extraction IDs behind the moat rating and valuation constraint.

## Contrarian Check (Sub-item 2.6)

After completing the moat rating, answer these two core questions (max 150 words):

1. **If the moat is overestimated, where am I most likely wrong?** — What forces are eroding the barrier? Cite at least one specific piece of evidence from 2.1-2.5
2. **If the moat drops one level, what is the valuation impact?** — Must provide a quantitative estimate (e.g., "Narrow → None means PE drops from 60x to 35-40x, stock price falls 30-40%")

---

## MCP 同业识别

在撰写 Step 2 分析之前，调用以下 MCP 工具自动识别同业并获取行业数据。

### 数据获取步骤

```
1. mcp__tushareMcp__index_member_all(ts_code="{ts_code}")
   → 获取目标公司所属申万行业分类（一级/二级/三级）
   → 确定 l3_code 后，获取同行业全部成分股

2. mcp__tushareMcp__sw_daily(ts_code="{行业指数代码}")
   → 行业指数行情（PE/PB/成交量）
   → 用于行业估值中枢判断

3. mcp__tushareMcp__fina_indicator(ts_code="{peer1,peer2,peer3}")
   → 同业 ROE、ROIC、毛利率、净利率等指标
   → 逐个公司调用（每次一个 ts_code）

4. mcp__tushareMcp__daily_basic(ts_code="{peer1,peer2,peer3}")
   → 同业市值、PE/PB（仅用于 sanity check，正式估值须自算）
   → 逐个公司调用
```

### 注意事项

1. 申万行业分类仅作为同业识别起点，需结合业务相似性手动筛选最终同业名单
2. 同业 PE/PB 从 `daily_basic` 获取后，仅用于 Step 4 的 sanity check，正式估值仍须通过 `calc_pe`/`calc_pb` 自算
3. 市场适配：
   - **港股**：使用 AKShare `stock_hk_valuation_comparison_em(symbol)` 获取同业估值对比（PE/PB/PS+排名），`stock_hk_growth_comparison_em(symbol)` 获取成长性对比。Tushare `moneyflow_hsgt`/`hk_hold` 仍可用于南向资金流。
   - **美股**：使用 AKShare `stock_us_daily(symbol)` 获取价格数据。同业估值需通过 WebSearch + `financial-analysis:comps-analysis` skill 从 SEC EDGAR 获取财务数据。
