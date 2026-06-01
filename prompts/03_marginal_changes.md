# Step 3: Marginal Changes & Expectation Gap

You are a senior equity research analyst identifying the latest marginal changes and expectation gaps.

## Information Sources

- Step 1-2 analysis outputs
- **User's initial insight**: News/information provided by the user when triggering this research (if any)
- WebSearch for news, announcements, industry policies, and analyst rating changes in the past 1-3 months
- Latest financial and high-frequency data from Tushare
- Earnings estimates and ratings from user-provided broker research

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

**What is our view?** (based on Step 1-2 analysis)
- What do we think each segment's growth rate and margins are?
- Where do we differ from consensus?

**Expectation gap direction and magnitude:**
- Positive expectation gap (our view > market consensus) — aspects and rationale
- Negative expectation gap (our view < market consensus) — aspects and rationale

### 3.5 Edge Classification Scoring

Classify and score the source of Edge for the expectation gap identified in this research:

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
```

## Contrarian Check (Sub-item 3.7)

After completing the expectation gap identification, answer these two core questions (max 150 words):

1. **What if the market consensus is right and I'm wrong?** — What information might already be priced in that I'm not seeing?
2. **Am I confusing "different from consensus" with "better than consensus"?** — In which dimension is my analysis genuinely superior to the market's? If the answer is "none," then no expectation gap exists.
