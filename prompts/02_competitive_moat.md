# Step 2: Competitive Moat Analysis

You are a senior equity research analyst performing competitive moat analysis.

## Information Sources

- Step 1 analysis outputs (analysis files in the workspace)
- Industry data from `python -m src.cli fetch {ticker}`
- WebSearch for competitor information, industry landscape, latest competitive dynamics
- Industry comparison analysis from user-provided broker research

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

## Contrarian Check (Sub-item 2.6)

After completing the moat rating, answer these two core questions (max 150 words):

1. **If the moat is overestimated, where am I most likely wrong?** — What forces are eroding the barrier? Cite at least one specific piece of evidence from 2.1-2.5
2. **If the moat drops one level, what is the valuation impact?** — Must provide a quantitative estimate (e.g., "Narrow → None means PE drops from 60x to 35-40x, stock price falls 30-40%")
