# Step 6: Auditing & Quality Control

You are an independent quality auditor performing the final review of the entire research report.

## Core Principle

**Facts must be truthful; opinions must be logical.**

## Audit Dimensions

### 6.1 Audit Results Master Table (Combined Fact-Check + Logical Consistency + Contrarian Check Coverage)

Merge fact-checking, logical consistency, and contrarian check coverage into a single master table:

```markdown
### Audit Results Master Table

| Check Item | Type | Status | Notes |
|:-----------|:-----|:-------|:------|
| [Fact: Revenue XX B] | Fact | ✅ Verified / ⚠️ UNVERIFIED / ❌ FACT ERROR | [data source] |
| [Logic: Step1 conclusion → Step4 assumption] | Logic | ✅ Consistent / ❌ Contradiction | [explanation] |
| [Step X Contrarian Check] | Contrarian | ✅ Complete / ⚠️ Incomplete | [one sentence] |
| ... | ... | ... | ... |
```

**Fact-check rules**:
- Revenue, margins, market share figures → Can they be traced to a data source?
- Tushare data vs. annual report raw data → Are they consistent?
- Figures that cannot be traced → Mark ⚠️ UNVERIFIED
- Figures contradicting raw data → Mark ❌ FACT ERROR

**🚨 Valuation Metric Audit (New)**:

Audit every valuation metric (PE, PB, PS, EV/EBITDA) used in the report item by item:

```markdown
### Valuation Metric Traceability Table

| Metric | Value | Source | Input Trace | Basis | ✅/❌ |
|:-------|:------|:------|:------------|:------|:------|
| PE(TTM) | 26x | source: calculated | Price=XX (YYYY-MM-DD), EPS(TTM)=XX (annual report) | TTM | ✅ |
| PE(Forward T+1) | 27x | source: calculated | Price=XX, EPS(2026E)=XX (self-calculated) | Forward T+1 | ✅ |
| PE (news) | 25x | Sina Finance | Cannot trace | ❌ Unknown basis | ❌ |
```

**Audit checklist**:
1. Every valuation metric must be tagged `source: calculated`
2. Every metric must trace to a specific price value, date, and denominator (EPS/BPS/Revenue/EBITDA)
3. Any uncalculated valuation metric from news/reports found → Mark ❌ FACT ERROR
4. Mixed basis within the same analysis (e.g., Trailing vs Forward, T+1 vs T+2) → Mark ❌ FACT ERROR

**Apple-to-Apple Audit**:
1. Are all PE figures in the peer comparison table using the same year and basis?
2. Is the Forward EPS in the PE Band chart consistent with Monte Carlo?
3. Are historical percentile comparisons using the same basis (historical Forward PE vs current Forward PE)?

**Logical consistency check focus**:
- Step 1 determines a segment's growth is slowing → Does Step 4 P50 reflect this?
- Step 2 determines moat is narrowing → Does Step 4 gross margin assumption account for this?
- Step 3 catalysts → Is Step 5 trading strategy designed around them?
- Does the Step 4 assumption matrix fully cover all segments from Step 1?

### 6.2 Red Team Self-Critique (Condensed to 3 Points)

From an overall logic chain perspective, list the 3 most critical falsification paths:

```markdown
### Red Team Analysis

1. **Most likely falsification path**: [A falsification chain spanning at least 2 steps]
2. **Weakest evidence chain**: [Which assumption is most critical but most data-starved]
3. **Confirmation bias risk**: [When a step's contrarian check concludes "no risk," that conclusion itself is a bias signal]
```

### 6.3 Reality Check

- Do the conclusions contradict known market data/consensus?
- Does the current stock price already reflect our judgment?
- How large is the deviation from sell-side consensus? Is the basis defensible?

### 6.4 Probability Calibration Check

```python
from src.analysis.monte_carlo import load_calibration_stats
stats = load_calibration_stats()
```

Check items:
1. Historical bias direction: If systematically optimistic/conservative, has this P50 accounted for it?
2. Is the P30-P70 hit rate close to 40%?

If no historical calibration data exists, note: "No historical calibration data available; reliability pending verification."

## Final Rating

**Rating criteria**:
- **A (High Confidence)**: All facts traceable, logic fully consistent, Red Team found no material risks
- **B (Moderate)**: Minor facts untraceable but non-core, explainable small deviations exist
- **C (Needs Supplement)**: Core facts have UNVERIFIED or FACT ERROR, unexplained contradictions exist

```markdown
### Final Rating

**Report Overall Quality**: [A/B/C]

**Disputed Points Requiring Attention**: [list]
**Recommended Corrections**: [list]
```
