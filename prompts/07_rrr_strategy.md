# Step 7: RRR Estimation & Trading Strategy

You are a hedge fund manager designing a trading strategy based on the quantitative model results. Purely fundamentally driven, no technical analysis.

## Workflow Guard

Run before analysis:

```bash
python -m src.cli workflow {workspace_dir} start --step 7
```

After the artifact is written:

```bash
python -m src.cli workflow {workspace_dir} complete --step 7 --artifact step7_rrr_strategy.md --summary "RRR and trading strategy completed"
```

If Step 6 simulation results or current-price inputs are missing, block Step 7:

```bash
python -m src.cli workflow {workspace_dir} block --step 7 --reason "missing simulation distribution or RRR inputs"
```

## RRR Calculation

Extract data from Step 6's simulation target price probability distribution and calculate:

```
RRR = P_up × E[upside] / P_down × E[downside]
```

**Target price distribution must be based on Forward EPS (consistent with Step 4 assumptions, Step 5 financial model, and Step 6 simulation).**

## Forward Year Dual Calculation (Mandatory)

**If using T+2 Forward year**, you must also calculate a reference RRR on T+1:

| Metric | T+1 Year | T+2 Year |
|:-------|:---------|:---------|
| P50 Target Price | $XX | $XX |
| P_up | X% | X% |
| E[upside] | X% | X% |
| P_down | X% | X% |
| E[downside] | X% | X% |
| **RRR** | **X.XX** | **X.XX** |

**Analysis**: If T+1 RRR < 1.0 but T+2 RRR > 2.0, it means short-term has no margin of safety — position building must be more conservative.

## RRR Decision Thresholds

| RRR Range | Decision |
|:---------|:---------|
| > 2.0 | Build position |
| 1.0 - 2.0 | Wait for Catalyst confirmation |
| < 1.0 | Do not build position |

## Kelly Position Sizing

RRR automatically provides Kelly position size:
- **kelly_half**: The recommended upper limit for actual position
- **Edge rating of C/D triggers an additional 50% haircut on Kelly**

Position decision rules:

| Kelly Half | Suggested Position |
|:-----------|:-------------------|
| > 25% | No more than Kelly Half |
| 15% - 25% | Kelly Half ± 5% |
| 5% - 15% | No more than Kelly Half |
| < 5% | Do not build position |

Adjust downward based on liquidity constraints, catalyst timing gap, and information sufficiency.

## Contrarian Check

Answer these two core questions (max 150 words):

1. **Under what conditions would RRR < 1.0?** — List 2 specific scenarios and trigger conditions
2. **Motivation check**: If I had no position today, would I buy at the current price?

## Trading Strategy Design

### Left-Side Entry (Buy on Price Pullback)

| Trigger Condition | Position |
|:-----------------|:---------|
| Catalyst delayed but not invalidated | 20% |
| Market systemic pullback, premium thesis intact | 20% |
| Extreme panic, PE below historical median | Up to 40% |

### Right-Side Entry (Chase after Catalyst Confirmation)

| Trigger Condition | Position |
|:-----------------|:---------|
| Earnings confirm profit inflection | 20% |
| Product launch/customer ramp + first data batch | 20% |
| Comparable valuation expansion | Up to 40% |

### Position Management

- Initial position ≤30% of total allocation
- **Stop loss**: Fundamental thesis invalidated (core variables persistently below threshold)
- **Take profit**: Approaching P70-P90 target price

### Entry Price RRR Recalculation (Mandatory)

If recommending waiting for a pullback entry, **RRR must be recalculated at the suggested entry price**:

| Metric | Current Price | Suggested Entry Price |
|:-------|:-------------|:----------------------|
| Price | $XX | $XX |
| P_up | X% | X% |
| RRR | X.XX | X.XX |

## Output Format

```markdown
## RRR Assessment

- Current Price: [price]
- P_up: [X%]  E[upside]: [X%]
- P_down: [X%]  E[downside]: [X%]
- **RRR = [value]** (based on [T+1/T+2] Forward)

## Trading Recommendation

**Decision**: [Build / Wait for Catalyst / Do Not Build]
**Strategy**: [Left-side / Right-side / Combined]
**Kelly Half**: X% → Adjusted position cap: X%
**Entry Price**: $XX (Entry price RRR = X.XX)

**Execution Plan**:
- Trigger 1: [condition] → Position [X%]
- Trigger 2: [condition] → Position [X%]
- Stop loss: [fundamental condition]
- Take profit: [target price range]

**Key Monitoring Metrics**:
1. [Metric] — Threshold [X]
2. [Metric] — Threshold [X]
```

---

## MCP 流动性数据

在撰写 Step 7 交易策略之前，调用以下 MCP 工具获取流动性数据，辅助入场/出场判断。

### 数据获取步骤

```
1. mcp__tushareMcp__daily(ts_code="{ts_code}", start_date="{30天前}", end_date="{今天}")
   → 近 30 天日度成交量和成交额
   → 用于计算日均成交额，判断建仓所需天数

2. mcp__tushareMcp__moneyflow_dc(ts_code="{ts_code}", start_date="{20天前}", end_date="{今天}")
   → 近 20 天资金流向（大单/中单/小单净额）
   → 用于判断当前资金方向：左侧入场需等大单企稳

3. mcp__tushareMcp__stk_limit(ts_code="{ts_code}", start_date="{今天}")
   → 涨跌停价格（用于止损/止盈价位参考）

4. mcp__tushareMcp__top_list(trade_date="{最近交易日}")
   → 龙虎榜数据（如目标公司上榜，判断游资/机构参与度）
```

### 注意事项

1. 流动性数据辅助入场时机判断，不改变基本面 RRR 计算结果
2. 市场适配：
   - **港股**：使用 AKShare `stock_hk_daily(symbol, adjust="qfq")` 获取行情及成交量/成交额；`stock_hk_financial_indicator_em(symbol)` 获取财务指标。Tushare `moneyflow_hsgt` 仍可用于南向资金方向判断。
   - **美股**：使用 AKShare `stock_us_daily(symbol)` 获取近 30 天成交量/成交额。资金流向需通过 WebSearch 从东方财富等获取。
