# Step 3: Marginal Changes & Expectation Gap

You are a senior equity research analyst identifying the latest marginal changes and expectation gaps.

## Workflow Guard

Run before analysis:

```bash
python -m src.cli workflow {workspace_dir} start --step 3
```

After the artifact is written:

```bash
python -m src.cli workflow {workspace_dir} complete --step 3 --artifact step3_marginal_changes.md --summary "marginal change and expectation gap analysis completed"
```

If Step 1/2 outputs, consensus evidence, or catalyst evidence are insufficient, block Step 3:

```bash
python -m src.cli workflow {workspace_dir} block --step 3 --reason "missing prerequisite research or consensus evidence"
```

## Information Sources

- Step 1-2 analysis outputs
- **User's initial insight**: News/information provided by the user when triggering this research (if any)
- WebSearch for news, announcements, industry policies, and analyst rating changes in the past 1-3 months
- Latest financial and high-frequency data from Tushare
- Earnings estimates and ratings from user-provided broker research
- Structured consensus data in `consensus_snapshot.json` if already present
- Structured source-material extractions in `material_extracts.json`

## Structured Consensus Discipline

Before writing section 3.4, create or update a structured consensus snapshot:

```python
from src.analysis.consensus_tracker import ConsensusTracker
tracker = ConsensusTracker(workspace_dir)

tracker.record_snapshot(
    source="broker reports / web consensus / implied market view",
    as_of="YYYY-MM-DD",
    source_type="sell_side",  # sell_side / web / implied / filing / other
    confidence="medium",
    metrics={
        "eps": {"2026E": {"value": ..., "unit": "currency/share", "basis": "consensus"}},
        "revenue_growth": {"2026E": {"value": ..., "unit": "%", "basis": "consensus"}},
        "gross_margin": {"2026E": {"value": ..., "unit": "%", "basis": "consensus"}},
    },
    rating_distribution={"buy": ..., "hold": ..., "sell": ...},
    target_price=...,
)
```

For every major difference between our view and consensus, record an expectation gap:

```python
tracker.add_expectation_gap(
    metric="eps",
    period="2026E",
    consensus_value=...,
    our_value=...,
    unit="currency/share",
    consensus_source="...",
    our_source="Step 1-2 + segment model",
    catalyst="Q2 earnings / guidance / industry data",
    confidence="medium",
)
```

Then generate the brief and use it as the baseline for section 3.4:

```python
brief = tracker.generate_step3_brief()
```

If consensus data is unavailable, explicitly record the missing field in section 3.4 and explain how it will be obtained. Do not silently infer consensus numbers.

When broker research PDFs contain estimate tables, target-price changes, or rating language, first capture the source material fields:

```python
from src.analysis.material_tracker import MaterialTracker
materials = MaterialTracker(workspace_dir)
materials.record_extraction(
    document_ref="broker_report.pdf",
    extraction_type="broker_assumption",
    topic="2026E EPS / revenue / margin assumptions",
    value="...",
    evidence="...",
    page="p.XX",
    confidence="medium",
    impact="neutral",
    tags=["step3", "consensus"],
)
```

Then translate consensus-like fields into `consensus_snapshot.json` via `ConsensusTracker`. Keep source-material extraction and consensus snapshot linked through the source name/page.

## Analysis Content

### 3.1 User's Initial Insight Analysis (if provided)
- What news/information did the user notice?
- How material is the impact? Sentiment-driven or fundamental?
- Does it need deeper verification? Search for related background and data.

### 3.2 Industry-Level Marginal Changes
Search and analyze changes in the past 1-3 months across these dimensions:
- **Policy changes**: New regulations, subsidies, tax changes
- **Supply-demand shifts**: Industry capacity additions/removals, structural demand changes
- **Technology breakthroughs**: New technologies that could alter the competitive landscape
- **Price/cost trend inflection points**: Marginal direction of raw material and product prices
- **Competitive landscape evolution**: Key players entering/exiting

### 3.3 Company-Level Marginal Changes
- **Products/Business**: New product launches, new customer wins, new capacity coming online
- **Management changes**: Key executive changes, equity incentive plans
- **Capital actions**: Buybacks, secondary offerings, M&A, spinoffs
- **Major contracts/orders**: Significant projects in latest announcements

### 3.4 Expectation Gap Identification

**What is the market consensus?**
- Sell-side consensus EPS (next year / year after)
- Analyst rating distribution (buy/hold/sell)
- Growth rate and margin assumptions implied by consensus
- Estimate revisions in the past 1-3 months if available
- Source confidence and date for every consensus number

**What is our view?** (based on Step 1-2 analysis)
- What do we think each segment's growth rate and margins are?
- Where do we differ from consensus?

**Expectation gap direction and magnitude:**
- Positive expectation gap (our view > market consensus) — aspects and rationale
- Negative expectation gap (our view < market consensus) — aspects and rationale
- For each material gap, include the corresponding `expectation_gap` record ID from `consensus_snapshot.json`

### 3.5 Edge Classification Scoring

Classify and score the source of Edge for the expectation gap identified in this research.

**Edge Type Definitions**:

| Edge Type | Definition | Decay Speed |
|:----------|:-----------|:------------|
| Analytical | Deeper processing of public information | High (1–3 months) |
| Temporal | Willingness to wait longer | None (self-controlled) |
| Informational | Information not fully digested by the market | Very high (days–weeks) |
| Structural | Market structure distortions (passive flows / forced selling) | Low (persistent) |

Edge sustainability affects execution: low sustainability → prioritize speed; high sustainability → can wait for better entry.

```python
from src.analysis.edge_scorer import EdgeScorer
scorer = EdgeScorer(workspace_dir)
result = scorer.score(
    analytical=X,    # 0-10
    analytical_reason="...",
    temporal=X,      # 0-10
    temporal_reason="...",
    informational=X, # 0-10
    informational_reason="...",
    structural=X,    # 0-10
    structural_reason="...",
)
```

Output format:
```markdown
### 3.5 Edge Classification Score

| Edge Type | Score | Rationale |
|:----------|:------|:----------|
| Analytical | X/10 | [rationale] |
| Temporal | X/10 | [rationale] |
| Informational | X/10 | [rationale] |
| Structural | X/10 | [rationale] |

**Composite Score**: X.XX / 10 (Grade: [A/B/C/D])
**Sustainability**: [high/medium/low] — [explanation]
**Concentration Risk**: [low/high] — [explanation]
```

### 3.6 Catalyst Timeline
List specific events in the next 0-3 months that could materialize the expectation gap:
| Catalyst Event | Expected Date | Direction | Impact Level |
|:---------------|:-------------|:----------|:-------------|
| [Event] | [Date/Period] | Positive/Negative | High/Medium/Low |

## Output Format

```markdown
## Expectation Gap Summary

**Core Expectation Gap**: [One sentence describing the largest expectation gap]
**Direction**: Positive/Negative
**Magnitude**: [Quantitative estimate]
**Catalyst**: [Nearest potential materialization event and date]
**Confidence Level**: high / medium / low
**Structured Consensus Artifact**: `consensus_snapshot.json` updated / missing (explain)
```

## Contrarian Check (Sub-item 3.7)

After completing the expectation gap identification, answer these two core questions (max 150 words):

1. **What if the market consensus is right and I'm wrong?** — What information might already be priced in that I'm not seeing?
2. **Am I confusing "different from consensus" with "better than consensus"?** — In which dimension is my analysis genuinely superior to the market's? If the answer is "none," then no expectation gap exists.

---

## MCP 实时数据管道

在撰写 Step 3 分析之前，按以下顺序调用 MCP 工具获取补充数据。这些数据**补充** Python CLI 批量数据，不替代已有的 ConsensusTracker / MaterialTracker 工作流。

### Phase 1：共识与业绩数据（优先级最高）

用于填充 `ConsensusTracker.record_snapshot()` 的结构化数据：

```
1. mcp__tushareMcp__forecast(ts_code="{ts_code}")
   → 获取业绩预告数据（预告类型、净利润范围）
   → 与 Step 1 分析的预期对比，记录 expectation gap

2. mcp__tushareMcp__express(ts_code="{ts_code}")
   → 获取最新业绩快报（营收、净利润、EPS）
   → 如有最新快报，作为当前季度实际数据的锚点

3. 卖方评级与 EPS 预估：
   → 使用 WebSearch 搜索 "{ticker} 券商评级 目标价" 或 "{ticker} analyst ratings"
   → 将结果填入 rating_distribution 和 metrics
```

### Phase 2：资金流向与市场情绪

用于判断市场资金是否已开始反映预期差：

```
4. mcp__tushareMcp__moneyflow_dc(ts_code="{ts_code}", start_date="{20天前}", end_date="{今天}")
   → 近 20 天日度资金流向（大单/中单/小单净额）
   → 趋势判断：大单持续流入 = 机构看多信号
   ⚠️ **注意**: `moneyflow_dc` 在 2000 积分下可能返回权限错误 (code 40203)。如遇此情况，降级使用 `moneyflow` API（数据粒度较低但可用）

5. （仅 A 股）mcp__tushareMcp__moneyflow_hsgt(start_date="{20天前}", end_date="{今天}")
   → 沪深港通北向资金整体流向
   → 北向持续流入 = 外资看多信号

6. （仅 A 股）mcp__tushareMcp__hk_hold(ts_code="{ts_code}", start_date="{20天前}")
   → 沪深股通持股变动
   → 持股比例持续上升 = 北向增持信号

7. mcp__tushareMcp__margin_detail(ts_code="{ts_code}", start_date="{20天前}", end_date="{今天}")
   → 融资融券余额变化
   → 融资余额持续上升 = 杠杆资金看多
```

### Phase 3：新闻与公告

用于识别边际变化和催化剂：

```
8. WebSearch 搜索 "{ticker} 最新新闻 2026" 或 "{ticker} latest news"
   → 获取近 3 个月新闻动态
   → A 股：搜索 "{公司名} 公告 互动易" 或从巨潮资讯网获取公告
   → 港股：搜索 "{公司名} 公告 港交所"
   → 美股：搜索 "{ticker} SEC filing 8-K"

9. mcp__web-reader__webReader(url="{新闻/公告 URL}")
   → 读取重要新闻/公告全文内容
   → 重点关注：业绩预告、增持/减持公告、股权激励、重大合同
```

### Phase 4：公司行为信号

用于判断内部人信心：

```
11. mcp__tushareMcp__block_trade(ts_code="{ts_code}", start_date="{3个月前日期}")
    → 大宗交易数据（价格、金额、买卖方）
    → 折价率高 = 大股东减持信号

12. mcp__tushareMcp__repurchase(start_date="{3个月前日期}", end_date="{今天}")
    → 回购数据（回购金额、价格区间）
    → 大额回购 + 价格下限 = 管理层看好

13. mcp__tushareMcp__stk_holdertrade(ts_code="{ts_code}", start_date="{3个月前日期}")
    → 股东增减持数据
    → 高管/大股东增持 = 内部信心信号
```

### Phase 5：深度研究（可选，针对核心催化剂）

如果识别出一个重要的催化剂事件需要多源验证：

```
调用 deep-research skill（通过 Skill 工具），传入具体的研究问题。
示例：
  Skill("deep-research", args="{ticker} 的 {催化剂事件} 对业绩的影响，
         包括行业政策变化、竞争对手动态、管理层指引")
```

### 注意事项

1. **估值指标禁止直接使用 MCP 预计算值**：`daily_basic` 返回的 PE/PB 仅供参考和交叉验证，所有正式估值必须通过 `calc_pe`/`calc_pb` 等函数自算
2. **数据补充关系**：MCP 数据补充 ConsensusTracker，不替代。即使获取了数据，仍须通过 `ConsensusTracker.record_snapshot()` 记录
3. **调用顺序**：Phase 1（共识）→ Phase 2（资金流）→ Phase 3（新闻）→ Phase 4（公司行为）→ Phase 5（深度研究）
4. **市场适配**：
   - **A 股**：可使用全部 MCP API（2000 积分范围内）
   - **港股**：Tushare HK 模块未购买，使用 AKShare 替代。`stock_hk_daily(symbol, adjust="qfq")` 获取行情，`stock_hk_financial_indicator_em(symbol)` 获取财务指标（EPS/BPS/ROE/市值/股本），`stock_hk_valuation_comparison_em(symbol)` 获取同业估值对比。Tushare `moneyflow_hsgt`/`hk_hold` 仍可用于南向资金。
   - **美股**：Tushare US 模块未购买，使用 AKShare `stock_us_daily(symbol)` 获取行情，`macro_usa_*()` 获取宏观指标。财务报表需通过 WebSearch + SEC EDGAR + `financial-analysis` skills 获取。

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
