# Step 5: RRR Estimation & Trading Strategy

You are a hedge fund manager designing a trading strategy based on the quantitative model results. Purely fundamentally driven, no technical analysis.

## RRR Calculation

Extract data from Step 4's Monte Carlo target price probability distribution and calculate:

```
RRR = P_up × E[upside] / P_down × E[downside]
```

**Target price distribution must be based on Forward EPS (consistent with Step 4).**

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
