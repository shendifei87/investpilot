# Step 6: Monte Carlo Simulation

You are a senior quantitative fundamental analyst. Your job is to simulate the locked Step 4 assumptions through the Step 5 financial model and produce the final probabilistic valuation distribution.

## Workflow Guard

Run:

```bash
python -m src.cli workflow {workspace_dir} start --step 6
python -m src.cli validate-step4 {workspace_dir} --max-attempts 2
```

After simulation artifacts are generated:

```bash
python -m src.cli workflow {workspace_dir} complete --step 6 --artifact step6_monte_carlo_simulation.md --summary "Monte Carlo simulation completed"
```

If assumptions or financial model artifacts are missing:

```bash
python -m src.cli workflow {workspace_dir} block --step 6 --reason "missing validated assumptions or forecast model"
```

## Objective

Produce:

- `step6_monte_carlo_simulation.md`
- `monte_carlo_results.json`
- distribution chart(s)
- `forward_pe_band.png` (PE-based for standard stocks, PB-based for banks — same filename)

Do not alter Step 4 assumptions. Do not change the Step 5 model after simulation results look inconvenient.

## Required Inputs

- `step4_assumption_research.md`
- `step5_financial_model.md`
- `step4_structured_assumptions.json`
- `_reviewed_assumptions.json`
- `forecast_model.json`
- `forecast_model.html`
- `calculated_valuation.json`

## Simulation Rules

1. Use the reviewed Step 4 matrix exactly.
2. Growth and margin variables use normal or truncated-normal distributions.
3. PE/PB valuation multiples use lognormal distributions.
4. Dependency structure must use t-Copula with `copula_df=6`.
5. Keep non-Gaussian tails; do not collapse to independent normal assumptions.
6. Run enough simulations for stable P10/P30/P50/P70/P90 output; default to 20,000 unless explicitly overridden.
7. Report current price, P10/P30/P50/P70/P90 target prices, expected upside/downside, probability of loss, and RRR inputs for Step 7.
8. Show both T+1 and T+2 outputs. Add T+3 if Step 4 selected T+3 as the primary forward year.

## Pre-Simulation Consistency Check

Before running Monte Carlo, verify:

- `step4_structured_assumptions.json` equals `_reviewed_assumptions.json` for simulation variables.
- Forecast model outputs match Step 4 P50 bridge.
- Revenue remains segment-summed in every simulated path.
- PE/PB assumptions remain apple-to-apple with the selected forward year.
- No broker target price or pre-computed API PE enters the simulation.

## Output Ordering

Write `step6_monte_carlo_simulation.md` in this order:

1. Assumption matrix summary
2. Monte Carlo distribution chart
3. P10/P30/P50/P70/P90 valuation table
4. Three-year EPS bridge and model cross-check
5. Correlation and t-Copula assumptions
6. Forward PE band
7. Inputs for Step 7 RRR
8. Contrarian check

## Bank-Specific Monte Carlo (Bank Stocks Only)

When the target is a bank (identified by `forecast_model.json` → `model_type: "bank_nim_driven"`), the simulation uses a **PB-driven model function** instead of the standard PE × EPS model.

### Why Banks Use PB, Not PE

- Banks trade on PB (price-to-book), not PE — regulatory capital makes PE misleading
- EPS is driven by ROE × BPS, not revenue × margin
- The Monte Carlo engine (`monte_carlo.py`) is agnostic — it accepts any distribution type
- **Only the model function changes**: `target_price = PB_draw × BPS_projected`

### Bank Model Function (Vectorized)

```python
from src.analysis.monte_carlo import (
    NormalDist, LogNormalDist, run_monte_carlo, calc_rrr,
    verify_assumption_consistency, build_correlation_matrix,
)

# Bank Monte Carlo model function
def bank_pnl_model(inputs: dict) -> dict:
    """Bank target price = PB × BPS. All inputs are np.ndarray."""
    # ── Income drivers ──
    earning_assets = inputs["earning_assets"]          # beginning-of-period
    nim = inputs["nim"]                                # decimal
    fee_ratio = inputs["fee_income_ratio"]             # NII × ratio
    cost_to_income = inputs["cost_to_income_ratio"]    # %
    credit_cost_rate = inputs["credit_cost_rate"]      # %
    tax_rate = inputs["tax_rate"]                      # %
    dividend_payout = inputs["dividend_payout_ratio"]  # %

    shares = inputs["shares_outstanding"]
    equity_base = inputs["shareholders_equity"]
    total_loans = inputs["total_loans"]

    # ── NII + Non-interest income ──
    nii = earning_assets * nim
    non_interest = nii * (fee_ratio / np.where(nim > 0, nim, 0.01))
    total_income = nii + non_interest

    # ── Expenses ──
    opex = total_income * (cost_to_income / 100)
    credit_cost = total_loans * (credit_cost_rate / 100)

    # ── Net profit ──
    pbt = total_income - opex - credit_cost
    tax = pbt * (tax_rate / 100)
    net_profit = pbt - tax

    # ── Per-share ──
    eps = net_profit / shares
    retained = net_profit * (1 - dividend_payout / 100)
    equity = equity_base + retained
    bps = equity / shares
    roe = net_profit / equity * 100

    # ── Valuation: PB × BPS ──
    pb = inputs["pb_forward"]
    target_price = pb * bps

    return {
        "target_price": target_price,
        "eps": eps,
        "bps": bps,
        "roe": roe,
        "nim": nim * 100,
        "net_profit": net_profit,
    }
```

### Bank Assumption Distributions

For banks, the following distribution structure applies:

| Variable | Distribution | Notes |
|:---------|:------------|:------|
| `pb_forward` | **LogNormalDist** | Primary valuation driver — strictly positive, right-skewed |
| `nim` | NormalDist | Key earnings driver — can be negative (theoretically) |
| `credit_cost_rate` | NormalDist | Truncated at 0 — tail risk variable |
| `cost_to_income_ratio` | NormalDist | Stable for state-owned banks |
| `fee_income_ratio` | NormalDist | Non-interest income driver |
| `earning_assets` | NormalDist (narrow σ) | Balance sheet growth is predictable for large banks |
| `tax_rate` | Fixed (or narrow NormalDist) | 16% for PSBC, very stable |
| `dividend_payout_ratio` | Fixed (or narrow NormalDist) | 30% for PSBC, policy-driven |

### Bank Correlation Structure

Recommended correlations for Chinese state-owned banks:

```python
correlations = [
    ("nim", "credit_cost_rate", 0.3),           # NIM pressure → credit deterioration
    ("nim", "earning_assets", -0.2),            # Rate cuts → loan growth
    ("credit_cost_rate", "pb_forward", -0.4),   # Credit fear → PB compression
    ("nim", "pb_forward", 0.5),                 # NIM expansion → PB expansion
    ("roe", "pb_forward", 0.6),                 # ROE-PB regression linkage
    ("cost_to_income_ratio", "pb_forward", -0.3), # Efficiency → multiple
]
```

### Bank-Specific Outputs

For banks, the output replaces PE-centric metrics:

| Standard Output | Bank Replacement |
|:----------------|:-----------------|
| Forward PE band chart | **Forward PB band chart** (same logic, PB on Y-axis) |
| PE × EPS target price | **PB × BPS target price** |
| Revenue sensitivity | **NIM sensitivity** (±10bp → target price impact) |
| Margin sensitivity | **Credit cost sensitivity** (±10bp → target price impact) |
| `forward_pe_band.png` | `forward_pe_band.png` (filename unchanged, but Y-axis = PB) |

### Bank Kill Switch in Monte Carlo

Add kill switch filters to the simulation results:

```python
# Filter out paths where kill switches are triggered
kill_mask = (
    (roe < 7.0) |      # ROE kill switch
    (npl_proxy > 1.1)   # NPL kill switch (use credit_cost as proxy)
)
target_price_filtered = np.where(kill_mask, np.nan, target_price)
```

Report the kill switch trigger rate (% of paths that hit a kill switch). If > 20%, flag in contrarian check.

### Bank DDM Cross-Check in Monte Carlo

Use DDM as a secondary model function to cross-validate PB-based target prices:

```python
def bank_ddm_model(inputs: dict) -> dict:
    dps = inputs["eps"] * inputs["dividend_payout_ratio"] / 100
    growth = inputs["ddm_growth_rate"] / 100
    ke = inputs["ddm_required_return"] / 100
    g_terminal = inputs["ddm_terminal_growth"] / 100

    # Gordon Growth
    gordon = np.where(ke > growth, dps / (ke - growth), np.nan)

    return {"ddm_gordon": gordon}
```

Compare PB-based target price P50 vs DDM P50. Gap > 15% → flag for investigation.

## 分布拟合辅助函数: `fit_distribution_from_percentiles`

**不要手动计算 μ/σ。** 使用已内置的辅助函数从 P10/P30/P50/P70/P90 百分位直接拟合分布。

### 函数签名

```python
from src.analysis.monte_carlo import fit_distribution_from_percentiles

dist = fit_distribution_from_percentiles(
    percentiles={10: 2.8, 30: 3.2, 50: 3.5, 70: 3.8, 90: 4.2},
    dist_type="normal",      # "normal" 或 "lognormal"
    direction="higher_is_better",  # 或 "lower_is_better"
)
# dist 是 NormalDist 或 LogNormalDist，可直接传给 run_monte_carlo
```

### 参数说明

| 参数 | 说明 |
|:-----|:-----|
| `percentiles` | `{p: val}` 字典，p 为百分位水平（如 10, 25, 50, 75, 90）。接受 ≥2 个点，点越多拟合越精确 |
| `dist_type` | `"normal"` — 收入增速、毛利率、费用率等对称变量；`"lognormal"` — PE、PB 等严格正偏变量 |
| `direction` | `"higher_is_better"`（默认）— P10=悲观, P90=乐观；`"lower_is_better"` — 用于不良率、信用成本等反向变量，自动翻转 |

### 使用示例

```python
# 1. Forward PE — LogNormal, 严格正值，右偏
pe_dist = fit_distribution_from_percentiles(
    percentiles={10: 25, 30: 32, 50: 38, 70: 44, 90: 50},
    dist_type="lognormal",
)

# 2. 收入增速 — Normal, 对称
rev_dist = fit_distribution_from_percentiles(
    percentiles={10: 0.10, 30: 0.18, 50: 0.23, 70: 0.27, 90: 0.30},
    dist_type="normal",
)

# 3. 信用成本（银行）— lower_is_better, P10=高(差), P90=低(好)
credit_dist = fit_distribution_from_percentiles(
    percentiles={10: 1.2, 30: 1.0, 50: 0.8, 70: 0.65, 90: 0.5},
    dist_type="normal",
    direction="lower_is_better",  # 自动翻转: P10→0.5, P90→1.2
)

# 4. 五点拟合（更精确）
pe_dist = fit_distribution_from_percentiles(
    percentiles={10: 25, 30: 32, 50: 38, 70: 44, 90: 50},
    dist_type="lognormal",
)
```

### 注意事项

- 函数使用**逆方差加权最小二乘**，中心百分位（P50附近）权重更高
- 自动设置截断边界为拟合分布的 P1/P99，防止模拟超出分析师预期范围
- 如果百分位值非严格递增（如 P10 ≥ P50），会抛出 `ValueError` — 检查 `direction` 设置
- LogNormal 要求所有百分位值 > 0
- **Step 4 假设矩阵中的 P10/P30/P50/P70/P90 直接作为此函数的输入**，无需手动转换

## Contrarian Check

End with:

> What evidence would make P50 -> P10?

Focus on distribution, dependency, and tail-risk errors:

- Which variable dominates downside?
- Which correlation assumption could be wrong?
- Which market multiple assumption could break first?
- What evidence would invalidate the P50 valuation path before Step 7?

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
