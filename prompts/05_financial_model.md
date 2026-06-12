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
- **HK**: Historical financials from AKShare `stock_hk_financial_indicator_em()` + `stock_hk_daily()`. Report in HKD or RMB (match company reporting currency). Follow HKFRS conventions.
- **WebFetch fallback**: If IR pages are blocked by security policy, use alternative domains listed in `config/ir_domains.py`.
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

## Phase 4: Bank-Specific Model (Bank Stocks Only)

When the research target is a **bank** (identified by `detect` market category or Step 1 classification), use the NIM-driven earnings model instead of the standard EPS = Revenue × Margin framework.

### Why Banks Are Different

Standard models break for banks because:
- Revenue = Net Interest Income + Non-Interest Income, not "units × price"
- Margin = NIM (Net Interest Margin), not gross margin
- Capital adequacy (CAR) constrains balance sheet growth
- Credit cost is the primary earnings volatility driver
- DDM (Dividend Discount Model) replaces DCF as the auxiliary valuation

### Bank Model Engine

```python
from src.analysis.bank_financial_model import (
    project_bank_earnings,
    ddm_valuation,
    save_bank_model,
    BANK_MODEL_INPUTS,
)
```

**Inputs** (all from Step 4 assumptions):

| Input | Description | Typical Source |
|:------|:------------|:---------------|
| `earning_assets` | 生息资产 (beginning) | Balance sheet |
| `total_loans` | 客户贷款总额 | Balance sheet |
| `shareholders_equity` | 归属母公司股东权益 | Balance sheet (deducted minority) |
| `shares_outstanding` | 总股本 | Share data |
| `nim` | 净息差 (decimal, e.g. 0.0166) | Income statement / NII ÷ earning assets |
| `fee_income_ratio` | 非息收入占比 | Income statement |
| `cost_to_income_ratio` | 成本收入比 (%) | Income statement |
| `credit_cost_rate` | 信用成本率 (bps) | Provision ÷ avg loans |
| `earning_assets_growth` | 生息资产增速 (%) | Step 4 assumption |
| `nim_change_bp` | NIM 变动 (bp/year) | Step 4 assumption |
| `loan_growth` | 贷款增速 (%) | Step 4 assumption |
| `dividend_payout_ratio` | 分红比率 (%) | Dividend policy |
| `tax_rate` | 有效税率 (%) | Income statement |

**Per-period overrides**: Any growth/assumption input can be a list `[T+1, T+2, T+3]` instead of a scalar.

### Bank Model Outputs

```python
model = project_bank_earnings(inputs, periods=3)
# model["periods"] — list of T+1/T+2/T+3 projections (EPS, BPS, ROE, NIM, DPS)
# model["sensitivity"]["nim_sensitivity"] — EPS under NIM ±10bp
# model["sensitivity"]["credit_cost_sensitivity"] — EPS under credit cost ±10bp
```

### DDM Valuation (Bank Auxiliary)

DDM replaces DCF for bank stocks. Use `ddm_valuation()`:

```python
ddm = ddm_valuation(
    dps_t1=0.25,           # Expected DPS in T+1
    growth_rate=3.0,       # Dividend growth rate %
    required_return=8.0,   # Required return % (cost of equity)
    terminal_growth=2.0,   # Terminal growth % (default: growth - 1%)
)
# Returns: intrinsic_value_gordon, intrinsic_value_2stage, validity
```

**DDM parameters from Step 4**:
- `dps_t1`: from bank model projection (EPS × payout ratio)
- `growth_rate`: long-term sustainable earnings growth (usually 2-4% for large banks)
- `required_return`: COE from CAPM or dividend yield + growth
- `terminal_growth`: long-run GDP nominal growth (1.5-2.5%)

### Bank Model Output Files

Save to workspace:
- `{ticker}_bank_model.json` — machine-readable, feeds Step 6 Monte Carlo
- `step5_bank_model_summary.md` — narrative explanation

### Bank Excel Model (`step5_3statement_model.xlsx`)

Bank stocks use a separate Excel generator (`src/analysis/bank_excel_model.py`) that produces a 6-tab workbook. The CLI auto-detects bank models via `forecast_model.json` → `model_type: "bank_nim_driven"` and routes to `build_bank_excel()`.

**Column layout**: Col A = labels, Col B = FY(n-1)A, Col C = FY(n)A (base), Col D/E/F = T+1/T+2/T+3. Historical values in black, projections in blue.

#### Tab 1: NII Build
Purpose: Decompose Net Interest Income into earning assets × NIM.

| Row | Content | Source |
|:----|:--------|:-------|
| 生息资产 (平均) | Earning assets by year | Bank model `earning_assets` |
| YoY 增速 (%) | Growth rate per year | Step 4 `earning_assets_growth` |
| 净息差 NIM (%) | NIM path with bp changes | Bank model `nim_pct` |
| 净利息收入 NII | EA × NIM | Bank model `net_interest_income` |
| 非利息收入 | Fee + other income | Bank model `non_interest_income` |
| **营业收入合计** | NII + Non-NII | Bank model `total_operating_income` |

#### Tab 2: Income Statement
Purpose: Full P&L from operating income to EPS/BPS/ROE.

| Row | Content | Format |
|:----|:--------|:-------|
| 净利息收入 / 非利息收入 / 营业收入合计 | Revenue lines | 亿元 |
| 营业支出 | OpEx = CTI × revenue | 亿元 |
| 信用减值损失 | Credit cost = avg loans × CC rate | 亿元 |
| 利润总额 / 净利润 | PBT / Net profit | 亿元 |
| EPS / BPS / ROE / DPS | Per-share metrics | 元 / % |
| 利润率分析 | NIM, ROE, CTI by year | % |

#### Tab 3: Balance Sheet
Purpose: Assets, liabilities, equity projection with balance check.

| Section | Key Items |
|:--------|:----------|
| 资产 | 现金及存放央行, 客户贷款, 金融投资, 存放同业, 其他 |
| 负债 | 客户存款, 同业存放, 应付债券 |
| 权益 | 归母权益, 少数股东权益 |
| **平衡检查** | 资产 − 负债 − 权益 = 0 (mandatory) |

#### Tab 4: Key Ratios
Purpose: Track all banking KPIs and kill switches.

| Ratio | Kill Switch / Threshold |
|:------|:------------------------|
| NIM (%) | Monitor decline >10bp |
| ROE (%) | Kill if < 7.0% |
| 成本收入比 (%) | Monitor reversal above 55% |
| 信用成本率 (%) | Monitor spike above 0.80% |
| NPL (%) | **Kill if > 1.1%** |
| 拨备覆盖率 (%) | Monitor below 280% |
| CAR (%) | Target ≥ 13.5% |
| 分红比率 (%) | Stable at 30% |

#### Tab 5: Valuation Bridge
Purpose: Multi-method target price comparison.

| Section | Methods |
|:--------|:--------|
| PB × BPS (Primary) | BPS × PB(P50) → target price, upside % |
| DDM (Auxiliary) | Gordon Growth model, 2-Stage DDM, upside % |
| PE (Reference only) | PE × EPS for reference (NOT primary for banks) |

#### Tab 6: Assumptions & Checks
Purpose: Step 4 assumption lock + model integrity verification.

| Section | Content |
|:--------|:--------|
| Assumptions lock | All P50 values traced to Step 4, with source tags |
| Integrity checks | EPS/BPS/ROE vs Step 4 bridge, NIM path, credit cost |
| Kill switch status | NPL and ROE thresholds with current values |

**Auto-generation**: When `save_bank_model()` is called, it auto-generates `forecast_model.html` from `forecast_model.json`. The CLI `cmd_excel_model()` detects `model_type == "bank_nim_driven"` and routes to `build_bank_excel()` automatically.

### Bank Valuation Framework (Hard Rule)

For banks, the valuation hierarchy is:

| Priority | Method | Purpose |
|:---------|:-------|:--------|
| **Primary** | PB × BPS | Relative valuation anchor |
| **Secondary** | PB/ROE regression | Cross-sectional comparison with peers |
| **Auxiliary** | DDM | Absolute valuation cross-check |
| **Not used** | DCF (FCF) | FCF is meaningless for banks |
| **Not used** | EV/EBITDA | EBITDA doesn't exist for banks |

All PB calculations must use `calc_pb` with `deduct_minority=True` — banks often have significant minority interests from subsidiaries.

### Bank Monte Carlo (Step 6 Adaptation)

When the target is a bank, Step 6 Monte Carlo uses:
- **PB distribution** (lognormal) instead of PE
- **ROE distribution** (normal) as the key driver
- **NIM distribution** (normal) for sensitivity
- **Credit cost distribution** (normal) for tail risk
- Correlation structure: t-Copula with copula_df=6

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

---

## MCP 参数限制

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
