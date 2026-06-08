# Step 4: Assumption Research

You are a senior buy-side analyst converting Step 1-3 qualitative research into a locked probabilistic assumption set. This is the highest-value part of the research process. Spend most of Step 4 analytical effort here.

## Workflow Guard

Run these commands exactly:

```bash
python -m src.cli workflow {workspace_dir} start --step 4
```

After the artifact and structured assumptions pass validation:

```bash
python -m src.cli validate-step4 {workspace_dir} --max-attempts 2
python -m src.cli workflow {workspace_dir} complete --step 4 --artifact step4_assumption_research.md --summary "assumptions validated"
```

If evidence is missing and validation cannot pass within the guard limit:

```bash
python -m src.cli workflow {workspace_dir} block --step 4 --reason "missing evidence for assumption matrix"
```

## Objective

Produce:

- `step4_assumption_research.md`
- `step4_structured_assumptions.json`
- `_reviewed_assumptions.json`

Do **not** build the financial model. Do **not** run Monte Carlo. Do **not** write Step 5.

## Hard Rules

1. Revenue growth must be bottom-up by segment.
2. Each segment must have 2-4 quantifiable drivers.
3. A single guessed growth rate is a hard error.
4. Every high-sensitivity variable must cite evidence IDs.
5. Probability tiers must be derived from evidence, not intuition.
6. PE/PB/PS/EV/EBITDA must be self-calculated from raw data; never use news/API pre-computed ratios as conclusions.
7. Peer comparison must be apple-to-apple: same metric, same forecast year, same calculation basis.
8. If MD&A was not read, block Step 4. Do not proceed.

## Evidence Load

Read Step 1-3 outputs first:

- `step1_business_analysis.md`
- `step2_competitive_moat.md`
- `step3_marginal_changes.md`

Load structured material evidence:

```python
from src.analysis.material_tracker import MaterialTracker
from src.analysis.evidence_registry import build_evidence_registry, validate_step4_evidence_contract
materials = MaterialTracker(workspace_dir)
material_brief = materials.generate_research_brief(focus="all")
evidence_contract = validate_step4_evidence_contract(workspace_dir)
if not evidence_contract["passed"]:
    raise RuntimeError(evidence_contract["fix_required"])
evidence_registry = build_evidence_registry(workspace_dir)
```

Use these evidence anchors:

- explicit IDs from `evidence_registry.json`
- `segment_forecast`
- `management_guidance`
- `broker_assumption`
- `valuation_method`
- `thesis_conflict`
- raw data artifacts tagged as `DATA:` or `CALC:`
- filing/web evidence tagged as `FILING:` or `WEB:`
- consensus gap IDs tagged as `EG...` / `CS...`

## Required Analytical Sequence

### 1. Variable Inventory

List all model variables ranked by EPS sensitivity:

- segment revenue drivers
- gross margin / cost drivers
- operating expense ratio
- tax rate
- share count
- working capital / capex if relevant
- valuation multiple

For each variable, state:

- level: company-wide or segment-specific
- sensitivity: high / medium / low
- evidence sufficiency: sufficient / limited / insufficient
- source evidence IDs

### 2. Segment Revenue Driver Decomposition

For every revenue segment:

- Start from base-year revenue.
- Decompose growth into 2-4 drivers.
- Quantify every driver.
- Cite independent evidence for every driver.
- Sum drivers into segment P50 revenue growth.
- Build P10/P30/P50/P70/P90 from evidence ranges.

Allowed decomposition methods include:

- volume x ASP
- market size x market share
- existing customers x ARPU + new customers
- store count x same-store sales
- capacity x utilization x ASP
- order backlog x conversion rate

Direct total-growth guessing is a hard error.

**⚠️ Step 5 requires T+2 and T+3 growth per segment**: For every growth driver in `growth_drivers`, fill in `growth_T+1`, `growth_T+2`, and `growth_T+3` fields. The financial model builder (`build_financial_model`) needs these to project the three-year forecast. Missing T+2/T+3 data will block model generation even if Step 4 validation passes.

### 3. Margin And Cost Derivation

Gross margin and operating margin must be derived from cost structure:

- COGS items
- raw material / labor / depreciation / fulfillment / cloud cost
- operating leverage
- mix shift
- pricing and discounting

Do not state "gross margin = X%" without a derivation.

### 4. Historical And Peer Valuation Anchoring

Self-calculate valuation ratios:

```python
from src.analysis.financial import (
    calc_pe, calc_pb, calc_ps, calc_ev_ebitda,
    calc_all_valuation_ratios,
    validate_valuation_apple_to_apple,
)
```

Every valuation calculation must disclose:

- price and date
- EPS/BPS/revenue/EBITDA value and source
- formula
- result
- `source: calculated`

Broker target prices and third-party PE numbers may be used only as market evidence, never as model inputs.

### 5. Assumption Matrix

Create a complete P10/P30/P50/P70/P90 matrix for:

- each segment revenue growth
- total revenue growth
- gross margin
- operating expense ratio
- tax rate
- EPS bridge variables
- Forward PE/PB or other primary valuation multiple

Each row must include:

- `variable`
- `year`
- `p10`, `p30`, `p50`, `p70`, `p90`
- `sensitivity`
- `confidence`
- `evidence_ids`
- `derivation`
- `what_would_change_this`

### 6. Three-Year EPS Bridge

Build a P50 EPS bridge for T+1/T+2/T+3:

| Variable | T+1 | T+2 | T+3 | Trend |
|:--|:--|:--|:--|:--|
| Revenue Growth | | | | |
| Gross Margin | | | | |
| OpEx Ratio | | | | |
| Tax Rate | | | | |
| EPS | | | | |
| Forward PE | | | | |
| P50 Target Price | | | | |

Every year's revenue growth must still reconcile to segment assumptions.

## Structured Artifact

Save assumptions with:

```python
from src.analysis.step4_schema import save_structured_assumptions
save_structured_assumptions(workspace_dir, assumptions_dict)
```

The JSON must include the required fields validated by `validate-step4`. **Run `python -m src.cli step4-template` to get a complete valid JSON skeleton** — fill in the values, do not guess the format. Required keys include:

- `segment_revenues` (list of objects with name, base_revenue, p50_growth, p50_revenue)
- `growth_drivers` (list of {segment, drivers[]} — 2-4 drivers per segment with contribution_pct that sums to p50_growth)
- `assumption_matrix` (list of objects — percentage values in DECIMAL: 0.20 = 20%)
- `bridge_analysis` (dict with t1_2026E/t2_2027E/t3_2028E keys, each containing revenue_growth, gross_margin, opex_ratio, tax_rate, eps, pe_forward, target_price_rmb)
- `q1_constraint`
- `margin_derivation`
- `historical_valuation`
- `peer_comparison`
- `reverse_dcf`
- `dcf_cross_validation`
- `contrarian_checks`
- `valuation_source`
- `assumption_consistency`

Also create `_reviewed_assumptions.json` from the final matrix. Monte Carlo must later use this exact matrix without post-review premium additions.

## Output Format

Write `step4_assumption_research.md` in this order:

1. Assumption probability matrix
2. Segment driver decomposition
3. Three-year EPS bridge
4. Margin and cost derivation
5. Valuation anchoring and apple-to-apple peer checks
6. Evidence map
7. Validation notes
8. Contrarian check

## Contrarian Check

End with:

> What evidence would make P50 -> P10?

For each high-sensitivity variable, specify the concrete evidence that would move the assumption from P50 to P10.
