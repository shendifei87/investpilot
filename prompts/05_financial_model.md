# Step 5: Financial Model Build

You are a senior financial modeling analyst. Your job is to convert the locked Step 4 assumptions into a formula-linked three-year model. Do not change the assumptions.

## Workflow Guard

Run:

```bash
python -m src.cli workflow {workspace_dir} start --step 5
python -m src.cli validate-step4 {workspace_dir} --max-attempts 2
```

After model artifacts are generated and checked:

```bash
python -m src.cli workflow {workspace_dir} complete --step 5 --artifact step5_financial_model.md --summary "three-statement model + DCF cross-validation generated"
```

If the Step 4 assumptions fail validation, block Step 5 instead of repairing forever:

```bash
python -m src.cli workflow {workspace_dir} block --step 5 --reason "Step 4 assumptions failed validation"
```

## Objective

Step 5 produces **three layers** of output, each serving a different purpose:

| Layer | Tool | Output | Purpose |
|:------|:-----|:-------|:--------|
| A. Internal Model | `financial_model.py` | `forecast_model.json` + `.html` | Machine-readable, feeds Step 6 Monte Carlo |
| B. Professional Excel | `python -m src.cli excel-model` | `step5_3statement_model.xlsx` | Human-readable, formula-linked three-statement model with live formulas |
| C. DCF Cross-Check | `dcf-model` skill | `step5_dcf_crosscheck.xlsx` + `step5_dcf_summary.md` | Absolute valuation anchor, cross-validates Layer A/B |

**Layer B is the primary deliverable for human review. Layer A is the primary input for Monte Carlo.**

## Phase 1: Internal Model (Python Pipeline)

Generate the internal auditable model first — it validates that Step 4 assumptions are complete and internally consistent:

```bash
python -m src.cli model {workspace_dir} --ticker {ticker}
```

**Inputs** (required in workspace):
- `step4_assumption_research.md`
- `step4_structured_assumptions.json`
- `_reviewed_assumptions.json`
- `calculated_valuation.json`

**Outputs**:
- `forecast_model.json` — formula-linked model with explicit lineage tracking
- `forecast_model.html` — rendered HTML view

**Model Integrity Checks** (must pass before proceeding to Phase 2):
- No hard-coded total revenue growth if segment drivers exist
- All P&L outputs trace to Step 4 assumptions
- Model has no assumptions absent from `_reviewed_assumptions.json`
- T+1/T+2/T+3 EPS reconcile to the bridge
- Formula references are explainable in `forecast_model.json`
- Every forecast output has lineage to Step 4 assumptions or explicit financial model inputs
- `defaults_used` must be empty
- `forecast_model.html` is readable and suitable as a final report appendix

If any check fails, **do NOT proceed to Phase 2** — return to Step 4 or block Step 5.

## Phase 2: Professional Three-Statement Excel Model (Python Pipeline)

After Phase 1 passes integrity checks, run the dedicated Excel generator:

```bash
python -m src.cli excel-model {workspace_dir} --ticker {ticker}
```

This produces `step5_3statement_model.xlsx` — a professional, formula-linked workbook built from `forecast_model.json` and `step4_structured_assumptions.json`. Revenue is decomposed into **multiplicative drivers** (e.g., Volume × ASP), never from a bare growth-rate × base formula.

### 2.1 Data Source

All inputs come from Step 4 outputs — **do NOT invent new assumptions**:

| Input | Source |
|:------|:-------|
| Historical financials (3 years) | Annual report PDFs in workspace + Tushare `income`/`balancesheet`/`cashflow` |
| Revenue by segment | `step4_structured_assumptions.json` → `segment_revenues` |
| Growth rates by segment | `step4_structured_assumptions.json` → `assumption_matrix` |
| Gross margin | `step4_structured_assumptions.json` → `assumption_matrix` (gross_margin) |
| OpEx ratio | `step4_structured_assumptions.json` → `assumption_matrix` (opex_ratio) |
| Tax rate | `step4_structured_assumptions.json` → `assumption_matrix` (tax_rate) |
| D&A ratio, Capex ratio, NWC ratio | `step4_structured_assumptions.json` → `financial_model_inputs` |
| Shares outstanding | `step4_structured_assumptions.json` → `financial_model_inputs.shares_outstanding` |
| Debt, Cash, Equity balances | `step4_structured_assumptions.json` → `financial_model_inputs` |
| Dividend payout ratio | `step4_structured_assumptions.json` → `financial_model_inputs.dividend_payout` |
| Forward PE | `step4_structured_assumptions.json` → `assumption_matrix` (pe) |

### 2.2 Excel Workbook Structure

The Excel generator (`src/analysis/excel_model.py`) produces `step5_3statement_model.xlsx` with 6 tabs:

**Tab 1: Revenue Build — Multiplicative Driver Decomposition**
- Each segment's revenue is built UP FROM drivers: `Revenue = Volume × ASP`, `Revenue = Market Size × Market Share`, etc.
- Drivers come from `step4_structured_assumptions.json` → `growth_drivers` (min 2, max 4 per segment)
- Individual drivers CAN have growth rates, market share, etc. as their own estimates
- Revenue is NEVER `Revenue = Base × (1 + growth_rate)` — the growth rate is the RESULT of driver math
- If drivers lack explicit base values, contribution_pct decomposition is used with a warning

**Tab 2: Income Statement**
- Revenue (by segment, then total)
- COGS
- **Gross Profit** (formula: Revenue - COGS)
- Selling Expenses
- General & Admin Expenses
- R&D Expenses
- **Operating Income / EBIT** (formula: Gross Profit - OpEx)
- Interest Expense
- Interest Income
- **Pre-tax Income / EBT** (formula: EBIT - Interest Exp + Interest Inc)
- Income Tax Expense
- **Net Income** (formula: EBT × (1 - tax_rate))
- **EPS (Basic)** (formula: Net Income / basic shares)
- **EPS (Diluted)** (formula: Net Income / diluted shares)
- Margin analysis row: Gross Margin %, EBIT Margin %, Net Margin % (all formula-driven)

**Tab 3: Balance Sheet**
- **Assets**:
  - Cash & Equivalents (linked from CF ending cash)
  - Accounts Receivable (Revenue × AR days / 365)
  - Inventory (COGS × inventory days / 365)
  - Prepaid Expenses & Other Current Assets
  - **Total Current Assets** (formula: SUM)
  - PP&E (formula: prior PP&E + Capex - D&A)
  - Intangible Assets & Goodwill
  - Other Non-Current Assets
  - **Total Assets** (formula: SUM)
- **Liabilities**:
  - Accounts Payable (COGS × AP days / 365)
  - Short-term Debt / Current Portion of LT Debt
  - Accrued Liabilities
  - Deferred Revenue
  - **Total Current Liabilities** (formula: SUM)
  - Long-term Debt
  - Other Non-Current Liabilities
  - **Total Liabilities** (formula: SUM)
- **Equity**:
  - Common Stock / Paid-in Capital
  - Retained Earnings (formula: prior RE + Net Income - Dividends)
  - Treasury Stock (if buyback)
  - Other Comprehensive Income
  - Minority Interest (if applicable)
  - **Total Equity** (formula: SUM)
- **Balance Check row**: Total Assets - Total Liabilities - Total Equity (must = 0)

**Tab 4: Cash Flow Statement**
- **Operating Activities**:
  - Net Income (linked from IS)
  - Depreciation & Amortization (linked from assumption)
  - Changes in Working Capital (linked from BS changes):
    - Δ Accounts Receivable (prior AR - current AR)
    - Δ Inventory (prior Inv - current Inv)
    - Δ Accounts Payable (current AP - prior AP)
    - Δ Other Working Capital
  - Stock-based Compensation
  - Other Operating Items
  - **Cash from Operations** (formula: SUM)
- **Investing Activities**:
  - Capital Expenditure (negative, linked from assumption)
  - Acquisitions
  - Other Investing Items
  - **Cash from Investing** (formula: SUM)
- **Financing Activities**:
  - Debt Issuance / (Repayment)
  - Share Buyback
  - Dividends Paid (formula: Net Income × payout ratio)
  - **Cash from Financing** (formula: SUM)
- **Net Change in Cash** (formula: CFO + CFI + CFF)
- **Beginning Cash** (linked from prior period BS)
- **Ending Cash** (formula: Beginning + Net Change) — **must tie to BS Cash**

**Tab 5: Valuation Bridge**
- EPS by year (linked from IS)
- Forward PE by year (linked from assumption)
- Target Price by year (formula: EPS × PE)
- EV Bridge: Market Cap + Net Debt = Enterprise Value
- EV/EBITDA by year (formula)

**Tab 6: Assumptions & Checks**
- All Step 4 assumptions listed with source and value
- Balance Sheet integrity check: Assets - L&E = 0 for each year
- Cash tie-out: CF ending cash = BS cash for each year
- Retained Earnings rollforward: prior RE + NI - Div = current RE
- Working Capital validation: each component ties to BS
- Debt schedule linkage check
- Formula-over-hardcode audit: every projection cell must be a formula, never a typed number

### 2.3 Cross-Statement Integrity Checks (Hard Rules)

Before completing Phase 2, verify ALL of the following. If any check fails, fix the model:

| Check | Formula | Must Equal |
|:------|:--------|:----------|
| BS Balance | Total Assets − Total Liabilities − Total Equity | 0 |
| Cash Tie-out | CF Ending Cash | BS Cash & Equivalents |
| RE Rollforward | Prior RE + Net Income − Dividends | Current RE |
| NI Linkage | IS Net Income | CF Net Income (first line) |
| Revenue Linkage | IS Revenue | Segment revenue build total |
| FCF Consistency | NI + D&A − Capex − ΔNWC | Operating FCF approximation |

### 2.4 Professional Formatting Requirements

The Excel workbook must follow institutional standards:
- **Blue/grey color scheme**: Historicals in black, projections in blue font
- **Column headers**: Bold, with period labels (e.g., FY2024A, FY2025E, FY2026E, FY2027E)
- **Subtotals**: Bold, with single underline; Grand totals with double underline
- **No hard-coded projection numbers**: Every projected cell must be a formula
- **Source annotations**: Key assumptions should have cell comments with source (e.g., "Step 4 assumption, evidence_id: E042")
- **Number format**: #,##0 for absolute values; 0.0% for margins/ratios; 0.00x for multiples

### 2.5 Market Adaptation

- **A-share**: Historical financials from Tushare `income`/`balancesheet`/`cashflow` APIs. Report in CNY. Follow PRC GAAP line item conventions.
- **HK**: Historical financials from AKShare `stock_hk_finance()`. Report in HKD or RMB (match company reporting currency). Follow HKFRS conventions.
- **US**: Historical financials from SEC EDGAR (10-K/K-10). Report in USD. Follow US GAAP conventions.

## Phase 3: DCF Cross-Validation (Mandatory Skill)

After Phase 2 Excel model passes all integrity checks, **must** invoke `dcf-model` skill as an independent cross-check:

```
Skill("financial-analysis:dcf-model", args="{ticker} DCF 交叉验证，使用 Step 4 假设和 Step 5 预测模型参数")
```

**Input parameters** (derived from Step 4/5 outputs — do NOT invent new assumptions):
- Revenue forecasts: from Phase 2 IS segment schedule
- EBITDA margins: from Step 4 margin assumptions
- Capex / D&A / NWC: from Step 4 financial_model_inputs
- WACC: cost of equity (CAPM) + cost of debt + target capital structure
- Terminal growth rate: tied to long-term GDP + inflation ceiling
- Tax rate: from Step 4

**Output artifacts** (saved to workspace):
- `step5_dcf_crosscheck.xlsx` — professional DCF workbook with:
  - Free cash flow projection (T+1 through T+5 or T+10)
  - WACC calculation with sources for each input
  - Terminal value (perpetuity growth method + exit multiple method)
  - Enterprise value bridge → equity value → per-share value
  - Bear / Base / Bull scenarios
  - Sensitivity tables: terminal growth vs WACC, terminal multiple vs WACC
- `step5_dcf_summary.md` — cross-validation verdict

**Cross-validation discipline (hard rules)**:
1. **Independence**: DCF inputs must come from Step 4/5. Do NOT tweak DCF assumptions to match the relative valuation target price
2. **Convergence check**: Compare DCF implied share price vs relative valuation (PE × EPS). Record the gap:
   - Gap < 10%: both methods agree → high conviction
   - Gap 10–20%: investigate which method's assumptions are more defensible
   - Gap > 20%: **flag as material divergence** — document which method you trust more and why; consider blocking Step 5 if unresolvable
3. **No circularity**: DCF result does NOT override Step 4 assumptions. It informs Step 7 RRR by providing an absolute valuation anchor

## Output Format

Write `step5_financial_model.md` with the following sections:

1. **Model artifact links** — paths to all output files
2. **Assumption lock summary** — confirmation that Phase 1 integrity checks passed
3. **Revenue schedule** — segment revenue build summary
4. **Income statement forecast** — key IS line items with formula descriptions
5. **Balance sheet bridge** — key BS movements and balance check results
6. **Cash flow / FCF bridge** — CFO/CFI/CFF breakdown and cash tie-out results
7. **EPS and valuation schedule** — EPS bridge + target price by year
8. **Three-statement integrity checks** — all 6 cross-statement checks (from Phase 2.3)
9. **DCF Cross-Validation** — DCF vs PE-based target price, gap analysis, resolution
10. **Contrarian check**

**Required artifacts** (all saved to workspace):
1. `forecast_model.json` — from Phase 1 (machine-readable, feeds Step 6)
2. `forecast_model.html` — from Phase 1
3. `step5_3statement_model.xlsx` — from Phase 2 (primary human deliverable)
4. `step5_dcf_crosscheck.xlsx` — from Phase 3
5. `step5_dcf_summary.md` — from Phase 3
6. `step5_financial_model.md` — this narrative report

## Contrarian Check

End with:

> Under what model-linkage or accounting conditions would the Step 4 assumptions fail to produce the claimed EPS?

List formula, accounting, and reconciliation risks. If any risk is material, return to Step 4 or block Step 5.
