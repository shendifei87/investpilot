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

### 2.3.1 Comparable Company Analysis (Two-Step CLI Workflow)

After completing the qualitative competitive landscape above, produce a structured peer valuation table using the **two-step CLI workflow**:

#### Step A: Prepare `step2_comps_data.json`

Manually create `step2_comps_data.json` in the workspace with peer financial data. Schema:

```json
{
  "version": 1,
  "date": "YYYY-MM-DD",
  "benchmark_year": "FY2026E",
  "benchmark_label": "FY2026E Forward PE",
  "peer_selection": {
    "included": ["ticker1", "ticker2"],
    "excluded": [{"name": "Company", "reason": "Private, no data"}],
    "criteria": "Selection rationale"
  },
  "peers": [
    {
      "ticker": "09992.HK",
      "name": "Pop Mart",
      "name_zh": "泡泡玛特",
      "market": "HKEX",
      "ccy": "HKD",
      "is_target": true,
      "price": 170.5,
      "price_date": "YYYY-MM-DD",
      "mcap_bn_usd": 29.1,
      "fy_end": "Dec 31",
      "financials": {
        "FY2025A": {
          "revenue_bn": 37.12, "revenue_ccy": "RMB", "rev_yoy": 184.7,
          "eps": 10.43, "gm_pct": 72.1, "nm_pct": 34.4, "roe_pct": 77.5
        },
        "FY2026E": {
          "revenue_bn": 43.37, "rev_yoy": 16.8,
          "eps": 10.86, "source": "Yahoo Finance", "as_of": "2026-06-09"
        },
        "FY2027E": {
          "revenue_bn": 50.71, "rev_yoy": 16.9,
          "eps": 13.30, "source": "Yahoo Finance", "as_of": "2026-06-09"
        }
      },
      "notes": "EPS calculation methodology"
    }
  ]
}
```

**Data discipline**:
- All EPS values must be from identifiable sources (Yahoo Finance consensus, StockAnalysis.com, Bloomberg, etc.)
- Record `as_of` date for every forward estimate — enables automatic staleness detection
- Exclude private companies with no public financial data
- Use standardized 3-year view: **FY2025A (actual) → FY2026E (forward) → FY2027E (forward)**

#### Step B: Generate xlsx + summary

```bash
python -m src.cli comps {workspace}
```

**Output artifacts** (auto-generated):
- `step2_comps_analysis.xlsx` — professional comps Excel with:
  - Self-calculated PE ratios (Current Price ÷ EPS, tagged `source: calculated`)
  - Revenue, margins, EPS across FY2025A/FY2026E/FY2027E
  - Target premium analysis vs peer median
  - Data freshness indicators (🟢 ≤90d, 🟡 91-180d, 🔴 >180d)
  - Raw Data sheet with per-metric source and date tracking
- `step2_comps_summary.md` — markdown summary with PE tables, revenue growth, margins, freshness

**Integration rules**:
1. Peer list from competitive landscape (2.3) feeds into `step2_comps_data.json` as the peer universe
2. All PE ratios are self-calculated by the CLI using `calc_pe()` — no manual PE entry
3. Statistical benchmarks (peer median/mean) set the **valuation corridor** that flows into:
   - Step 2 "Moat → Valuation Constraint" (PE or PB depending on mode)
   - Step 4 assumption ranges
   - Step 5 valuation sheet peer column
4. If the company trades at a premium to median, the premium must be justified by moat rating (2.1) or growth differential (2.5) — otherwise flag as **unjustified premium risk**
5. Data staleness: Mattel/Funko estimates from 2025 are automatically flagged 🔴 — refresh before relying on them
6. Market adaptation for data gathering:
   - **A-share**: Tushare MCP `daily_basic`, `fina_indicator`, `income` for financial data
   - **HK**: AKShare `stock_hk_financial_indicator_em()` + Yahoo Finance for consensus EPS
   - **US**: WebSearch + SEC EDGAR for financial statements; Yahoo Finance/StockAnalysis.com for consensus

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

#### Standard Mode (PE-primary, default)

```markdown
### Moat → Valuation Constraint

**Rating**: [Wide/Narrow/None]  **Trend**: [Widening/Stable/Narrowing]
**PE Reasonable Ceiling**: [XXx] (based on peer comparison + historical median)
**Premium Support Factors**: [1-2 factors]
**Premium Risk**: [If moat is downgraded, PE could contract to XXx]
```

#### Bank Mode (PB-primary, when valuation_primary == "PB")

For banks, PB is the primary valuation metric. Use the PB-ROE framework instead:

```markdown
### Moat → Valuation Constraint (🏦 Bank PB Mode)

**Rating**: [Wide/Narrow/None]  **Trend**: [Widening/Stable/Narrowing]
**PB Reasonable Ceiling**: [XXx] (based on PB-ROE regression + peer comparison)
**PB-ROE Regression**: PB = [a] + [b] × ROE (R² = [X.XX])
**PB Valuation Corridor**:
- P10 (Bear): [X.XXx] ([price]元) — ROE deterioration + NPL stress
- P50 (Base): [X.XXx] ([price]元) — ROE stable at current level
- P90 (Bull): [X.XXx] ([price]元) — ROE expansion + NPL improvement
**DDM Auxiliary**: [cost of equity X.X%] → implied PB [X.XXx] (cross-check)

**Key PB Driver**: Sustainable ROE (not growth). ROE [X.XX]% → justified PB [X.XX]x.
**PB vs ROE Gap**: Actual PB [X.XX]x vs ROE-implied PB [X.XX]x → [over/under/fair]valued by [X]%
**Premium Risk**: If moat downgrade / ROE < [7% kill switch], PB → [X.XX-X.XX]x, stock falls [X-X]%
```

**Bank-specific guidance for PB-ROE**:
- PB is driven by sustainable ROE, not growth rate (unlike PE for growth stocks)
- Key PB levers: NIM (revenue), credit cost (risk), operating cost ratio (efficiency)
- PB corridor should incorporate NPL sensitivity (kill switch: NPL > 1.1% for PSBC)
- DDM as cross-check: gordon growth model with dividend yield + sustainable growth
- If `step2_comps_data.json` has `valuation_primary: "PB"`, the comps CLI automatically uses PB mode

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

### 🚨 MCP 参数限制硬规则（防 Context 爆炸）

以下 MCP 工具**必须**携带日期参数，否则返回全历史数据（数百万字符）导致 context 爆炸：
- `daily_basic`: 必须传 `trade_date` 或 `start_date`+`end_date`
- `fina_indicator`: 必须传 `start_date`+`end_date` 或 `period`
- `income` / `balancesheet` / `cashflow`: 必须传 `start_date`+`end_date` 或 `period`
- `forecast` / `express`: 必须传 `start_date`+`end_date` 或 `period`
- `daily` / `adj_factor`: 必须传 `start_date`+`end_date` 或 `trade_date`

**推荐参数范围**：仅取最近 4 个季度（或最近 1 年）的数据。示例：
```
daily_basic(ts_code="600036.SH", start_date="20250101", end_date="20260612")
fina_indicator(ts_code="600036.SH", start_date="20240101", end_date="20260612")
```

**违反此规则的调用 = 硬错误，必须立即修正。**
